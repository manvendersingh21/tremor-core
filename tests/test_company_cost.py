"""Money math of bench/company_cost/report.py. Offline: pure functions, no rows needed."""
import importlib.util
import math
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "bench/company_cost/report.py"


def load():
    spec = importlib.util.spec_from_file_location("company_cost_report", SRC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_h200_price_and_break_even():
    m = load()
    assert math.isclose(m.H200_FULL[64], 108.96 / (301 / 16.7 * 86400) * 1000)
    assert math.isclose(m.h200_per_1k(0.5), 2 * m.H200_FULL[64])
    u = m.break_even_util(0.1576)
    assert math.isclose(m.h200_per_1k(u), 0.1576)  # at break-even the per-call prices match
    assert 0.40 < u < 0.48


def test_monthly_cascade_parts_add_up():
    m = load()
    c = m.monthly(1_000_000, "GPT-5.5")
    assert c["h200s"] == 2  # 1M a day over 0.78M per H200 at half load
    assert math.isclose(c["gpu"], 2 * 108.96 * 30)
    assert math.isclose(c["escalated_per_day"], 1_000_000 * 31 / 301)
    assert math.isclose(c["total"], c["gpu"] + c["escalation"] + 25.0)
    assert m.monthly(1_000_000, "GPT-5.5", served_free=1.0)["h200s"] == 0  # all served by cache: no GPU
    assert math.isclose(m.api_only(100_000, "GPT-5.5"), 100_000 * 30 * 4.02 / 1000)


def test_tuned_v100_price_and_cascade():
    m = load()
    assert math.isclose(m.V100_FULL[0.52], 0.52 * 369.9 / 3600 / 301 * 1000)  # $0.18 per 1k, results_akash_tuning.md
    assert round(m.V100_FULL[1.53], 2) == 0.52
    assert m.V100_FULL[0.52] > m.PRICE["763B"]["all"]  # even full, a tuned V100 does not beat the 763B per call
    c = m.v100_monthly(100_000, "GPT-5.5")
    assert c["boxes"] == math.ceil(100_000 / (m.V100_CAP * 0.5))
    assert math.isclose(c["gpu"], c["boxes"] * 0.52 * 24 * 30)
    assert math.isclose(c["escalated_per_day"], 100_000 * 31 / 301)
    assert m.monthly(1_000_000, "GPT-5.5")["h200s"] == 2  # the H200 path is unchanged
