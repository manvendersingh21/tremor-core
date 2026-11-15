"""--estimate: classify each request without calling a model, then project cost from measured rates.

Every number this module produces from DEFAULT_RATES is a projection built on assumptions. Rates measured by a
--live run (rates_from_live) replace them; the report labels which one was used.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Callable

from . import prices
from .logs import Req, est_tokens

CLASSES = ("repeat", "near_repeat", "easy_code", "lookup", "general", "hard")
HEAVY = 0.6  # same threshold the router uses for "skip the small tiers" (chimera.toml [thresholds] heavy)
CODE = re.compile(r"```|\b(python|javascript|typescript|java|c\+\+|rust|golang|sql|bash|regex|function|script|code|bug|"
                  r"compile|syntax|html|css|api|json)\b|\bdef \w+\(|\bclass \w+", re.I)

# ASSUMED placeholders (no bench/results_cost_case.md yet). p30 = share of that class the 30B answers without climbing;
# agree = share of 30B answers a judge scores as good as the 763B's; wrong_hit = wrong semantic cache hits per hit.
DEFAULT_RATES = {
    "source": "assumed defaults, not measured on this log",
    "p30": {"easy_code": 0.85, "lookup": 0.85, "general": 0.6, "hard": 0.0},
    "agree": 0.9, "wrong_hit": 0.03, "out_tokens": 300,
}


def complexity(prompt: str) -> float:
    """Same heuristic as the router (packages/chimera-core/router.py complexity_score)."""
    from chimera_core.router import complexity_score
    return complexity_score(prompt)


def kind(prompt: str) -> str:
    c = complexity(prompt)
    if c >= HEAVY or len(prompt) > 2000:
        return "hard"
    if CODE.search(prompt):
        return "easy_code" if len(prompt) <= 800 else "hard"
    return "lookup" if len(prompt) <= 300 else "general"


def _norm(t: str) -> str:
    return " ".join(t.lower().split())


def classify(reqs: list[Req], embed: Callable[[str], list[float]] | None = None, threshold: float = 0.97,
             pairs: dict[int, int] | None = None) -> list[str]:
    """A repeat is an exact match (after whitespace and case folding) of an earlier request; a near repeat is an earlier
    request at cosine >= threshold that also passes the cache guard. Otherwise the request is classed by content.
    The cache starts empty and warms from this log only: the first occurrence is always a miss.
    `pairs`, if given, is filled with {request index: earlier index it would hit} for near repeats."""
    from chimera_core.cache.guard import consistent
    out: list[str] = []
    seen: dict[str, int] = {}
    near: dict[int, int] = {}
    if embed is not None and len(reqs) > 1:
        import numpy as np
        E = np.array([embed(r.prompt) for r in reqs], dtype="float32")
        E /= np.linalg.norm(E, axis=1, keepdims=True).clip(1e-9)
        for i0 in range(0, len(reqs), 500):
            S = E[i0:i0 + 500] @ E[:i0 + 500].T
            for k in range(S.shape[0]):
                i = i0 + k
                for j in np.argsort(-S[k, :i])[:5] if i else []:  # best earlier candidates, most similar first
                    if S[k, j] < threshold:
                        break
                    if consistent(reqs[i].prompt, reqs[j].prompt):
                        near[i] = int(j)
                        break
    if pairs is not None:
        pairs.update(near)
    for i, r in enumerate(reqs):
        key = _norm(r.prompt)
        if key in seen:
            out.append("repeat")
        elif i in near:
            out.append("near_repeat")
        else:
            out.append(kind(r.prompt))
        seen.setdefault(key, i)
    return out


def tokens(r: Req, out_default: int) -> tuple[int, int, bool]:
    """(in, out, estimated?). Logged usage wins; else len/4 of the prompt plus system prompt, and the default output length."""
    est = r.tokens_in is None or r.tokens_out is None
    return (r.tokens_in if r.tokens_in is not None else est_tokens(r.prompt) + r.sys_chars // 4,
            r.tokens_out if r.tokens_out is not None else out_default, est)


def project_rows(reqs: list[Req], classes: list[str], rates: dict) -> list[dict]:
    """One row per request with expected (fractional) ladder cost. Cache classes cost nothing; the rest climb to the 763B with probability 1 - p30."""
    rows = []
    for r, c in zip(reqs, classes):
        tin, tout, est = tokens(r, rates["out_tokens"])
        cache = c in ("repeat", "near_repeat")
        p30 = 1.0 if cache else rates["p30"].get(c, 0.0)
        top = 0.0 if cache else 1 - p30
        rows.append({"id": r.id, "cls": c, "tin": tin, "tout": tout, "est_tokens": est, "top_frac": top,
                     "ladder_top_tokens": top * (tin + tout), "ladder_usd": top * prices.usd(tin, tout, prices.TOP),
                     "wrong_hit": rates["wrong_hit"] if c == "near_repeat" else 0.0,
                     "bad_answer": p30 * (1 - rates["agree"]) if not cache else 0.0})
    return rows


def summarize(rows: list[dict], company: str, volume_per_month: int | None = None, gpu_box: bool = True) -> dict:
    """Totals, per 1k requests and per month, for one company model price. Works on estimate rows and live rows alike
    (both carry tin, tout, ladder_usd, ladder_top_tokens, cls, wrong_hit, bad_answer)."""
    n = len(rows)
    price = prices.PRICES[company]
    base = sum(prices.usd(r["tin"], r["tout"], price) for r in rows)
    ladder = sum(r["ladder_usd"] for r in rows)
    base_tok = sum(r["tin"] + r["tout"] for r in rows)
    top_tok = sum(r["ladder_top_tokens"] for r in rows)
    k = 1000 / n if n else 0
    vol = volume_per_month or 0
    s = {"company_model": company, "company_price_in_out": price[:2], "price_source": price[2], "n": n,
         "classes": dict(Counter(r["cls"] for r in rows)),
         "baseline_usd": base, "ladder_usd": ladder, "baseline_tokens": base_tok, "ladder_top_tokens": top_tok,
         "tokens_saved_pct": 100 * (1 - top_tok / base_tok) if base_tok else None,
         "usd_saved_pct": 100 * (1 - ladder / base) if base else None,
         "per_1k": {"baseline_usd": base * k, "ladder_usd": ladder * k, "baseline_tokens": base_tok * k, "ladder_top_tokens": top_tok * k},
         "wrong_cache_hits": sum(r["wrong_hit"] for r in rows), "bad_answers": sum(r["bad_answer"] for r in rows),
         "tokens_estimated": sum(r["est_tokens"] for r in rows)}
    if vol and n:
        gpu = prices.GPU_USD_PER_HOUR * prices.HOURS_PER_MONTH if gpu_box else 0.0
        s["monthly"] = {"volume": vol, "baseline_usd": base / n * vol, "ladder_usd": ladder / n * vol, "gpu_box_usd": gpu,
                        "ladder_total_usd": ladder / n * vol + gpu,
                        "break_even_volume": int(gpu / ((base - ladder) / n)) if base > ladder else None}
    return s
