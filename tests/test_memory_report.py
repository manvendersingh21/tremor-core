"""bench/memory/report.py builds the N+1 report from cached rows (no models, no keys)."""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_report_builds_from_rows(tmp_path, monkeypatch):
    for p in (ROOT / "bench", ROOT / "bench" / "memory", ROOT / "bench" / "datasets"):
        monkeypatch.syspath_prepend(str(p))
    import run_memory as R
    import report
    monkeypatch.setattr(R, "STORE", tmp_path)
    monkeypatch.setattr(R, "OUT_MD", tmp_path / "r.md")
    monkeypatch.setattr(R, "OUT_CSV", tmp_path / "r.csv")
    test = [{"id": f"mbpp-{i}"} for i in range(4)]

    def put(name, passes):
        with (tmp_path / name).open("w") as fh:
            for t, ok in zip(test, passes):
                fh.write(json.dumps({"id": t["id"], "pass": ok, "tin": 100, "tout": 50, "usd": 0.001, "ms": 10, "ctx_chars": 5}) + "\n")
    (tmp_path / "ctx_sizes.json").write_text(json.dumps({"sizes": [2, 4]}))
    put("baseline30.jsonl", [1, 1, 0, 0])
    put("top_test.jsonl", [1, 1, 1, 0])
    put("with_mem_2.jsonl", [1, 1, 1, 0])
    put("with_mem_4.jsonl", [1, 0, 1, 0])
    put("control_random.jsonl", [1, 1, 0, 0])
    report.write(test, [{"id": "t1"}], [{"id": "t1"}])
    md = (tmp_path / "r.md").read_text()
    assert "fixed 1 problems and broke 1" in md  # the % in "95%" once broke the %-format
    assert "one run of 4 problems" in md
    assert (tmp_path / "r.csv").read_text().count("\n") == 1 + 2 + 1 + 1 + 1
