"""Step events from SpeculativeCascadeRouter.generate(on_event=...): order, contents, cache stack."""
import json
import time
import zlib

from chimera_core.cache.guard import consistent, make_guard
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
    """Production shape: the only cache is the shared one (Supabase stand-in). `semantic` is the offline-test path."""
    tiers = [tier("small", 0.5, device="laptop"), tier("big", 1.0, cost=0.001, device="cloud")]
    pool = TierPool(tiers, min_confidence=gate, probe=lambda t: True, backend_factory=lambda t: fakes[t.name])
    emb = Bag()
    shared = shared if shared is not None else PgVectorCache(emb, FakeStore(), threshold=0.97)
    return SpeculativeCascadeRouter(None, pool=pool, semantic=semantic, shared=shared, embedder=emb,
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
    assert steps(got) == ["embed", "cache_shared", "memory", "decide", "call", "draft", "memory", "final"]
    d = dict(got)
    assert d["cache_shared"]["hit"] is False and d["cache_shared"]["threshold"] == 0.97 and d["cache_shared"]["status"] == "ok"
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
    assert steps(got) == ["embed", "cache_shared", "memory", "decide", "call", "draft", "decide", "call", "memory", "final"]
    assert "confidence 0.900 < gate 0.95" in got[6][1]["reason"]
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
    assert res.text == "small-answer" and r2.shared.get("q none") is None


def test_shared_hit_on_a_second_machine():
    store = FakeStore()
    a = make({"small": Fake("small", conf=0.99), "big": Fake("big")}, shared=PgVectorCache(Bag(), store))
    run(a, "shared question")
    settle(a.shared)
    b = make({"small": Fake("small", fail=True), "big": Fake("big", fail=True)}, shared=PgVectorCache(Bag(), store))
    res, got = run(b, "shared question")  # a second machine: no model works, Supabase answers
    assert steps(got) == ["embed", "cache_shared", "final"]
    d = dict(got)
    assert d["cache_shared"]["hit"] is True and d["cache_shared"]["kind"] == "exact" and d["cache_shared"]["score"] == 1.0
    assert d["final"]["cache"] == "shared" and res.telemetry.tier_used == "exact_cache"


def test_slow_or_down_shared_cache_is_skipped_within_budget():
    class Slow(FakeStore):
        def lookup(self, *a):
            time.sleep(1.0)
            return super().lookup(*a)

    shared = PgVectorCache(Bag(), Slow(), budget_s=0.05)
    r = make({"small": Fake("small", conf=0.99), "big": Fake("big")}, shared=shared)
    t = time.perf_counter()
    res, got = run(r)
    assert time.perf_counter() - t < 0.8 and res.text == "small-answer"
    assert dict(got)["cache_shared"] == {"hit": False, "status": "unavailable", "threshold": 0.97, "kind": None,
                                         "score": None, "guard": None, "ms": dict(got)["cache_shared"]["ms"]}
    down = FakeStore()
    down.fail = True
    _, got = run(make({"small": Fake("small", conf=0.99), "big": Fake("big")}, shared=PgVectorCache(Bag(), down)))
    assert dict(got)["cache_shared"]["status"] == "unavailable"


def test_guard_verdict_is_in_the_event():
    store = FakeStore()
    shared = PgVectorCache(Bag(), store, threshold=0.5, store_text=True, guard=lambda q, c, s: consistent(q, c))
    shared.put("add 5 and 7", "12")
    settle(shared)
    r = make({"small": Fake("small", conf=0.99), "big": Fake("big")}, shared=shared)
    _, got = run(r, "add 5 and 9")
    c = dict(got)["cache_shared"]
    assert c["hit"] is False and c["guard"] == "rejected" and c["score"] >= 0.5


def test_offline_local_cache_still_reports_cache_local():
    sem = SemanticCache(Bag(), 0.5, guard=make_guard())
    sem.put("add 5 and 7", "12")
    r = SpeculativeCascadeRouter(None, pool=make({"small": Fake("small", conf=0.99), "big": Fake("big")}).pool,
                                 semantic=sem, embedder=Bag())
    _, got = run(r, "add 5 and 9")
    assert steps(got)[:2] == ["embed", "cache_local"] and dict(got)["cache_local"]["guard"] == "rejected"


def test_a_broken_listener_does_not_break_the_call():
    r = make({"small": Fake("small", conf=0.99), "big": Fake("big")})
    assert r.generate("hello there", on_event=lambda s, d: 1 / 0).text == "small-answer"


def test_no_listener_still_works_and_telemetry_has_events():
    r = make({"small": Fake("small", conf=0.99), "big": Fake("big")})
    assert r.generate("plain call").telemetry.events[-1]["step"] == "final"


class Mem:
    def __init__(self, ctx="Solved example: 2+2=4"):
        self.ctx, self.stored = ctx, []

    def retrieve(self, prompt):
        return self.ctx

    def store(self, prompt, answer, model, tier, verified, tests, tokens=None):
        self.stored.append((prompt, answer, tier, model, tests))
        return 1


class Spy(Fake):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.prompts = []

    def complete(self, prompt, n):
        self.prompts.append(prompt)
        return super().complete(prompt, n)


def test_memory_context_reaches_the_30b_only_and_big_answers_are_stored():
    small, big = Spy("small", conf=0.5), Spy("big")
    r = make({"small": small, "big": big})
    r.memory = mem = Mem()
    res, got = run(r, "what is three plus three")
    assert small.prompts[0].startswith("Solved example") and big.prompts[0] == "what is three plus three"
    assert mem.stored == [("what is three plus three", "big-answer", "big", "big-m", None)]
    m = [d for s, d in got if s == "memory"]
    assert m[0]["op"] == "retrieve" and m[0]["chars"] == len(mem.ctx) and m[1] == {
        "op": "store", "stored": True, "tier": "big", "tests_passed": None}


def test_30b_answers_and_failed_checks_are_not_stored():
    r = make({"small": Fake("small", conf=0.99), "big": Fake("big")})
    r.memory = mem = Mem()
    run(r, "small one")
    assert mem.stored == []  # answered by the 30B: not teacher data
    r2 = make({"small": Fake("small", conf=0.1), "big": Fake("big")})
    r2.memory = mem2 = Mem()
    r2.generate("failing tests", check=lambda a: False)
    settle(r2.shared)
    assert mem2.stored == [] and r2.shared.get("failing tests") is None


def test_ollama_without_logprobs_uses_self_check(monkeypatch):
    from chimera_core.inference.cloud_verifier import OllamaBackend
    from chimera_core.tiers import build_backend

    replies = iter([{"message": {"content": "42"}, "prompt_eval_count": 7, "eval_count": 2},
                    {"message": {"content": "ESCALATE"}, "prompt_eval_count": 50, "eval_count": 1}])
    monkeypatch.setattr(OllamaBackend, "_post", lambda self, path, body: next(replies))
    text, tin, tout, conf = build_backend(tier("gpu", 0.6)).complete("q", 16)
    assert (text, tin, tout, conf) == ("42", 7, 2, 0.0)
    monkeypatch.setattr(OllamaBackend, "_post", lambda self, path, body: {
        "message": {"content": "Paris"}, "logprobs": [{"logprob": -0.01}, {"logprob": -0.03}], "eval_count": 2})
    assert 0.97 < build_backend(tier("gpu", 0.6)).complete("q", 16)[3] < 0.99


def test_shared_cache_rows_are_scrubbed():
    store = FakeStore()
    r = make({"small": Fake("small", conf=0.99), "big": Fake("big")},
             shared=PgVectorCache(Bag(), store, store_text=True))
    run(r, "mail me at someone@example.com please")
    settle(r.shared)
    row = store.rows[0]
    assert "someone@example.com" not in row["text"] and "someone@example.com" not in row["answer"]
    assert r.shared.get("mail me at someone@example.com please") is not None  # lookups still match the raw prompt
