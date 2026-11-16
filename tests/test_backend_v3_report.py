import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "bench")]

import backend_v3_report as V  # noqa: E402


def test_gpu_calls_counts_timeouts_and_slow_calls(tmp_path):
    ev = lambda tier, ok, ms, err=None: {"step": "call", "tier": tier, "ok": ok, "ms": ms, "error": err}  # noqa: E731
    rows = [{"events": [ev("gpu-small", True, 2000), ev("cloud-deepseek", True, 900)]},
            {"events": [ev("gpu-small", False, 90010, "TimeoutError"), ev("cloud-deepseek", True, 800)]},
            {"events": [ev("gpu-small", True, 95000)]}]
    (tmp_path / "backend_telemetry.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    g = V.gpu_calls(tmp_path)
    assert g["n"] == 3 and g["errors"] == {"TimeoutError": 1} and g["over90"] == 1 and g["max"] == 95000
