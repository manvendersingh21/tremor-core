"""Swarm properties (demo mode: stub models, in-memory cache, offline).

1. The swarm never serves a candidate the check rejects.
2. It never serves a costlier candidate when a cheaper one passed: the served tier is the first (cheapest) tier whose
   candidate passes, and no tier above it was called.
"""
from hypothesis import given, strategies as st

from skeleton.core import Assistant
from skeleton.core.swarm import SWARM_LADDER, Swarm

from tests._props import PBT

TEXTS = st.sampled_from(["a", "b", "c", "d"])
FALLBACK = "FALLBACK"


@PBT
@given(st.lists(TEXTS, min_size=3, max_size=3), st.sets(TEXTS))
def test_cheapest_passing_candidate_is_served_and_a_rejected_one_never(candidates, passing):
    models = {t: (lambda p, c=c: c) for t, c in zip(SWARM_LADDER, candidates)}
    bot = Swarm(Assistant({"mode": "demo", "namespace": "swarm-prop", "ladder": SWARM_LADDER}, demo_models=models),
                check=lambda q, a: a in passing, fallback=FALLBACK)
    passed = [i for i, c in enumerate(candidates) if c in passing]
    for _ in range(2):  # the second ask is a cache hit when the first answer passed
        a = bot.ask("some question")
        assert a["answer"] in passing or a["answer"] == FALLBACK  # property 1
        if passed:  # property 2
            assert a["answer"] == candidates[passed[0]] and a["verified"] is True
            assert a["tier"] in ("exact_cache", "semantic_cache") or a["tier"] == SWARM_LADDER[passed[0]]
            assert not set(a["tried"]) - set(SWARM_LADDER[: passed[0] + 1])
        else:
            assert a["answer"] == FALLBACK and a["verified"] is False and a["tried"] == SWARM_LADDER


# ---- 3. joined-entry answers are never backed -------------------------------------------------------------------
import re  # noqa: E402

from skeleton.core.kblookup import (NOT_THINGS, QWORDS, KBLookup, Semantic, backed, joins_entries,  # noqa: E402
                                    swarm_check, swarm_covered)
from skeleton.core.demo import STOP  # noqa: E402

FILLER = ["Open the Orders page and click the button.", "Support answers email within a day.",
          "Gift cards never expire.", "Standard parcels leave the warehouse quickly."]
FILLER_WORDS = {w for t in FILLER for w in re.findall(r"[a-z]+", t.lower())}
THING = st.text("bcdfghjklmnprtvwz", min_size=5, max_size=9).filter(
    lambda w: w not in FILLER_WORDS | STOP | QWORDS | NOT_THINGS)


class HashEmbedder:
    def embed(self, text):
        v = [0.0] * 97
        for w in re.findall(r"[a-z]+", text.lower()):
            v[sum(map(ord, w)) % 97] += 1.0
        return v


class YesJudge:
    def agrees(self, q, entries, a):
        return True

    def covers(self, q, entries):
        return True


@PBT
@given(THING, THING, st.integers(1, 9), st.integers(10, 99))
def test_an_answer_joining_two_separate_entries_is_never_backed(a, b, n, m):
    """Entry 1 names thing `a`, entry 2 names thing `b`, no entry names both. An answer that joins them is refused by
    every check path, even with a judge that always says YES."""
    if a == b:
        return
    e1, e2 = f"The {a} plan costs {n} dollars.", f"We offer {b} in {m} days."
    lines = [e1, e2] + FILLER
    q, ans = f"Is the {a} plan offered with {b}?", f"Yes, the {a} plan comes with {b}: {n} dollars, {m} days."
    sem = Semantic(HashEmbedder(), lines, lines)
    assert joins_entries(lines, q, ans)
    assert not backed(lines, q, ans)
    assert not sem.backed(q, ans) and not sem.backed_loose(q, ans)
    assert not swarm_check(lines, sem, YesJudge(), q, ans)
    assert not swarm_covered(sem, YesJudge(), q)
    assert KBLookup([(e1, e1), (e2, e2)]).match(q) is None
    # control: when one entry states both things, the join rule does not refuse
    both = [f"The {a} plan comes with {b}."] + lines
    assert not joins_entries(both, q, ans)
