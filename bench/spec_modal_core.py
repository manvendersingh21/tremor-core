"""Greedy (temperature 0) speculative decoding loop over token ids, split across two servers.

draft(ctx, k)   -> list of up to k token ids the small model proposes after ctx
verify(ctx, d)  -> (m, nxt): the big model accepts the first m ids of d (m <= len(d)); nxt is the big model's own
                   next token (the correction at the first mismatch, or the bonus token after a full accept).
The output equals the big model's greedy output by construction (lossless), up to GPU numeric ties.
Pure Python, no network: the Modal runner supplies the two callables (deploy/modal/spec_modal.py).
"""
from dataclasses import dataclass, field
import time


@dataclass
class SpecStats:
    rounds: int = 0
    drafted: int = 0
    accepted: int = 0
    draft_ms: float = 0.0
    verify_ms: float = 0.0
    ks: list = field(default_factory=list)

    @property
    def alpha(self) -> float:
        return self.accepted / self.drafted if self.drafted else 0.0


def adaptive_k(k: int, m: int, sent: int, lo: int = 2, hi: int = 16) -> int:
    """Spec+ rule: a full accept grows K, a miss in the first half shrinks it."""
    if sent and m == sent:
        return min(hi, k + 2)
    if sent and m < sent // 2:
        return max(lo, k - 2)
    return k


def spec_generate(draft, verify, prompt_ids, max_tokens, k=4, adaptive=False, eos=frozenset()):
    ctx, out, st = list(prompt_ids), [], SpecStats()
    while len(out) < max_tokens:
        t0 = time.perf_counter()
        d = draft(ctx, min(k, max_tokens - len(out))) or []
        t1 = time.perf_counter()
        m, nxt = verify(ctx, d)
        t2 = time.perf_counter()
        new = d[:m] + [nxt]
        for i, t in enumerate(new):  # stop at the first EOS, keep it
            if t in eos:
                new = new[: i + 1]
                break
        new = new[: max_tokens - len(out)]
        out += new
        ctx += new
        st.rounds += 1
        st.drafted += len(d)
        st.accepted += m
        st.draft_ms += (t1 - t0) * 1e3
        st.verify_ms += (t2 - t1) * 1e3
        st.ks.append(k)
        if adaptive:
            k = adaptive_k(k, m, len(d))
        if new and new[-1] in eos:
            break
    return out, st


def first_diff(a, b):
    """Index of the first differing token, or -1 when equal (the lossless check)."""
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return -1 if len(a) == len(b) else min(len(a), len(b))
