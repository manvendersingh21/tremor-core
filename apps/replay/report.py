"""Markdown and JSON output for a replay. Numbers come from estimate.summarize(); this module only formats."""
from __future__ import annotations

from . import prices
from .estimate import CLASSES, summarize


def _pct(v) -> str:
    return "n/a" if v is None else f"{v:.1f}%"


def build(rows: list[dict], mode: str, rates: dict, volume: int | None, extra: dict | None = None) -> dict:
    """mode: 'live' (measured on this log) or 'estimate' (projection). One summary per company model price."""
    return {"mode": mode, "label": "measured on this run" if mode == "live" else "PROJECTION, not measured on this log",
            "rates_source": rates["source"], "rates": rates, "n": len(rows),
            "by_model": {m: summarize(rows, m, volume) for m in prices.PRICES},
            "ladder_price": {"model": "DeepSeek-V4.1-Flash 763B", "in_out_per_m": prices.TOP[:2], "source": prices.TOP[2]},
            "gpu_box": {"usd_per_hour": prices.GPU_USD_PER_HOUR, "source": "bench/cost_case/report.py V100_HR (an assumption, not an invoice)"},
            **(extra or {})}


def markdown(rep: dict, title: str = "chimera replay") -> str:
    L = [f"# {title}", "", f"**{rep['label']}.** {rep['n']} requests. Rates: {rep['rates_source']}.", ""]
    first = next(iter(rep["by_model"].values()))
    L += ["Request classes: " + ", ".join(f"{c} {first['classes'].get(c, 0)}" for c in CLASSES), ""]
    if first["tokens_estimated"]:
        L += [f"Token counts: {first['tokens_estimated']} of {first['n']} requests had no usage in the log, so input is len/4 and output is "
              f"{'the ladder answer length' if rep['mode'] == 'live' else 'the assumed default'} (len/4 is rough).", ""]
    L += ["## Cost per 1,000 requests", "",
          "| Company model | in/out $ per M | Their $ | Ladder $ (763B only) | $ saved | Tokens on frontier | Tokens on 763B | Tokens saved |",
          "|---|---|---|---|---|---|---|---|"]
    for m, s in rep["by_model"].items():
        k = s["per_1k"]
        L.append(f"| {m} | {s['company_price_in_out'][0]}/{s['company_price_in_out'][1]} | ${k['baseline_usd']:.2f} | ${k['ladder_usd']:.2f} | "
                 f"{_pct(s['usd_saved_pct'])} | {k['baseline_tokens']:,.0f} | {k['ladder_top_tokens']:,.0f} | {_pct(s['tokens_saved_pct'])} |")
    if first.get("monthly"):
        v = first["monthly"]["volume"]
        L += ["", f"## Per month at {v:,} requests", "",
              f"The ladder also needs a GPU box: ${prices.GPU_USD_PER_HOUR}/h x {prices.HOURS_PER_MONTH} h = ${first['monthly']['gpu_box_usd']:.0f} a month, fixed, whatever the volume.", "",
              "| Company model | Their $/month | Ladder token $ | + GPU box | Ladder total | Net saving | Break-even requests/month |", "|---|---|---|---|---|---|---|"]
        for m, s in rep["by_model"].items():
            mo = s["monthly"]
            L.append(f"| {m} | ${mo['baseline_usd']:,.0f} | ${mo['ladder_usd']:,.0f} | ${mo['gpu_box_usd']:,.0f} | ${mo['ladder_total_usd']:,.0f} | "
                     f"${mo['baseline_usd'] - mo['ladder_total_usd']:,.0f} | {mo['break_even_volume']:,} |" if mo["break_even_volume"] else
                     f"| {m} | ${mo['baseline_usd']:,.0f} | ${mo['ladder_usd']:,.0f} | ${mo['gpu_box_usd']:,.0f} | ${mo['ladder_total_usd']:,.0f} | "
                     f"${mo['baseline_usd'] - mo['ladder_total_usd']:,.0f} | never |")
    L += ["", "## Quality"]
    q = rep.get("quality")
    if q:
        L += [f"- 30B answers judged against the 763B answer: {q['passed']} of {q['judged']} pass (score >= 4 of 5).",
              f"- Cache hits: {q['exact_hits']} exact, {q['semantic_hits']} semantic. Wrong semantic hits: {q['wrong_cache_hits']} of {q['semantic_hits_judged']} judged.",
              f"- Requests that failed on every tier: {q['failed_requests']}."]
    else:
        L += [f"- Projected 30B answers judged worse than the 763B: {first['bad_answers']:.0f} of {first['n']}.",
              f"- Projected wrong cache hits: {first['wrong_cache_hits']:.1f}."]
    L += ["", "## Prices", "", "| Model | in $/M | out $/M | Source |", "|---|---|---|---|"]
    L += [f"| {m} | {p[0]} | {p[1]} | {p[2]} |" for m, p in prices.PRICES.items()]
    L += [f"| ladder top (763B) | {prices.TOP[0]} | {prices.TOP[1]} | {prices.TOP[2]} |"]
    return "\n".join(L) + "\n"
