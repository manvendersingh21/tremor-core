"""Web API handlers over a fake backend: SSE, limits, firewall, secrets, 20 parallel calls, health, stats."""
import concurrent.futures as cf
import http.client
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from chimera_core.config import ChimeraConfig
from chimera_core.router import RouterConfig, SpeculativeCascadeRouter
from chimera_core.service import Service, handle_http, scrub
from chimera_core.tiers import TierCfg, TierPool

from chimera_core.cache.pgvector_cache import PgVectorCache

from test_events import Bag, Fake, tier
from test_pgvector_cache import FakeStore, settle


def router(small=None, shared=None):
    fakes = {"small": small or Fake("small", conf=0.99), "big": Fake("big")}
    tiers = [tier("small", 0.5, device="laptop"), tier("big", 1.0, cost=0.001, device="cloud")]
    pool = TierPool(tiers, min_confidence=0.95, probe=lambda t: True, backend_factory=lambda t: fakes[t.name])
    shared = shared or PgVectorCache(Bag(), FakeStore())  # the only cache, as in production (Supabase stand-in)
    return SpeculativeCascadeRouter(None, pool=pool, embedder=Bag(), shared=shared, config=RouterConfig())


@pytest.fixture
def server():
    made = []

    def start(svc):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                handle_http(self, "GET", svc) or self.send_error(404)

            def do_POST(self):
                handle_http(self, "POST", svc) or self.send_error(404)

        class Srv(ThreadingHTTPServer):
            request_queue_size = 64  # the stdlib default of 5 resets bursts of 20 connections

        srv = Srv(("127.0.0.1", 0), H)
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        made.append(srv)
        return srv.server_address[1]

    yield start
    for s in made:
        s.shutdown()


