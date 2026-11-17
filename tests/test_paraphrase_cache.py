"""Paraphrase band of the shared cache (cache/band.py, pgvector_cache._choose). Offline: fake embedder and store."""
import math

from hypothesis import given, strategies as st

from _props import PBT
from test_pgvector_cache import FakeStore, settle

from chimera_core.cache.band import CHECK_PROMPT, make_checker, normalize_prompt
from chimera_core.cache.pgvector_cache import PgVectorCache
from chimera_core.config import ChimeraConfig, band_settings
from chimera_core.router import RouterConfig, SpeculativeCascadeRouter
from chimera_core.tiers import TierCfg

OLD, NEW = "What is the capital of France?", "Tell me the capital of France"


class Vecs:
    """Embedder whose cosine between OLD and any query is set by the test: query -> [s, sqrt(1-s^2)]."""

    def __init__(self, sims=None):
        self.sims = sims or {}

    def embed(self, text):
        if text in self.sims:
            s = self.sims[text]
            return [s, math.sqrt(max(0.0, 1 - s * s))]
        return [1.0, 0.0]  # OLD and anything unnamed


def cache(sims, *, band_low=0.88, checker=None, normalize=False, guard=None, old=OLD, answer="Paris"):
    c = PgVectorCache(Vecs(sims), FakeStore(), threshold=0.97, store_text=True, band_low=band_low, checker=checker,
                      normalize=normalize, guard=guard)
    c.put(old, answer)
    settle(c)
    return c


def yes(calls):
    def chk(new, old, ans):
        calls.append((new, old, ans))
        return True, {"verdict": "yes", "tokens_in": 40, "tokens_out": 1}
    return chk


def test_normalize_france_and_operators():
    assert normalize_prompt(OLD) == normalize_prompt(NEW) == normalize_prompt("capital of france") == "capital of france"
    assert normalize_prompt("Can you please tell me what's 2+2?") == "2 + 2"
    assert normalize_prompt("what is 2+2") != normalize_prompt("what is 2-2")
    assert normalize_prompt("Please!") == ""


@PBT
@given(st.text(max_size=60))
def test_normalize_is_idempotent(s):
    assert normalize_prompt(normalize_prompt(s)) == normalize_prompt(s)


@PBT
@given(st.floats(0.0, 0.8799))
def test_below_band_is_never_served(s):
    calls = []
    c = cache({NEW: s}, checker=yes(calls))
    assert c.get(NEW) is None and calls == []


@PBT
@given(st.floats(0.88, 0.9699))
def test_checker_no_is_never_served(s):
    c = cache({NEW: s}, checker=lambda n, o, a: (False, {"verdict": "no"}))
    assert c.get(NEW) is None
    assert c.lookup(NEW).check == {"verdict": "no"}


@PBT
@given(st.floats(0.88, 0.9699))
def test_guard_fail_is_never_served_and_never_checked(s):
    calls = []
    q = "What is the capital of Germany?"  # entity differs: the guard says no
    c = cache({q: s}, checker=yes(calls))
    assert c.get(q) is None and calls == []


def test_band_yes_is_served_with_check_info():
    calls = []
    c = cache({NEW: 0.955}, checker=yes(calls))
    lk = c.lookup(NEW)
    assert lk.hit[0] == "Paris" and lk.kind == "semantic" and lk.via == "band+raw" and lk.check["verdict"] == "yes"
    assert calls == [(NEW, OLD, "Paris")]


def test_checker_error_is_a_miss():
    def boom(n, o, a):
        raise TimeoutError
    assert cache({NEW: 0.95}, checker=boom).get(NEW) is None


def test_above_threshold_and_exact_skip_the_checker():
    calls = []
    c = cache({NEW: 0.98}, checker=yes(calls))
    assert c.get(NEW)[0] == "Paris" and c.get(OLD)[0] == "Paris" and calls == []


def test_band_off_by_default():
    c = PgVectorCache(Vecs({NEW: 0.95}), FakeStore(), threshold=0.97, store_text=True)
    c.put(OLD, "Paris")
    settle(c)
    assert c.get(NEW) is None


def test_normalized_prompts_match_without_a_check():
    calls = []
    c = cache({NEW: 0.90, "capital of france": 0.5}, checker=yes(calls), normalize=True)
    lk = c.lookup(NEW)  # normalized texts are equal: score 1.0, no check needed
    assert lk.hit[0] == "Paris" and lk.via == "normalized" and lk.kind == "semantic" and calls == []


def test_make_checker_parses_and_cools_down():
    now = [0.0]
    replies = iter(["Yes.", "no", RuntimeError("tunnel")])

    def complete(prompt, n):
        assert n == 3 and "Question B: new" in prompt
        r = next(replies)
        if isinstance(r, Exception):
            raise r
        return r
    chk = make_checker(complete, clock=lambda: now[0], usage=lambda: {"prompt_tokens": 30, "completion_tokens": 1})
    assert chk("new", "old", "ans")[0] is True
    assert chk("new", "old", "ans")[0] is False
    assert chk("new", "old", "ans")[1]["verdict"] == "error"
    assert chk("new", "old", "ans")[1]["verdict"] == "skipped"  # within the 60 s cooldown: no call
    assert "{" not in CHECK_PROMPT.format(old="a", answer="b", new="c")


def test_band_settings_turn_off_when_unsafe():
    t = TierCfg(name="gpu-small", device="gpu", backend="ollama", url="http://127.0.0.1:1", model="m")

    class Raw:
        last_usage = {}
        def complete(self, p, n):
            return "YES"

    fac = lambda tc: type("B", (), {"raw": Raw()})()  # noqa: E731
    cfg = ChimeraConfig.model_validate({"cache": {"band_low": 0.88, "band_check": "gpu-small", "store_text": True},
                                        "tiers": [t.model_dump()]})
    low, chk = band_settings(cfg, fac)
    assert low == 0.88 and chk("a", "b", "c")[0] is True
    cfg.cache.band_check = "missing"
    assert band_settings(cfg, fac) == (0.0, None)
    cfg.cache.band_check, cfg.cache.store_text = "gpu-small", False
    assert band_settings(cfg, fac) == (0.0, None)
    assert band_settings(ChimeraConfig(), fac) == (0.0, None)


def test_router_event_and_check_tokens():
    class NoLocal:
        def complete(self, *a):
            raise AssertionError("no model may be called on a cache hit")
    calls = []
    c = cache({NEW: 0.955}, checker=yes(calls))
    r = SpeculativeCascadeRouter(NoLocal(), shared=c, config=RouterConfig())
    out = r.generate(NEW)
    ev = next(e for e in out.telemetry.events if e["step"] == "cache_shared")
    assert out.text == "Paris" and out.telemetry.tier_used == "semantic_cache"
    assert ev["kind"] == "semantic" and ev["check"]["verdict"] == "yes" and ev["band_low"] == 0.88
    assert (out.telemetry.tokens_in, out.telemetry.tokens_out) == (40, 1)
