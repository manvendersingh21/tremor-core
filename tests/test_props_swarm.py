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
