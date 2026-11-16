"""Property tests for the ladder and the tier-pool router. Fake backends, fake Supabase, no network.

Properties P8-P12 in .kiro/specs/chimera-speculative-os/design.md. See docs/handoff/property-tests.md."""
import math

import pytest
from hypothesis import given, strategies as st

from _props import PBT
from test_events import Fake, Bag, tier
from test_pgvector_cache import FakeStore, settle

from chimera_core.cache.pgvector_cache import PgVectorCache
from chimera_core.inference.local_draft import DraftResult
from chimera_core.inference.telemetry import Telemetry
from chimera_core.ladder import LadderConfig, LadderRouter
from chimera_core.router import RouterConfig, SpeculativeCascadeRouter
from chimera_core.tiers import AllTiersFailed, TierPool

CACHE_TIERS = ("exact_cache", "semantic_cache")
FIELDS = ("tier_used", "tokens_saved", "acceptance_rate_alpha", "latency_ms", "dollars_saved")
HEAVY = "Refactor and redesign the architecture, then implement it.\n```\nx\n```\n```\ny\n```\n"


def prompts():
    return st.builds(lambda w, heavy: (HEAVY if heavy else "") + " ".join(w) + "#",
                     st.lists(st.text(alphabet="abcdefgh", min_size=1, max_size=5), min_size=1, max_size=5), st.booleans())


# ---------------------------------------------------------------- ladder
class Local:
    def __init__(self, conf, log):
        self.conf, self.log = conf, log

    def complete(self, prompt, max_tokens=256, system=None):
        self.log.append("local")
        return DraftResult(text="local", token_ids=[1], logprobs=[math.log(max(self.conf, 1e-6))], mean_confidence=self.conf)


class Text:
    def __init__(self, name, log, mode="ok"):
        self.name, self.log, self.mode = name, log, mode

    def complete(self, prompt, max_tokens):
        self.log.append(self.name)
        if self.mode == "oserror":
            raise OSError("down")
        if prompt.startswith("Task:\n") and "Proposed answer" in prompt:
            return "ESCALATE" if self.mode == "escalate" else "OK"
        return self.name


RANK = {"local": 0, "mid": 1, "top": 2}
TIER_OF = {"local": "local", "mid": "gpu", "top": "top"}
CHECKS = {"none": None, "true": lambda t: True, "false": lambda t: False, "top_only": lambda t: t == "top",
          "not_local": lambda t: t != "local"}


def ladder(conf, mid_mode, use_brief=False):
    log = []
    r = LadderRouter(Local(conf, log), Text("mid", log, mid_mode), Text("top", log), LadderConfig(use_brief=use_brief))
    return r, log


ladder_args = (st.floats(0, 1), st.sampled_from(["ok", "escalate", "oserror"]), st.sampled_from(sorted(CHECKS)), prompts(),
               st.booleans())


# P8 (R6.1, R6.2): every call emits one telemetry event with the documented fields, and none is negative
@PBT
@given(*ladder_args)
def test_ladder_emits_complete_telemetry_and_no_negative_numbers(conf, mid_mode, chk, prompt, brief):
    r, log = ladder(conf, mid_mode, brief)
    events = []
    out = r.generate(prompt, check=CHECKS[chk], on_event=lambda s, d: events.append((s, d)))
    assert len(r.tracker.events) == 1 and r.tracker.events[0] is out.telemetry
    dump = out.telemetry.model_dump()
    assert all(f in dump for f in FIELDS)
    t = out.telemetry
    assert t.tokens_saved >= 0 and t.dollars_saved >= 0 and t.latency_ms >= 0
    assert t.acceptance_rate_alpha is None or 0 <= t.acceptance_rate_alpha <= 1
    final = dict(events)["final"]
    assert final["tokens_kept_off_big"] >= 0 and final["dollars_saved"] >= 0 and final["ms"] >= 0
    # the same call serves a repeat from cache with zero big-model work
    again = r.generate(prompt)
    if again.telemetry.tier_used in CACHE_TIERS:
        assert again.telemetry.tokens_saved >= 0 and again.telemetry.dollars_saved >= 0


# P9 (R6.3): escalation never goes down a tier, the top is called at most once, and the answering tier is the highest visited
@PBT
@given(*ladder_args)
def test_ladder_escalation_is_monotonic_and_stops_at_top(conf, mid_mode, chk, prompt, brief):
    r, log = ladder(conf, mid_mode, brief)
    out = r.generate(prompt, check=CHECKS[chk])
    ranks = [RANK[x] for x in log]
    assert ranks == sorted(ranks)
    assert log.count("top") <= 1
    if "top" in log:
        assert log[-1] == "top"
    assert out.telemetry.tier_used == TIER_OF[log[-1]]


# P10 (R6.4): an answer the check rejects is never what the cache serves next time (answers from the 3B and the 30B)
@PBT
@given(st.floats(0, 1), st.sampled_from(["ok", "escalate"]), prompts())
def test_ladder_cache_only_holds_answers_that_passed_the_check(conf, mid_mode, prompt):
    r, _ = ladder(conf, mid_mode)
    check = CHECKS["top_only"]
    first = r.generate(prompt, check=check)
    again = r.generate(prompt)
    if again.telemetry.tier_used in CACHE_TIERS:
        assert check(again.text)
    assert first.text == "top" or first.telemetry.tier_used in CACHE_TIERS


