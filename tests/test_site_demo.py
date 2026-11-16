"""site/demo.py builds site/demo.json (what the page shows with no backend) from committed result files only."""
import csv
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
sys.path.insert(0, str(SITE))
import demo  # noqa: E402


@pytest.fixture(scope="module")
def d():
    return demo.build_dict()


def test_demo_json_is_up_to_date(d):
    assert (SITE / "demo.json").read_text(encoding="utf-8") == json.dumps(d, indent=1, ensure_ascii=False) + "\n"
    assert (SITE / "docs" / "tour_script.md").read_text(encoding="utf-8") == demo.tour_script(d)


def test_cost_rows_match_the_report(d):
    md = (ROOT / "bench/results_company_cost.md").read_text(encoding="utf-8")
    row = next(l for l in md.split("### h = 0")[1].splitlines() if l.startswith("| 1,000,000 |"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    one_m = next(r for r in d["cost"]["scale"]["no_repeats"] if r["calls_a_day"] == 1_000_000)
    assert one_m["gpt55_only"] == float(cells[1].strip("$").replace(",", ""))
    assert one_m["cascade_gpt55"] == float(cells[2].strip("$").replace(",", ""))
    assert one_m["saved_763"] == cells[6]
    assert any(r["tier"].startswith("GPT-5.5") and r["usd_per_1k"] == "$4.02" for r in d["cost"]["per_1k"]) == ("| GPT-5.5 (list price) | $4.02 |" in md)


def test_chat_replays_are_the_saved_rows(d):
    rows = {(r["pass"], r["id"]): r for r in csv.DictReader(open(ROOT / "bench/results_backend.csv", newline="", encoding="utf-8"))}
    assert len(d["chat"]["examples"]) >= 3
    for ex in d["chat"]["examples"]:
        first, again = dict(ex["first"])["final"], dict(ex["repeat"])["final"]
        assert first["ms"] == float(rows[("COLD", ex["id"])]["latency_ms"]) and first["cache"] is None
        assert again["ms"] == float(rows[("WARM", ex["id"])]["latency_ms"]) and again["cache"] == "shared"
        assert again["tier"] == rows[("WARM", ex["id"])]["tier_used"] and again["tokens_in"] == again["tokens_out"] == 0


def test_stats_block_has_the_api_shape(d):
    g = d["stats"]["global"]
    for k in ("calls", "tokens_today", "hit_rate", "cache", "by_tier", "by_task", "series", "tokens_kept_off_big", "dollars_saved"):
        assert k in g, k
    assert g["calls"] == sum(g["by_tier"].values()) == 120
    assert 0 < g["hit_rate"] < 1 and len(d["stats"]["recent"]) <= 20


def test_kiro_counts_are_read_from_the_tree(d):
    k = d["kiro"]
    assert len(k["steering"]) == len(list((ROOT / ".kiro/steering").glob("*.md")))
    assert len(k["specs"]) == len(list((ROOT / ".kiro/specs").glob("*/requirements.md")))
    assert len(k["agents"]) == len(list((ROOT / ".kiro/agents").glob("*.json")))
    props = sum(len(re.findall(r"^\s*@given\(", p.read_text(encoding="utf-8"), re.M)) for p in (ROOT / "tests").glob("test_props_*.py"))
    assert k["properties"] == props and k["bugs_fixed"] <= k["bugs_found"]


def test_tour_has_one_stop_per_hall_door_and_lasts_about_3_minutes(d):
    scene = (SITE / "game/scene.js").read_text(encoding="utf-8")
    rooms = [s["room"] for s in d["tour"] if "room" in s]
    assert rooms == demo.HALL
    assert set(rooms) == set(re.findall(r"\{ room: '(\w+)'", scene))
    assert 150 <= sum(s["secs"] for s in d["tour"]) <= 200
    assert d["tour"][-1].get("chart") and d["tour"][-1]["room"] == "ledger"


def test_parsers_fail_loudly():
    with pytest.raises(KeyError):
        demo.table("# a\n\ntext only\n", "# a")
    with pytest.raises(KeyError):
        demo.rx("abc", r"(\d+)")
    assert demo.money("-$2,889 (-611%)") == -2889.0 and demo.money("$12,060") == 12060.0


def test_pages_deploys_on_push_to_dev():
    wf = (ROOT / ".github/workflows/pages.yml").read_text(encoding="utf-8")
    assert re.search(r"push:\s*\n\s*branches:\s*\[\s*dev\s*\]", wf) and "site/build.py --check" in wf
