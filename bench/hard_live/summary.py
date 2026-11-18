"""Counting for bench/results_hard_live.md (no model, no DB: tests/test_hard_live.py runs it offline)."""
from __future__ import annotations

import math


def pct(xs: list[float], q: float) -> float:
    """Nearest-rank percentile; 0 for an empty list."""
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))]


def recovery(questions: list[dict], plain: list[dict], ladder: list[dict]) -> dict:
    """How many the 30B alone missed, how many the ladder got right anyway, and the ladder's own misses."""
    p = {r["id"]: r for r in plain}
    lad = {r["id"]: r for r in ladder}
    ids = [q["id"] for q in questions if q["id"] in p and q["id"] in lad]
    missed = [i for i in ids if p[i]["grade"] != 1]
    return {
        "plain_missed": len(missed),
        "ladder_recovered": sum(lad[i]["grade"] == 1 for i in missed),
        "ladder_still_wrong": sum(lad[i]["grade"] != 1 for i in missed),
        "ladder_lost": sum(p[i]["grade"] == 1 and lad[i]["grade"] != 1 for i in ids),
        # the failure that matters most: the ladder served a wrong 30B answer and never climbed
        "wrong_no_climb": sum(lad[i]["grade"] != 1 and lad[i]["tier"] == "gpu-small" and not lad[i].get("climbed")
                              for i in ids),
    }
