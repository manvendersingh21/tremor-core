"""Offline tests for bench/datasets/grade.py (no models, no keys, no downloads)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "bench" / "datasets"))
import grade  # noqa: E402

HE = {"kind": "humaneval", "prompt": 'def add(a, b):\n    """sum"""\n', "entry_point": "add",
      "test": "def check(f):\n    assert f(1, 2) == 3\n"}


def test_unit_test_pass_fail_and_body_only():
    row = {"grader": "unit_test", "data": HE}
    assert grade.grade(row, "```python\ndef add(a, b):\n    return a + b\n```") == 1
    assert grade.grade(row, "```python\ndef add(a, b):\n    return a - b\n```") == 0
    assert grade.grade(row, "```python\n    return a + b\n```") == 1  # body only continues the stub


def test_sandbox_blocks_network_hides_env_and_times_out(monkeypatch):
    monkeypatch.setenv("CRUSOE_API_KEY", "secret")
    assert not grade.run_sandboxed("import socket\nsocket.create_connection(('127.0.0.1', 9), 1)")
    assert grade.run_sandboxed("import os\nassert 'CRUSOE_API_KEY' not in os.environ")
    monkeypatch.setattr(grade, "TIMEOUT_S", 1)
    assert not grade.run_sandboxed("while True: pass")


def test_exact_and_choice():
    assert grade.grade({"grader": "exact", "data": {"expected": "1800"}}, "so $1,800.\nAnswer: 1,800") == 1
    assert grade.grade({"grader": "exact", "data": {"expected": "18"}}, "I get 17") == 0
    assert grade.grade({"grader": "choice", "data": {"expected": "B"}}, "B. Paris") == 1
    assert grade.grade({"grader": "choice", "data": {"expected": "B"}}, "The answer is C") == 0
    assert grade.grade({"grader": "pair", "data": {}}, "x") is None
