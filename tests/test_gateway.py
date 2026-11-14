import json
import math
import urllib.error

import pytest
from fastapi.testclient import TestClient

from apps.gateway.app import create_app
from apps.gateway.resilient import FALLBACKS, Resilient
from apps.gateway.store import AuditLog, KeyStore
from chimera_core.cache.exact_cache import ExactCache
from chimera_core.cache.semantic_cache import SemanticCache
from chimera_core.config import ChimeraConfig
from chimera_core.inference.local_draft import DraftResult
from chimera_core.ladder import LadderConfig, LadderRouter


class Local:
    def complete(self, prompt, max_tokens=256, system=None):
        return DraftResult(text="local answer", token_ids=[1], logprobs=[math.log(0.95)], mean_confidence=0.95)


class Text:
    def complete(self, prompt, max_tokens):
        return "text"


def make(cfg=None, probe=None, clock=None):
    cfg = cfg or ChimeraConfig()
    router = LadderRouter(Local(), Text(), Text(), LadderConfig(), exact=ExactCache())
    keys, audit = KeyStore(":memory:"), AuditLog(":memory:")
    kw = {"probe": probe} if probe else {}
    if clock:
        kw["clock"] = clock
    return TestClient(create_app(cfg, router, keys, audit, **kw)), keys, audit, router


def auth(raw):
    return {"authorization": f"Bearer {raw}"}


def chat(c, raw, prompt="hello", **extra):
    return c.post("/v1/chat/completions", headers=auth(raw), json={"messages": [{"role": "user", "content": prompt}], **extra})


def test_no_key_and_revoked_key_get_401():
    c, keys, _, _ = make()
    assert chat(c, "nope").status_code == 401
    assert c.post("/v1/chat/completions", json={}).status_code == 401
    _, raw = keys.create("acme")
    assert chat(c, raw).status_code == 200
    keys.revoke(tenant="acme")
    r = chat(c, raw)
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_api_key"


def test_only_hashes_are_stored():
    keys = KeyStore(":memory:")
    _, raw = keys.create("acme")
    dump = json.dumps(list(keys._db.iterdump()))
    assert raw not in dump and keys.lookup(raw).tenant == "acme"


def test_tenant_cache_isolation():
    c, keys, _, _ = make()
    _, a = keys.create("acme")
    _, b = keys.create("globex")
    assert chat(c, a).headers["x-chimera-tier"] == "local"
    assert chat(c, a).headers["x-chimera-tier"] == "exact_cache"
    assert chat(c, b).headers["x-chimera-tier"] == "local"  # globex does not see acme's answer


def test_openai_shape_and_headers():
    c, keys, audit, _ = make()
    _, raw = keys.create("acme")
    r = chat(c, raw)
    body = r.json()
    assert body["object"] == "chat.completion" and body["id"].startswith("chatcmpl-")
    assert body["choices"][0]["message"] == {"role": "assistant", "content": "local answer"}
    assert body["choices"][0]["finish_reason"] == "stop"
    assert set(body["usage"]) == {"prompt_tokens", "completion_tokens", "total_tokens"}
    assert body["chimera"]["tier_used"] == "local" and body["chimera"]["request_id"] == r.headers["x-request-id"]
    assert r.headers["x-chimera-tier"] == "local"
    assert int(r.headers["x-chimera-tokens-saved"]) == body["chimera"]["tokens_saved"]
    assert float(r.headers["x-chimera-latency-ms"]) >= 0
    assert audit.rows("acme")[0][:2] == ("acme", "local")
    assert [m["id"] for m in c.get("/v1/models", headers=auth(raw)).json()["data"]][0] == "chimera-auto"


def test_bad_requests():
    c, keys, _, _ = make(ChimeraConfig(gateway={"max_body_bytes": 200}))
    _, raw = keys.create("acme")
    assert c.post("/v1/chat/completions", headers=auth(raw), content=b"{not json").status_code == 400
    assert chat(c, raw, model="gpt-9").status_code == 404
    assert chat(c, raw, prompt="x" * 500).status_code == 413


def test_rate_limit_returns_429_and_refills():
    now = [0.0]
    c, keys, _, _ = make(ChimeraConfig(gateway={"burst": 2, "rate_per_min": 60}), clock=lambda: now[0])
    _, raw = keys.create("acme")
    assert [chat(c, raw).status_code for _ in range(3)] == [200, 200, 429]
    assert "retry-after" in chat(c, raw).headers
    now[0] += 2
    assert chat(c, raw).status_code == 200


