"""Spec+: speculative decoding designed for a draft and a verifier that sit on different networks.

Pieces (each is a switch in `Cfg`): adaptive K, token-tree drafting, pipelined pre-drafting, free
drafts (prompt lookup / cache neighbour), compact binary wire, optional lossy mode.

Lossless by default. The draft proposes tokens from its own distribution q-hat (top-N, logprobs
rounded to int8 so both sides rebuild the identical q-hat). The verifier walks the tree: it accepts
child c with probability min(1, r(c)/q(c)); on a reject it replaces r by norm(max(r - q, 0)) and
drops c from q (sampling without replacement); if every child is rejected it samples from r. A
node without children gets one bonus sample from the target. `tests/test_specplus.py` checks that
the output distribution equals the target on a toy model.

Everything here is pure Python and offline. The draft model and the target are passed in:
  draft.top(ctx)   -> ([(token_id, logprob), ...] top-N, seconds spent)
  target.dist(ctx) -> {token_id: probability}
Time is a virtual clock: real measured draft seconds + a modelled round trip (rtt + server time).
"""
from __future__ import annotations

import json
import math
import random
import struct
from dataclasses import dataclass, field

EOS = {151645, 151643}  # <|im_end|>, <|endoftext|>
SCALE = 16  # int8 logprob step = 1/16 nat


# ---------- draft distribution as it travels (int8 logprobs) ----------
def quant(lp: float) -> int:
    return max(-127, min(0, round(lp * SCALE)))


def qhat(q: list[tuple[int, int]]) -> dict[int, float]:
    w = {i: math.exp(c / SCALE) for i, c in q}
    s = sum(w.values())
    return {i: x / s for i, x in w.items()}


@dataclass
class Node:
    tok: int = -1  # token that leads to this node (-1 at the root)
    q: list[tuple[int, int]] = field(default_factory=list)  # (id, int8 code) for the NEXT token; empty = leaf
    kids: list["Node"] = field(default_factory=list)  # drawn from q without replacement, in order


def sample(dist: dict[int, float], rng: random.Random) -> int:
    u, acc, last = rng.random() * sum(dist.values()), 0.0, -1
    for t, p in dist.items():
        acc += p
        last = t
        if u < acc:
            return t
    return last


# ---------- lossless tree verification ----------
@dataclass
class Verdict:
    tokens: list[int]  # accepted draft tokens + one target token (correction or bonus)
    idxs: list[int]  # which child was taken at each step
    rejected: bool  # True if the walk stopped because every child was rejected
    unchecked: int = 0  # lossy mode: tokens accepted without a test
    would_reject: float = 0.0  # lossy mode: summed probability the test would have rejected them


def verify_tree(root: Node, p_of, rng: random.Random, lossy_p: float | None = None) -> Verdict:
    """p_of(path_tokens) -> {id: prob}, the target distribution after the accepted path so far."""
    node, path, idxs, unchecked, wr = root, [], [], 0, 0.0
    while True:
        p = p_of(path)
        if not node.kids:
            return Verdict(path + [sample(p, rng)], idxs, False, unchecked, wr)
        q, r, taken = qhat(node.q), dict(p), None
        for ci, kid in enumerate(node.kids):
            c, qc = kid.tok, q[kid.tok]
            if lossy_p is not None and qc > lossy_p:
                unchecked += 1
                wr += 1 - min(1.0, r.get(c, 0.0) / qc)
                taken = ci
                break
            if rng.random() < min(1.0, r.get(c, 0.0) / qc):
                taken = ci
                break
            res = {t: max(r.get(t, 0.0) - q.get(t, 0.0), 0.0) for t in set(r) | set(q)}
            s = sum(res.values())
            r = {t: x / s for t, x in res.items() if x > 0} if s > 0 else dict(p)
            del q[c]
            z = sum(q.values())
            q = {t: x / z for t, x in q.items()} if z > 0 else q
        if taken is None:
            return Verdict(path + [sample(r, rng)], idxs, True, unchecked, wr)
        idxs.append(taken)
        path.append(node.kids[taken].tok)
        node = node.kids[taken]


# ---------- adaptive K ----------
def choose_k(alpha: float, t_draft: float, v0: float, v_node: float, kmax: int = 16) -> int:
    """Pick K that maximises expected tokens per second.

    E[tokens per round] = (1 - a^(K+1)) / (1 - a) for per-token acceptance a.
    Round time = K * t_draft + (v0 = rtt + server base) + K * v_node.
    """
    a = min(max(alpha, 0.0), 0.999)

    def rate(k: int) -> float:
        return (1 - a ** (k + 1)) / (1 - a) / (k * (t_draft + v_node) + v0)

    return max(range(1, kmax + 1), key=rate)


