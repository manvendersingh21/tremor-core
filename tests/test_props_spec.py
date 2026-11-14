"""Property tests for the speculative accept rule (inference/specplus.py verify_tree). Pure math, no models.

Properties P13-P15. The accept ratio min(1, p/q) and the residual are inline in verify_tree, so they are checked
through what they must produce: tokens in the target's support, and the target's distribution (chi-square)."""
import math
import random

from hypothesis import given, strategies as st

from _props import PBT, PBT_SLOW

from chimera_core.inference.specplus import Node, qhat, quant, sample, verify_tree

V = 4
CHI2_CRIT_DF3 = 28.0  # p about 4e-6 for 3 degrees of freedom; the rng is seeded, so a run is reproducible

weights = st.lists(st.floats(0.0, 1.0), min_size=V, max_size=V).filter(lambda w: sum(w) > 0.05)


def dist(w, floor=0.0):
    w = [x + floor for x in w]
    s = sum(w)
    return {i: x / s for i, x in enumerate(w)}


def root_with_kids(q_probs, n_kids, rng):
    """A one-step tree: the draft's next-token distribution (int8 codes, as on the wire) and kids drawn from it
    without replacement, in order. This is how the drafter builds the tree."""
    q = [(i, quant(math.log(max(p, 1e-9)))) for i, p in q_probs.items()]
    pool = dict(qhat(q))
    kids = []
    for _ in range(min(n_kids, len(pool))):
        c = sample(pool, rng)
        kids.append(Node(tok=c))
        del pool[c]
        z = sum(pool.values())
        pool = {t: x / z for t, x in pool.items()} if z > 0 else pool
    return Node(q=q, kids=kids)


# P13 (R3.2): the accept ratio min(1, p_t/p_d) is in [0,1] and the first emitted token is in the target's support
@PBT
@given(weights, weights, st.integers(1, 3), st.integers(0, 2**31))
def test_emitted_token_is_always_possible_under_the_target(wp, wq, kids, seed):
    p, q = dist(wp), dist(wq, 0.01)
    rng = random.Random(seed)
    root = root_with_kids(q, kids, rng)
    v = verify_tree(root, lambda path: p, rng)
    assert v.tokens and all(0 <= t < V for t in v.tokens)
    assert p[v.tokens[0]] > 0                 # never a token the target gives probability 0
    assert len(v.idxs) in (0, 1)              # one step: either a kid was taken or the target resampled


# P14 (R3.3): the residual after a rejection is a distribution: no negative mass, sums to 1.
# Checked on the same arithmetic verify_tree uses.
@PBT
@given(weights, weights)
def test_residual_is_a_distribution(wp, wq):
    p, q = dist(wp), dist(wq, 0.01)
    res = {t: max(p.get(t, 0.0) - q.get(t, 0.0), 0.0) for t in p}
    s = sum(res.values())
    assert all(x >= 0 for x in res.values())
    assert all(0 <= min(1.0, p[t] / q[t]) <= 1 for t in p)
    if s > 0:
        assert math.isclose(sum(x / s for x in res.values()), 1.0)
    else:
        assert math.isclose(sum(min(p[t], q[t]) for t in p), 1.0)   # p == q: every draft token is accepted


# P15 (R3.2, R3.3): lossless. Accepted-or-resampled tokens follow the target distribution (chi-square, V=4)
@PBT_SLOW
@given(weights, weights, st.integers(1, 3), st.integers(0, 2**31))
def test_output_follows_the_target_distribution(wp, wq, kids, seed):
    p, q = dist(wp, 0.05), dist(wq, 0.05)    # floor keeps every expected count >= 5
    rng, n = random.Random(seed), 1500
    counts = [0] * V
    for _ in range(n):
        root = root_with_kids(q, kids, rng)
        counts[verify_tree(root, lambda path: p, rng).tokens[0]] += 1
    chi2 = sum((counts[i] - n * p[i]) ** 2 / (n * p[i]) for i in range(V))
    assert chi2 < CHI2_CRIT_DF3, (counts, p)
