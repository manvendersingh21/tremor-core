"""skeleton/bench/run.py in demo mode: the mix is reproducible and the store run counts hits and wrong hits."""
import importlib.util
import pathlib
import random

_p = pathlib.Path(__file__).resolve().parents[1] / "skeleton/bench/run.py"
_spec = importlib.util.spec_from_file_location("skeleton_bench_run", _p)
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


def test_mix_is_reproducible_and_mostly_repeats():
    a, b = bench.shopper_mix(200, random.Random(7)), bench.shopper_mix(200, random.Random(7))
    assert a == b and len(a) == 200
    assert len({q for q, _ in a}) < 60  # shoppers repeat themselves


def test_store_run_demo(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "OUT", tmp_path)
    s = bench.store(False, 60, 7)
    assert s["questions"] == 60 and s["warmup"]["questions"] == 30
    assert s["hit_rate"] > 0.7 and s["wrong_hits"] == 0
    assert s["big_only_dollars"] > s["dollars"]
    assert (tmp_path / "store_demo.jsonl").read_text().count("\n") == 60