# ---------- free drafts ----------
class FreeDrafter:
    """Draft tokens that cost nothing: copy what follows the last n tokens earlier in the context,
    or in a neighbour answer (e.g. the best semantic-cache hit below the serve threshold)."""

    def __init__(self, neighbour: list[int] | None = None, n: int = 3, m: int = 8) -> None:
        self.neighbour, self.n, self.m = neighbour or [], n, m

    def propose(self, ctx: list[int], gen_len: int) -> list[int]:
        if gen_len == 0:
            return self.neighbour[: self.m]
        key = ctx[-self.n:]
        for seq, end in ((ctx, len(ctx) - 1), (self.neighbour, len(self.neighbour))):
            for i in range(min(end, len(seq)) - self.n, -1, -1):  # most recent match first
                if seq[i: i + self.n] == key and i + self.n < len(seq):
                    return seq[i + self.n: i + self.n + self.m]
        return []


# ---------- wire ----------
def _vi(n: int, out: bytearray) -> None:
    while n >= 0x80:
        out.append(n & 0x7F | 0x80)
        n >>= 7
    out.append(n)


def _rv(b: bytes, i: int) -> tuple[int, int]:
    n = shift = 0
    while True:
        x = b[i]
        i += 1
        n |= (x & 0x7F) << shift
        if x < 0x80:
            return n, i
        shift += 7


def encode_tree(root: Node) -> bytes:
    out = bytearray()

    def walk(n: Node) -> None:
        _vi(len(n.q), out)
        for i, c in n.q:
            _vi(i, out)
            out.extend(struct.pack("b", c))
        _vi(len(n.kids), out)
        ids = [i for i, _ in n.q]
        for k in n.kids:
            _vi(ids.index(k.tok), out)
        for k in n.kids:
            walk(k)

    walk(root)
    return bytes(out)


def decode_tree(b: bytes) -> Node:
    pos = 0

    def walk(tok: int) -> Node:
        nonlocal pos
        nq, pos = _rv(b, pos)
        q = []
        for _ in range(nq):
            i, pos = _rv(b, pos)
            q.append((i, struct.unpack("b", b[pos: pos + 1])[0]))
            pos += 1
        nk, pos = _rv(b, pos)
        idx = []
        for _ in range(nk):
            j, pos = _rv(b, pos)
            idx.append(j)
        return Node(tok, q, [walk(q[j][0]) for j in idx])

    return walk(-1)


def encode_reply(idxs: list[int], final: int) -> bytes:
    out = bytearray()
    _vi(len(idxs), out)
    for j in idxs:
        _vi(j, out)
    _vi(final, out)
    return bytes(out)


def decode_reply(b: bytes) -> tuple[list[int], int]:
    n, i = _rv(b, 0)
    idxs = []
    for _ in range(n):
        j, i = _rv(b, i)
        idxs.append(j)
    return idxs, _rv(b, i)[0]


def json_bytes(prompt: list[int], chain: list[int]) -> tuple[int, int]:
    """Size of one round trip in the old stateless JSON protocol (bench/verify_server.py)."""
    up = json.dumps({"prompt_ids": prompt, "draft_ids": chain, "temperature": 1.0})
    down = json.dumps({"logprobs": [-0.123456789] * len(chain), "next_ids": [151643] * (len(chain) + 1),
                       "reused_tokens": len(prompt), "ms": 123.4})
    return len(up), len(down)


# ---------- the loop ----------
@dataclass
class Cfg:
    k: int = 4
    adaptive: bool = False
    kmax: int = 16
    tree: bool = False
    tree_thresh: float = 0.5  # branch where top-1 probability is below this
    tree_branch: int = 3
    pipeline: bool = False
    free: bool = False
    min_free: int = 2
    lossy: bool = False
    lossy_p: float = 0.98
    binary: bool = False
    rtt: float = 0.15  # seconds, modelled
    srv_base: float = 0.025  # seconds per verify pass (also per autoregressive token), modelled
    srv_node: float = 0.0005  # extra seconds per tree node, modelled
    max_new: int = 96


@dataclass
class Stats:
    tokens: int = 0
    rounds: int = 0
    seconds: float = 0.0
    accepted: int = 0  # draft tokens accepted
    rejections: int = 0
    nodes: int = 0  # draft nodes sent
    free_tokens: int = 0
    bytes_up: int = 0
    bytes_down: int = 0
    draft_calls: int = 0
    pre_used: int = 0
    pre_tried: int = 0
    unchecked: int = 0
    would_reject: float = 0.0
    out: list[int] = field(default_factory=list)

    def row(self) -> dict:
        t, r = max(self.tokens, 1), max(self.rounds, 1)
        return {"tok_s": round(self.tokens / self.seconds, 2) if self.seconds else 0.0,
                "rt_per_100": round(100 * self.rounds / t, 1),
                "alpha": round(self.accepted / max(self.accepted + self.rejections, 1), 3),
                "tok_per_rt": round(self.tokens / r, 2),
                "bytes_per_rt": round((self.bytes_up + self.bytes_down) / r),
                "passes_per_100": round(100 * self.rounds / t, 1),
                "free_frac": round(self.free_tokens / max(self.nodes, 1), 3)}


