"""Step events from SpeculativeCascadeRouter.generate(on_event=...): order, contents, cache stack."""
import json
import time
import zlib

from chimera_core.cache.guard import make_guard
from chimera_core.cache.pgvector_cache import PgVectorCache
from chimera_core.cache.semantic_cache import SemanticCache
from chimera_core.router import RouterConfig, SpeculativeCascadeRouter
from chimera_core.tiers import TierCfg, TierPool

from test_pgvector_cache import FakeStore, settle


class Bag:
    """Hashed bag of words, 64 dims: different prompts get different vectors."""

    def embed(self, text):
        v = [0.0] * 64
        for w in text.lower().split():
            v[zlib.crc32(w.encode()) % 64] += 1.0
        return v


def tier(name, mx, cost=0.0, device="gpu"):
    return TierCfg(name=name, device=device, backend="ollama", url="http://x", model=name + "-m",
                   family="qwen", max_complexity=mx, cost_per_1k_in=cost, cost_per_1k_out=cost)


class Fake:
    def __init__(self, name, conf=None, fail=False):
        self.name, self.conf, self.fail = name, conf, fail

    def complete(self, prompt, n):
        if self.fail:
            raise TimeoutError
        return self.name + "-answer", 10, 5, self.conf


def make(fakes, shared=None, semantic=None, gate=0.95):
    tiers = [tier("small", 0.5, device="laptop"), tier("big", 1.0, cost=0.001, device="cloud")]
    pool = TierPool(tiers, min_confidence=gate, probe=lambda t: True, backend_factory=lambda t: fakes[t.name])
    emb = Bag()
    return SpeculativeCascadeRouter(
        None, pool=pool, semantic=semantic or SemanticCache(emb, 0.97), shared=shared, embedder=emb,
        config=RouterConfig(min_confidence=gate))


def steps(events):
    return [e[0] for e in events]


def run(r, prompt="what is two plus two"):
    got = []
    res = r.generate(prompt, on_event=lambda s, d: got.append((s, d)))
    return res, got


def test_miss_then_answer_event_order_and_contents():
    r = make({"small": Fake("small", conf=0.99), "big": Fake("big")})
    res, got = run(r)
    assert steps(got) == ["embed", "cache_local", "decide", "call", "draft", "final"]
    d = dict(got)
    assert d["cache_local"]["hit"] is False and d["cache_local"]["threshold"] == 0.97
    assert d["decide"]["tier"] == "small" and "complexity" in d["decide"]["reason"]
    assert (d["call"]["model"], d["call"]["tokens_in"], d["call"]["tokens_out"]) == ("small-m", 10, 5)
    assert d["draft"]["confidence"] == 0.99 and d["draft"]["gate"] == 0.95
    f = d["final"]
    assert f["tier"] == "small" and f["model"] == "small-m" and f["tokens_kept_off_big"] == 15 and f["cache"] is None
    assert f["dollars_saved"] > 0 and f["dollars"] == 0
    assert [e["step"] for e in res.telemetry.events] == steps(got)  # every event is also in telemetry
    json.dumps(res.telemetry.model_dump())


def test_low_confidence_climbs_and_decide_says_why():
    r = make({"small": Fake("small", conf=0.90), "big": Fake("big")})
    res, got = run(r)
    assert steps(got) == ["embed", "cache_local", "decide", "call", "draft", "decide", "call", "final"]
    assert "confidence 0.900 < gate 0.95" in got[5][1]["reason"]
    assert got[-1][1]["tier"] == "big" and got[-1][1]["tokens_kept_off_big"] == 0 and got[-1][1]["dollars"] > 0
    assert res.telemetry.per_tier["crusoe"].output_tokens == 5


def test_only_checked_answers_are_cached():
    shared = PgVectorCache(Bag(), FakeStore(), threshold=0.97)
    r = make({"small": Fake("small", conf=0.90), "big": Fake("big")}, shared=shared)
    run(r, "q low")
    settle(shared)
    assert shared.get("q low") is not None  # the big tier answered: cached
    r2 = make({"small": Fake("small", conf=0.90), "big": Fake("big")}, shared=PgVectorCache(Bag(), FakeStore()))
    r2.pool.tiers = r2.pool.tiers[:1]  # nothing above the unsure 3B: its answer is served, not stored
    res, _ = run(r2, "q none")
    settle(r2.shared)
    assert res.text == "small-answer" and r2.shared.get("q none") is None and r2.exact.get("q none", "") is None


def test_shared_hit_is_reported_and_warms_local():
    store = FakeStore()
    a = make({"small": Fake("small", conf=0.99), "big": Fake("big")}, shared=PgVectorCache(Bag(), store))
    run(a, "shared question")
    settle(a.shared)
    b = make({"small": Fake("small", fail=True), "big": Fake("big", fail=True)}, shared=PgVectorCache(Bag(), store))
    res, got = run(b, "shared question")  # a second machine: empty local cache, no model works
    assert steps(got) == ["embed", "cache_local", "cache_shared", "final"]
    d = dict(got)
    assert d["cache_shared"]["hit"] is True and d["cache_shared"]["score"] == 1.0 and d["cache_shared"]["threshold"] == 0.97
    assert d["final"]["cache"] == "shared" and res.telemetry.tier_used == "semantic_cache"
    _, got2 = run(b, "shared question")
    assert dict(got2)["cache_local"]["hit"] is True and dict(got2)["cache_shared"]["status"] == "skipped"


def test_slow_shared_cache_is_cut_at_the_budget_and_does_not_fail_the_call():
    class Slow(FakeStore):
        def lookup(self, *a):
            time.sleep(1.0)
            return super().lookup(*a)

    r = make({"small": Fake("small", conf=0.99), "big": Fake("big")},
             shared=PgVectorCache(Bag(), Slow(), budget_s=0.05))
    t = time.perf_counter()
    res, got = run(r)
    assert time.perf_counter() - t < 0.8 and res.text == "small-answer"
    assert dict(got)["cache_shared"]["status"] in ("timeout", "down") and dict(got)["cache_shared"]["hit"] is False


def test_guard_verdict_is_in_the_event():
    sem = SemanticCache(Bag(), 0.5, guard=make_guard())
    sem.put("add 5 and 7", "12")
    r = make({"small": Fake("small", conf=0.99), "big": Fake("big")}, semantic=sem)
    _, got = run(r, "add 5 and 9")
    c = dict(got)["cache_local"]
    assert c["hit"] is False and c["guard"] == "rejected"


def test_a_broken_listener_does_not_break_the_call():
    r = make({"small": Fake("small", conf=0.99), "big": Fake("big")})
    assert r.generate("hello there", on_event=lambda s, d: 1 / 0).text == "small-answer"


def test_no_listener_still_works_and_telemetry_has_events():
    r = make({"small": Fake("small", conf=0.99), "big": Fake("big")})
    assert r.generate("plain call").telemetry.events[-1]["step"] == "final"