def post(port, body, raw=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    c.request("POST", "/api/chat", raw if raw is not None else json.dumps(body), {"Content-Type": "application/json"})
    r = c.getresponse()
    data = r.read().decode()
    return r.status, dict(r.getheaders()), data


def parse(sse):
    out = []
    for block in sse.strip().split("\n\n"):
        ev, data = block.split("\n")
        out.append((ev[7:], json.loads(data[6:])))
    return out


def test_chat_streams_steps_then_answer_then_done(server):
    svc = Service(router(), ChimeraConfig(), rate_per_min=600, burst=50)
    port = server(svc)
    status, headers, body = post(port, {"prompt": "what is two plus two"})
    ev = parse(body)
    assert status == 200 and headers["Content-Type"] == "text/event-stream"
    assert [e for e, _ in ev] == ["embed", "cache_shared", "memory", "decide", "call", "draft", "memory", "final",
                              "answer", "done"]
    assert dict(ev)["answer"]["text"] == "small-answer"
    settle(svc.router.shared)
    status, _, body = post(port, {"prompt": "what is two plus two"})  # same prompt: Supabase exact hit
    assert dict(parse(body))["final"]["cache"] == "shared" and dict(parse(body))["cache_shared"]["kind"] == "exact"


@pytest.mark.parametrize("body,code,status", [
    ({"prompt": ""}, "invalid_request", 400), ({"nope": 1}, "invalid_request", 400),
    ({"prompt": "x" * 2001}, "prompt_too_long", 413),
    ({"prompt": "hi", "action": "git push --force origin main"}, "approval_required", 403),
])
def test_input_cap_and_firewall(server, body, code, status):
    port = server(Service(router(), ChimeraConfig(), rate_per_min=600, burst=50))
    s, _, text = post(port, body)
    assert s == status and json.loads(text)["error"]["code"] == code


def test_bad_json_and_oversize_body(server):
    port = server(Service(router(), ChimeraConfig()))
    assert post(port, None, raw="{nope")[0] == 400
    assert post(port, None, raw="x" * 20_000)[0] == 413


def test_20_parallel_requests_no_errors(server):
    slow = Fake("small", conf=0.99)
    port = server(Service(router(slow), ChimeraConfig(), rate_per_min=6000, burst=20))
    with cf.ThreadPoolExecutor(20) as ex:
        res = list(ex.map(lambda i: post(port, {"prompt": f"question number {i} about sorting"}), range(20)))
    assert [s for s, _, _ in res] == [200] * 20
    for _, _, body in res:
        names = [e for e, _ in parse(body)]
        assert names[-2:] == ["answer", "done"] and "error" not in names


def test_rate_limit_is_enforced_per_ip(server):
    port = server(Service(router(), ChimeraConfig(), rate_per_min=1, burst=5))
    with cf.ThreadPoolExecutor(20) as ex:
        res = list(ex.map(lambda i: post(port, {"prompt": f"another question {i} please"}), range(20)))
    codes = sorted(s for s, _, _ in res)
    assert codes.count(200) == 5 and codes.count(429) == 15
    limited = next(h for s, h, _ in res if s == 429)
    assert int(limited["Retry-After"]) >= 1


def test_ip_header_cannot_dodge_the_limit():
    svc = Service(router(), ChimeraConfig(), rate_per_min=1, burst=1)
    list(svc.chat({"prompt": "one"}, "1.1.1.1"))
    with pytest.raises(Exception) as e:
        svc.chat({"prompt": "two"}, "1.1.1.1")
    assert e.value.status == 429
    list(svc.chat({"prompt": "three"}, "2.2.2.2"))  # another peer has its own bucket


def test_no_secret_or_prompt_in_stream_or_logs(monkeypatch, caplog):
    monkeypatch.setenv("CRUSOE_API_KEY", "sk-test-1234567890abcdef")
    monkeypatch.setenv("CHIMERA_DB_URL", "postgres://u:pw@db.example.test:5432/x")

    class Leaky(Fake):
        def complete(self, prompt, n):
            return "key is sk-test-1234567890abcdef and db postgres://u:pw@db.example.test:5432/x", 1, 1, 0.99

    svc = Service(router(Leaky("small")), ChimeraConfig())
    with caplog.at_level(logging.DEBUG):
        text = json.dumps(list(svc.chat({"prompt": "my private prompt text"}, "9.9.9.9")))
    assert "sk-test-1234567890abcdef" not in text and "db.example.test" not in text
    assert "[redacted]" in text
    assert "sk-test" not in caplog.text and "my private prompt" not in caplog.text
    assert scrub({"a": ["sk-test-1234567890abcdef"]}) == {"a": ["[redacted]"]}


def test_all_tiers_failed_is_an_error_event_without_details():
    r = router(Fake("small", fail=True))
    r.pool.tiers = r.pool.tiers[:1]
    ev = list(Service(r, ChimeraConfig()).chat({"prompt": "will fail"}, "3.3.3.3"))
    assert ev[-2][0] == "error" and ev[-2][1]["code"] == "all_tiers_failed" and ev[-1][0] == "done"


def test_health_and_stats_shapes_and_caching(tmp_path):
    cfg = ChimeraConfig(tiers=[
        TierCfg(name="mac", device="laptop", backend="llamacpp", url="http://127.0.0.1:1", model="m"),
        TierCfg(name="gpu", device="gpu", backend="ollama", url="http://127.0.0.1:2", model="m"),
        TierCfg(name="cr", device="cloud", backend="openai", url="https://api.inference.crusoecloud.com", model="m"),
        TierCfg(name="gm", device="cloud", backend="openai", url="https://api.gmi-serving.com", model="m")])
    calls = []
    svc = Service(router(), cfg, telemetry_path=tmp_path / "t.jsonl", modal_state=lambda: {"state": "stopped"},
                  probe=lambda t: calls.append(t.name) or t.name != "gm")
    h = svc.health()
    assert h["llama"]["up"] and not h["gmi"]["up"] and h["gpu_tunnel"]["up"] and h["crusoe"]["up"]
    assert h["modal"] == {"state": "stopped"} and "free_mb" in h["ram"]
    n = len(calls)
    svc.health()
    assert len(calls) == n  # second call inside 2 s is cached
    list(svc.chat({"prompt": "stats please"}, "4.4.4.4"))
    settle(svc.router.shared)
    list(svc.chat({"prompt": "stats please"}, "4.4.4.4"))
    s = svc.stats()["session"]
    assert s["calls"] == 2 and s["cache_hits"]["shared"] == 1 and s["hit_rate"] == 0.5 and s["tokens_kept_off_big"] > 0


def test_modal_state_reads_the_newest_gpu_large_app():
    from chimera_core.service import modal_state_of

    apps = [{"description": "chimera-gpu-large", "state": "stopped", "created_at": "2026-11-13 22:45"},
            {"description": "chimera-gpu-large", "state": "deployed", "created_at": "2026-11-14 01:00"},
            {"description": "chimera-img-check", "state": "deployed", "created_at": "2026-11-15 00:00"}]
    assert modal_state_of(apps) == "deployed"
    assert modal_state_of(apps[:1]) == "stopped"
    assert modal_state_of(apps[2:]) == "not_deployed"


def test_summarize_ui_fields():
    import time as _t

    from chimera_core.service import recent_calls, summarize

    now = _t.time()
    old = now - 3 * 86400
    rows = [
        {"tier_used": "gpu", "ts": now, "tokens_in": 10, "tokens_out": 5, "tokens_saved": 15, "dollars_saved": 0.01,
         "task": "chat", "conversation_id": "c1"},
        {"tier_used": "exact_cache", "cache_source": "shared", "ts": now, "tokens_saved": 7, "task": "chat",
         "conversation_id": "c1", "events": [{"step": "cache_shared", "score": 1.0}, {"step": "final", "model": "cache"}]},
        {"tier_used": "semantic_cache", "cache_source": "shared", "ts": old, "false_hit": True, "task": "code"},
        {"tier_used": "top", "ts": old, "tokens_in": 100, "tokens_out": 50, "dollars_spent": 0.002},
        {"tier_used": "local"},  # an old row with no ts: in totals, not in today or the series
    ]
    s = summarize(rows, now)
    assert s["tokens"] == 165 and s["tokens_today"] == 15 and s["calls_today"] == 2
    assert s["cache"]["today"] == {"exact": 1, "cosine": 0, "false_hits": 0}
    assert s["cache"]["all_time"] == {"exact": 1, "cosine": 1, "false_hits": 1}
    assert s["by_task"]["chat"]["calls"] == 2 and s["by_task"]["chat"]["cache_hits"] == 1
    assert s["by_task"]["other"]["calls"] == 2 and s["by_task"]["code"]["calls"] == 1
    assert s["by_conversation"] == {"c1": {"calls": 2, "tokens": 15, "cache_hits": 1, "tokens_saved": 22,
                                           "dollars_saved": 0.01, "last_ts": now}}
    daily = s["series"]["daily"]
    assert [d["calls"] for d in daily] == [2, 2] and daily[-1]["tokens_saved"] == 22
    assert sum(h["calls"] for h in s["series"]["hourly"]) == 2
    rc = recent_calls(rows, 3)
    assert [r["tier"] for r in rc] == ["local", "top", "semantic_cache"] and len(recent_calls(rows)) == 5
    assert recent_calls(rows)[3]["score"] == 1.0 and recent_calls(rows)[3]["steps"][0]["step"] == "cache_shared"


def test_chat_tags_reach_stats_and_bad_ids_are_refused(tmp_path):
    svc = Service(router(), ChimeraConfig(), rate_per_min=600, burst=50, telemetry_path=tmp_path / "none.jsonl")
    svc._storage = lambda: {"supabase": {"up": False}, "neo4j": {"up": False}}
    list(svc.chat({"prompt": "tagged question one", "conversation_id": "conv-1", "task": "code"}, "5.5.5.5"))
    st = svc.stats()
    assert st["session"]["by_conversation"]["conv-1"]["calls"] == 1
    assert st["session"]["by_task"]["code"]["tokens"] == 15 and st["session"]["tokens_today"] == 15
    assert st["recent"][0]["conversation_id"] == "conv-1" and st["recent"][0]["prompt"] == "tagged question one"
    assert [s["step"] for s in st["recent"][0]["steps"]][-1] == "final"
    list(svc.chat({"prompt": "untagged"}, "5.5.5.5"))
    assert svc.stats()["session"]["by_task"]["chat"]["calls"] == 1  # stats are not stale after a call
    for bad in ({"conversation_id": "a b"}, {"task": "x" * 65}, {"task": 3}):
        with pytest.raises(Exception) as e:
            svc.chat({"prompt": "hi", **bad}, "5.5.5.5")
        assert e.value.status == 400


def test_storage_counts_with_fakes_and_neo4j_down(monkeypatch, tmp_path):
    class Store:
        def _tx(self, tenant, sql, params, fetch):
            assert tenant == "default" and fetch == "one"
            return (3, 8192, 10)

    class Shared:
        tenant = "default"

        def _store_ready(self):
            return Store()

    r = router()
    r.shared = Shared()
    svc = Service(r, ChimeraConfig(), telemetry_path=tmp_path / "none.jsonl")
    monkeypatch.setattr(svc, "_neo4j_counts", lambda: (_ for _ in ()).throw(ConnectionError("down")))
    st = svc.storage()
    sb = st["supabase"]
    assert sb["up"] and set(sb["tables"]) >= {"prompts", "teacher_pairs", "mem_nodes", "mem_edges"}
    assert sb["tables"]["prompts"] == {"tenant_rows": 3, "bytes": 8192, "rows_estimate": 10}
    assert sb["bytes_total"] == 8192 * len(sb["tables"])
    assert st["neo4j"] == {"up": False, "error": "ConnectionError"}
    assert svc.storage() is st  # cached 60 s
