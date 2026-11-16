"""site/results.py reads its numbers from bench/*.md; site/results.json must match them."""
import json
import pathlib
import sys

SITE = pathlib.Path(__file__).resolve().parent.parent / "site"
sys.path.insert(0, str(SITE))
import results  # noqa: E402


def test_every_report_has_numbers_and_json_is_current():
    d = json.loads(results.build())
    assert len(d["reports"]) == 13  # 12 + the Akash tuning report
    for r in d["reports"]:
        assert r["metrics"] and all(m["value"] for m in r["metrics"]), r["id"]
    assert d["headlines"]["repeat_tokens_off"].endswith("%")
    assert (SITE / "results.json").read_text(encoding="utf-8") == results.build()


def test_missing_row_fails_loudly():
    try:
        results._cell("| a | b |", "| zzz |", 1)
    except KeyError:
        return
    raise AssertionError("expected KeyError")