def test_streaming_chunks():
    c, keys, _, _ = make()
    _, raw = keys.create("acme")
    r = chat(c, raw, stream=True)
    assert r.headers["content-type"].startswith("text/event-stream") and r.headers["x-chimera-tier"] == "local"
    lines = [ln[6:] for ln in r.text.splitlines() if ln.startswith("data: ")]
    assert lines[-1] == "[DONE]"
    chunks = [json.loads(x) for x in lines[:-1]]
    assert all(ch["object"] == "chat.completion.chunk" for ch in chunks)
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert "".join(ch["choices"][0]["delta"].get("content", "") for ch in chunks) == "local answer"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop" and "chimera" in chunks[-1]


def test_metrics_by_tier_and_tenant():
    c, keys, _, _ = make()
    _, a = keys.create("acme")
    chat(c, a)
    chat(c, a)
    chat(c, "bad")
    m = c.get("/metrics").text
    assert 'chimera_calls_total{tenant="acme",tier="local"} 1' in m
    assert 'chimera_calls_total{tenant="acme",tier="exact_cache"} 1' in m
    assert 'chimera_tokens_saved_total{tenant="acme",tier="exact_cache"}' in m
    assert 'chimera_dollars_saved_total{tenant="acme"' in m
    assert 'chimera_latency_ms_count{tenant="acme",tier="local"} 1' in m
    assert 'chimera_errors_total{tenant="-",code="invalid_api_key"} 1' in m


def test_health_ready_and_actions():
    c, keys, _, _ = make(probe=lambda check: check[0] == "local")
    assert c.get("/healthz").json() == {"status": "ok"}
    assert c.get("/readyz").json()["tiers"]["local"] is True
    c2, _, _, _ = make(probe=lambda check: False)
    assert c2.get("/readyz").status_code == 503
    _, raw = keys.create("acme")
    assert c.post("/v1/actions/score", headers=auth(raw), json={"action": "pay"}).status_code == 404  # off by default
    c3, keys3, _, _ = make(ChimeraConfig(gateway={"actions": True}))
    _, raw3 = keys3.create("acme")
    v = c3.post("/v1/actions/score", headers=auth(raw3), json={"action": "pay the invoice"}).json()
    assert v["needs_approval"] is True and v["score"] >= 70
    assert c3.post("/v1/actions/score", headers=auth(raw3), json={"nope": 1}).status_code == 400


def test_prompt_not_logged_by_default(caplog):
    import logging
    c, keys, _, _ = make()
    _, raw = keys.create("acme")
    with caplog.at_level(logging.INFO, logger="chimera.gateway"):
        chat(c, raw, prompt="top secret words")
    rec = [r for r in caplog.records if r.getMessage() == "request"][-1]
    assert "prompt" not in rec.fields and rec.fields["tenant"] == "acme"
    c2, keys2, _, _ = make(ChimeraConfig(gateway={"log_prompts": True}))
    _, raw2 = keys2.create("acme")
    with caplog.at_level(logging.INFO, logger="chimera.gateway"):
        chat(c2, raw2, prompt="top secret words")
    assert [r for r in caplog.records if r.getMessage() == "request"][-1].fields["prompt"] == "top secret words"


def test_retry_then_fallback_one_tier_down():
    calls = []

    class Flaky:
        def __init__(self, fail):
            self.fail = fail

        def complete(self, prompt, max_tokens):
            calls.append(1)
            if self.fail:
                raise urllib.error.HTTPError("u", 429, "rate", {}, None)
            return "ok"

    sleeps = []
    r = Resilient(Flaky(True), lambda p, n: "lower tier", "top", "gpu", 0.5, sleep=sleeps.append)
    log = []
    FALLBACKS.set(log)
    assert r.complete("p", 10) == "lower tier"
    assert len(calls) == 2 and sleeps == [0.5] and log == [("top", "gpu")]
    with pytest.raises(urllib.error.HTTPError):  # 4xx other than 429 is not retried or hidden
        Resilient(type("B", (), {"complete": lambda s, p, n: (_ for _ in ()).throw(
            urllib.error.HTTPError("u", 400, "bad", {}, None))})(), None, "top", "gpu").complete("p", 1)


def test_purge_removes_only_that_tenant(tmp_path):
    class Emb:
        def embed(self, t):
            return [1.0, 0.0]

    path = str(tmp_path / "c.db")
    ex, sem = ExactCache(path=path), SemanticCache(Emb(), 0.9, path)
    for ns in ("acme", "globex"):
        ex.put("q", "a", ns)
        sem.put("q", "a", ns)
    assert ex.purge("acme") == 1 and sem.purge("acme") == 1
    assert ex.get("q", "acme") is None and ExactCache(path=path).get("q", "acme") is None
    assert ex.get("q", "globex") == "a" and sem.get("q", "globex") is not None


def test_exact_cache_migrates_old_table(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE exact (key TEXT PRIMARY KEY, response TEXT)")
    db.commit()
    c = ExactCache(path=path)
    c.put("q", "a", "acme")
    assert ExactCache(path=path).get("q", "acme") == "a"