@PBT
@given(st.floats(0, 1), st.sampled_from(["ok", "escalate", "oserror"]), prompts())
def test_ladder_does_not_cache_an_answer_that_failed_the_check(conf, mid_mode, prompt):
    r, _ = ladder(conf, mid_mode)
    r.generate(prompt, check=CHECKS["false"])
    assert r.generate(prompt).telemetry.tier_used not in CACHE_TIERS


# ---------------------------------------------------------------- tier pool (production path)
class Back:
    def __init__(self, conf, fail, tin, tout, text):
        self.conf, self.fail, self.tin, self.tout, self.text = conf, fail, tin, tout, text

    def complete(self, prompt, n):
        if self.fail:
            raise TimeoutError
        return self.text, self.tin, self.tout, self.conf


back = st.builds(Back, st.one_of(st.none(), st.floats(0, 1)), st.booleans(), st.integers(0, 5000), st.integers(0, 5000),
                 st.sampled_from(["ans", "42", "x y z"]))


class Mem:
    def __init__(self):
        self.stores = []

    def retrieve(self, prompt):
        return ""

    def store(self, prompt, answer, model, tier, verified, tests, tokens=None):
        self.stores.append((answer, verified, tests))
        return len(self.stores)


def pooled(backs, gate):
    tiers = [tier("t0", 0.5, 0.0, "laptop"), tier("t1", 1.0, 0.0005, "gpu"), tier("t2", 1.0, 0.002, "cloud")]
    for t, mx in zip(tiers, (0.5, 1.0, 1.0)):
        assert t.max_complexity == mx
    fakes = {f"t{i}": b for i, b in enumerate(backs)}
    pool = TierPool(tiers, min_confidence=gate, probe=lambda t: True, backend_factory=lambda t: fakes[t.name])
    shared = PgVectorCache(Bag(), FakeStore(), threshold=0.97)
    mem = Mem()
    return SpeculativeCascadeRouter(None, pool=pool, shared=shared, embedder=Bag(), memory=mem,
                                    config=RouterConfig(min_confidence=gate)), mem


pool_args = (st.lists(back, min_size=3, max_size=3), st.floats(0.5, 1), prompts())


# P8 on the pool path: telemetry fields, tokens and dollars never negative
@PBT
@given(*pool_args)
def test_pool_router_telemetry_complete_and_non_negative(backs, gate, prompt):
    r, _ = pooled(backs, gate)
    try:
        out = r.generate(prompt)
    except AllTiersFailed:
        return
    settle(r.shared)
    t: Telemetry = out.telemetry
    assert all(f in t.model_dump() for f in FIELDS)
    assert t.tokens_saved >= 0 and t.dollars_saved >= 0 and t.latency_ms >= 0
    assert t.dollars_spent >= 0 and t.cloud_tokens >= 0 and t.local_tokens >= 0
    assert t.acceptance_rate_alpha is None or 0 <= t.acceptance_rate_alpha <= 1
    assert len(r.tracker.events) == 1


# P9 on the pool path: tiers are tried cheapest first, each at most once, never back down
@PBT
@given(*pool_args)
def test_pool_escalation_never_goes_down_and_stops_at_top(backs, gate, prompt):
    r, _ = pooled(backs, gate)
    order = [t.name for t in r.pool.tiers]
    try:
        res = r.pool.generate(prompt)
    except AllTiersFailed:
        return
    idx = [order.index(n) for n in res.attempts]
    assert idx == sorted(set(idx))                 # strictly increasing: no repeat, no step down
    assert res.tier in res.attempts
    if not res.low_confidence:
        assert res.attempts[-1] == res.tier        # the last tier tried is the one that answered
    assert len(res.attempts) <= len(order)         # stops at the top


@PBT
@given(st.lists(back.filter(lambda b: b.fail), min_size=3, max_size=3), st.floats(0.5, 1), prompts())
def test_pool_with_every_tier_down_raises_instead_of_looping(backs, gate, prompt):
    r, _ = pooled(backs, gate)
    with pytest.raises(AllTiersFailed):
        r.pool.generate(prompt)


# P10 on the pool path: a call whose check fails is never cached and never stored as memory
@PBT
@given(*pool_args, st.sampled_from([True, False, None]))
def test_pool_failed_check_is_never_cached_or_stored(backs, gate, prompt, verdict):
    r, mem = pooled(backs, gate)
    check = None if verdict is None else (lambda t: verdict)
    try:
        out = r.generate(prompt, check=check)
    except AllTiersFailed:
        return
    settle(r.shared)
    if verdict is False:
        assert mem.stores == []
        assert r.generate(prompt).telemetry.tier_used not in CACHE_TIERS
    for answer, verified, tests in mem.stores:     # memory only ever gets answers whose check passed
        assert verified is True and tests is not False and (verdict is not True or tests is True)
