"""run_h200.gen is resumable: finished ids are skipped, wall time accumulates. Offline: the HTTP call is faked."""
import importlib.util
import json
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "bench/cost_case/run_h200.py"


def load():
    spec = importlib.util.spec_from_file_location("run_h200", SRC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_gen_resumes_and_skips_done(tmp_path, monkeypatch):
    m = load()
    monkeypatch.setattr(m, "STORE", tmp_path)
    monkeypatch.setattr(m, "load_env", lambda: None)
    monkeypatch.setenv("MODAL_QWEN_URL", "http://example.invalid")
    monkeypatch.setenv("MODAL_VLLM_TOKEN", "x")
    calls = []

    def fake(url, key, prompt):
        calls.append(prompt)
        return {"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}

    monkeypatch.setattr(m, "call", fake)
    m.gen(2, 3)
    first = len(calls)
    m.gen(2, 5)  # two more tasks only
    rows = [json.loads(x) for x in (tmp_path / "gen_c2.jsonl").read_text().splitlines()]
    assert first == 3 and len(calls) == 5
    assert len({r["id"] for r in rows}) == 5
    assert (tmp_path / "gen_c2.wall").exists()
