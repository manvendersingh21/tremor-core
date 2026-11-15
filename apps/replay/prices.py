"""List prices, USD per million tokens (in, out). Check the source before quoting a number to a customer."""
from __future__ import annotations

PRICES: dict[str, tuple[float, float, str]] = {
    "gpt-5.5-class": (5.0, 30.0, "bench/cost_case/report.py (GPT-5.5 list price used by the cost-case run)"),
    "claude-opus-class": (4.0, 20.0, "https://developer.puter.com/tutorials/claude-api-pricing/ (Claude Opus 5.5, Oct 2026); primary: https://platform.claude.com/docs/en/about-claude/pricing"),
    "claude-sonnet-class": (2.0, 10.0, "https://developer.puter.com/tutorials/claude-api-pricing/ (Claude Sonnet 5.5, Oct 2026); primary: https://platform.claude.com/docs/en/about-claude/pricing"),
    "grok-class": (2.0, 6.0, "bench/cost_case/report.py (Grok-4.5 list price)"),
}
TOP = (0.29, 1.20, "bench/results_ladder.md (Crusoe DeepSeek-V4.1-Flash 763B list; cached-input discount ignored)")
JUDGE = (0.15, 0.50, "bench/run_suite.py (GMI zai-org/GLM-5.3-Flash list)")
GPU_USD_PER_HOUR = 0.50  # V100 box, bench/cost_case/report.py V100_HR. A fixed monthly cost, not per token.
HOURS_PER_MONTH = 730


def usd(tin: float, tout: float, price: tuple) -> float:
    return (tin * price[0] + tout * price[1]) / 1e6
