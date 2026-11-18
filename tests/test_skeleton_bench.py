"""skeleton/bench/run.py in demo mode: the mix is reproducible and the help-desk run counts hits, wrong hits and cost per ticket."""
import importlib.util
import pathlib
import random

_p = pathlib.Path(__file__).resolve().parents[1] / "skeleton/bench/run.py"
_spec = importlib.util.spec_from_file_location("skeleton_bench_run", _p)
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


def test_mix_is_reproducible_and_mostly_repeats():
    a, b = bench.ticket_mix(200, random.Random(7)), bench.ticket_mix(200, random.Random(7))
    assert a == b and len(a) == 200
    assert len({q for q, _ in a}) < 60  # customers repeat themselves


def test_helpdesk_run_demo(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "OUT", tmp_path)
    s = bench.helpdesk(False, 60, 7)
    assert s["questions"] == 60 and s["warmup"]["questions"] == 30
    assert s["hit_rate"] > 0.7 and s["wrong_hits"] == 0
    assert s["big_only_dollars"] > s["dollars"]
    c = {x["tickets"]: x["tokens"] for x in s["curve"]}
    assert c[50] < c[30]  # model tokens per ticket fall after the warm-up
    assert (tmp_path / "helpdesk_demo.jsonl").read_text().count("\n") == 60
