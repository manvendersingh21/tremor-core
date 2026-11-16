"""bench/cost_case/run_akash_tuning.py: stratified 20-task subset, resumable runs, cost per 1,000 calls. Offline: HTTP is faked."""
import importlib.util
import json
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "bench/cost_case/run_akash_tuning.py"


def load():
    spec = importlib.util.spec_from_file_location("run_akash_tuning", SRC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_subset_is_20_stratified():
    m = load()
    rows = [json.loads(x) for x in m.TASKS.read_text().splitlines()]
    s = m.subset(rows)
    by = {d: sum(r["difficulty"] == d for r in s) for d in ("trivial", "everyday", "hard")}
    assert by == {"trivial": 5, "everyday": 10, "hard": 5}


def test_summarize_cost_and_speed():
    m = load()
    rows = [{"latency_ms": 2000, "tokens_out": 100, "eval_ms": 1000, "pass": 1},
            {"latency_ms": 4000, "tokens_out": 300, "eval_ms": 2000, "pass": 0}]
    s = m.summarize(rows, wall_s=7.2, prices=(1.0,))
    assert s["pass"] == 1 and s["n"] == 2
    assert s["decode_tok_s"] == 125.0  # median of 100 and 150 tok/s
    assert s["tok_s_total"] == round(400 / 7.2, 1)
    assert s["usd_per_1k"] == [1.0]  # $1/hr x 7.2 s / 2 calls x 1000 = $1.00


def test_run_resumes_and_grades(tmp_path, monkeypatch):
    m = load()
    monkeypatch.setattr(m, "STORE", tmp_path)
    seen = []

    def fake(url, backend, prompt, opts, keep_alive, logprobs):
        seen.append(prompt)
        return {"text": "no code", "tokens_in": 5, "tokens_out": 2, "eval_ms": 10, "prompt_ms": 1, "load_ms": 0}

    monkeypatch.setattr(m, "call", fake)
    m.run("t", 2, "http://example.invalid", "ollama", {}, None, True)
    first = len(seen)
    m.run("t", 2, "http://example.invalid", "ollama", {}, None, True)  # all done: no calls
    rows = [json.loads(x) for x in (tmp_path / "t_c2.jsonl").read_text().splitlines()]
    assert first == 21 and len(seen) == 21  # 20 tasks + 1 warm-up, nothing on the rerun
    assert len(rows) == 20 and all(r["pass"] == 0 for r in rows)
