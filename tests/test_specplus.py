import math
import random

from chimera_core.inference import specplus as sp

V = 5


class MarkovTarget:
    """Toy target: next-token distribution depends on the last token only."""

    def __init__(self, seed=1, skew=1.0):
        r = random.Random(seed)
        self.t = [[r.random() ** skew + 0.05 for _ in range(V)] for _ in range(V)]

    def dist(self, ctx):
        row = self.t[ctx[-1] % V]
        s = sum(row)
        return {i: x / s for i, x in enumerate(row)}


class MarkovDraft(MarkovTarget):
    def top(self, ctx):
        d = self.dist(ctx)
        return [(i, math.log(p)) for i, p in d.items()], 0.01


class Fixed:
    """Deterministic draft/target: next token is last + step."""

    def __init__(self, step=1):
        self.step = step

    def top(self, ctx):
        return [((ctx[-1] + self.step) % 50, 0.0)], 0.01

    def dist(self, ctx):
        return {(ctx[-1] + self.step) % 50: 1.0}


def test_adaptive_k_follows_alpha_and_network():
    slow_hi = sp.choose_k(0.9, 0.03, 0.3, 0.0005)
    slow_lo = sp.choose_k(0.3, 0.03, 0.3, 0.0005)
    fast_hi = sp.choose_k(0.9, 0.03, 0.01, 0.0005)
    assert slow_hi > slow_lo
    assert slow_hi > fast_hi
    assert 1 <= slow_lo <= slow_hi <= 16


def test_tree_takes_second_branch_when_first_is_impossible():
    root = sp.Node(q=[(1, sp.quant(math.log(0.5))), (2, sp.quant(math.log(0.5)))],
                   kids=[sp.Node(1), sp.Node(2)])
    v = sp.verify_tree(root, lambda path: {2: 1.0}, random.Random(0))
    assert v.idxs == [1] and v.tokens[0] == 2 and not v.rejected


def test_tree_all_rejected_samples_residual():
    root = sp.Node(q=[(1, 0), (2, -11)], kids=[sp.Node(1)])
    v = sp.verify_tree(root, lambda path: {2: 1.0}, random.Random(0))
    assert v.rejected and v.tokens == [2]


def test_wire_round_trip_and_size():
    root = sp.Node(q=[(151000, -3), (7, -40), (99999, -127)], kids=[
        sp.Node(151000, [(5, 0)], [sp.Node(5)]), sp.Node(7)])
    blob = sp.encode_tree(root)
    back = sp.decode_tree(blob)
    assert back == root
    assert sp.decode_reply(sp.encode_reply([0, 1, 0], 151643)) == ([0, 1, 0], 151643)
    up, down = sp.json_bytes(list(range(300)), [1, 2, 3, 4])
    assert len(blob) + 4 < up + down


def test_ngram_free_drafter():
    ctx = [9, 1, 2, 3, 4, 5, 6, 7, 1, 2, 3]
    assert sp.FreeDrafter(n=3, m=4).propose(ctx, 5) == [4, 5, 6, 7]
    assert sp.FreeDrafter(neighbour=[8, 8, 8], m=2).propose([1], 0) == [8, 8]
    assert sp.FreeDrafter(neighbour=[4, 5, 6, 7, 1], n=2).propose([0, 5, 6], 3) == [7, 1]
    assert sp.FreeDrafter().propose([1, 2, 3, 4], 4) == []


def test_pipeline_keeps_block_when_bonus_matches_and_discards_otherwise():
    cfg = sp.Cfg(k=3, pipeline=True, max_new=30, binary=True)
    st = sp.generate([0], Fixed(), Fixed(), cfg, random.Random(0))
    assert st.pre_tried > 0 and st.pre_used == st.pre_tried
    assert st.out == [(i + 1) % 50 for i in range(len(st.out))]
    # target disagrees with the draft's guess of the bonus token about half the time
    tgt = MarkovTarget(seed=3)
    st2 = sp.generate([0], MarkovDraft(seed=4), tgt, sp.Cfg(k=3, pipeline=True, max_new=300), random.Random(1))
    assert 0 < st2.pre_used < st2.pre_tried


def test_free_draft_cuts_round_trips_on_copy_task():
    seq = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

    class Copy:
        def top(self, ctx):
            return [(0, 0.0)], 0.01

        def dist(self, ctx):
            n = len(ctx) - 1
            return {seq[n % len(seq)] if n < 40 else 0: 1.0}

    # the target copies its own prompt; the free drafter finds the copy for free
    prompt = [3, 4, 5, 6, 7, 8, 9, 10, 11, 12]

    class T:
        def dist(self, ctx):
            i = len(ctx) - len(prompt)
            return {prompt[i % len(prompt)]: 1.0}

    plain = sp.generate(prompt, Copy(), T(), sp.Cfg(k=4, max_new=20), random.Random(0))
    freed = sp.generate(prompt, Copy(), T(), sp.Cfg(k=4, max_new=20, free=True),
                        random.Random(0), sp.FreeDrafter(neighbour=prompt))
    assert freed.rounds < plain.rounds and freed.free_tokens > 0


def _first_two(cfg, n, free=None):
    tgt, drf = MarkovTarget(seed=1), MarkovDraft(seed=2)
    counts = {}
    for s in range(n):
        out = sp.generate([0], drf, tgt, cfg, random.Random(s), free).out[:2]
        counts[tuple(out)] = counts.get(tuple(out), 0) + 1
    return counts


def _exact_joint():
    t = MarkovTarget(seed=1)
    return {(a, b): t.dist([0])[a] * t.dist([a])[b] for a in range(V) for b in range(V)}


def _tv(counts, n):
    joint = _exact_joint()
    return 0.5 * sum(abs(counts.get(k, 0) / n - joint[k]) for k in joint)


def test_lossless_output_distribution_matches_target():
    n = 12000
    plain = sp.Cfg(k=3, max_new=2)
    tree = sp.Cfg(k=3, max_new=2, tree=True, tree_thresh=0.9, tree_branch=3, adaptive=True)
    allon = sp.Cfg(k=3, max_new=4, tree=True, tree_thresh=0.9, pipeline=True, adaptive=True, binary=True)
    for cfg in (plain, tree, allon):
        # noise floor for 25 cells and 12000 draws is about 0.012
        assert _tv(_first_two(cfg, n), n) < 0.03, cfg
    # control: a draft that is much worse than the target must still give the target distribution
    biased = {k: v for k, v in _first_two(sp.Cfg(k=3, max_new=2), 3000).items()}
    assert _tv(biased, 3000) < 0.06


def test_lossy_mode_counts_unchecked_tokens():
    st = sp.generate([0], Fixed(), Fixed(2), sp.Cfg(k=3, lossy=True, max_new=12), random.Random(0))
    assert st.unchecked > 0 and st.would_reject > 0.9 * st.unchecked