def _step(draft, ctx: list[int], cfg: Cfg, rng: random.Random, st: Stats):
    top, cost = draft.top(ctx)
    st.draft_calls += 1
    q = [(i, quant(lp)) for i, lp in top]
    qh = qhat(q)
    toks = [sample(qh, rng)]
    if cfg.tree and max(qh.values()) < cfg.tree_thresh:
        rest = dict(qh)
        for _ in range(cfg.tree_branch - 1):
            rest.pop(toks[-1])
            if not rest:
                break
            toks.append(sample(rest, rng))
    return (q, toks), cost


def _tree(steps) -> Node:
    root = cur = Node()
    for q, toks in steps:
        cur.q, cur.kids = q, [Node(t) for t in toks]
        cur = cur.kids[0]
    return root


def generate(prompt: list[int], draft, target, cfg: Cfg, rng: random.Random,
             free: FreeDrafter | None = None) -> Stats:
    st, ctx = Stats(), list(prompt)
    td, a_acc, a_rej, pre = 0.03, 7.0, 3.0, None  # pre = (g1 step, V seconds available)
    carry: list = []  # reused pre-draft steps
    first = True
    while st.tokens < cfg.max_new and not (st.out and st.out[-1] in EOS):
        gen_len = len(ctx) - len(prompt)
        v0 = cfg.rtt + cfg.srv_base
        k = choose_k(a_acc / (a_acc + a_rej), td, v0, cfg.srv_node, cfg.kmax) if cfg.adaptive else cfg.k
        k = min(k, cfg.max_new - st.tokens) if cfg.max_new - st.tokens > 0 else 1
        steps, cost, c = list(carry[:k]), 0.0, list(ctx)
        carry = []
        for q, toks in steps:
            c.append(toks[0])
        if cfg.free and free is not None and not steps:
            fr = free.propose(ctx, gen_len)[:k]
            if len(fr) >= cfg.min_free:
                steps = [([(t, 0)], [t]) for t in fr]
                c += fr
                st.free_tokens += len(fr)
        while len(steps) < k and not (c and c[-1] in EOS and len(c) > len(prompt)):
            s, cs = _step(draft, c, cfg, rng, st)
            steps.append(s)
            cost += cs
            td = 0.8 * td + 0.2 * cs
            c.append(s[1][0])
        root = _tree(steps)
        n_nodes = sum(len(t) for _, t in steps)
        chain = [t[0] for _, t in steps]
        v = cfg.rtt + cfg.srv_base + cfg.srv_node * n_nodes
        # pipelining: draft block N+1 from the tip while block N is in flight
        g1, extra = None, 0.0
        if cfg.pipeline and chain[-1] not in EOS:
            n_pre = max(1, min(cfg.kmax, int(v / max(td, 1e-6))))
            g1, cg = _step(draft, c, Cfg(tree=False), rng, st)
            st.pre_tried += 1
            pre = (g1, n_pre, c)
        verdict = verify_tree(root, lambda path: target.dist(ctx + path), rng, cfg.lossy_p if cfg.lossy else None)
        n_acc = len(verdict.tokens) - 1
        st.accepted += n_acc
        st.rejections += int(verdict.rejected)
        a_acc, a_rej = 0.8 * a_acc + n_acc, 0.8 * a_rej + int(verdict.rejected)
        st.unchecked += verdict.unchecked
        st.would_reject += verdict.would_reject
        # wire
        if cfg.binary:
            up = len(encode_tree(root)) + (len(prompt) * 3 + 2 if first else 0)
            down = len(encode_reply(verdict.idxs, verdict.tokens[-1]))
        else:
            up, down = json_bytes(ctx, chain)
        first = False
        st.bytes_up += up
        st.bytes_down += down
        # pre-draft reuse
        if g1 is not None and not verdict.rejected and not any(verdict.idxs) and verdict.tokens[-1] == g1[1][0]:
            st.pre_used += 1
            c2, steps2, pcost = list(pre[2]) + [g1[1][0]], [], 0.0
            while len(steps2) < pre[1] - 1 and len(steps2) < cfg.kmax:
                s, cs = _step(draft, c2, Cfg(tree=False), rng, st)
                steps2.append(s)
                pcost += cs
                c2.append(s[1][0])
            carry = steps2
            extra = max(0.0, pcost + cg - v)
        elif g1 is not None:
            extra = 0.0  # pre-draft stopped when the verdict arrived; it overlapped the wait
        st.seconds += cost + v + extra
        st.nodes += n_nodes
        st.rounds += 1
        new = verdict.tokens
        stop = next((i for i, x in enumerate(new) if x in EOS), None)
        new = new if stop is None else new[: stop + 1]
        ctx += new
        st.out += new
        st.tokens += len(new)
        if stop is not None:
            break
    return st


def autoregressive(prompt: list[int], target, cfg: Cfg, rng: random.Random) -> Stats:
    """Big model alone: one streamed request, one token per server step."""
    st, ctx = Stats(), list(prompt)
    for _ in range(cfg.max_new):
        t = sample(target.dist(ctx), rng)
        ctx.append(t)
        st.out.append(t)
        if t in EOS:
            break
    st.tokens = st.rounds = len(st.out)
    st.seconds = cfg.rtt + len(st.out) * cfg.srv_base
    return st
