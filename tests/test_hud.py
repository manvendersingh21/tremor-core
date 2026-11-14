import importlib.util
import json
import pathlib

_p = pathlib.Path(__file__).resolve().parent.parent / "apps" / "phantom-phone" / "hud-web" / "server.py"
_spec = importlib.util.spec_from_file_location("hud_server", _p)
hud = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hud)


def test_bench_merge(tmp_path):
    (tmp_path / "results.csv").write_text(
        "mode,id,cat,tier,latency_ms,quality,usd,cloud_prompt_tokens,cloud_completion_tokens\n"
        "A,e1,easy,cloud,100,1,0.01,10,5\nA,h1,heavy,cloud,300,1,0.03,20,5\n"
        "B,e1,easy,local,50,1,0,0,0\nB,h1,heavy,cloud_handoff,900,0,0.02,20,5\n")
    (tmp_path / "results_gpu.csv").write_text("mode,id,cat,tier,latency_ms,quality\nG,e1,easy,gpu,10,1\n")
    out = hud.bench_summary(tmp_path)
    assert [r["run"] for r in out["runs"]] == ["results", "results_gpu"]  # missing CSVs are skipped
    r = out["runs"][0]
    assert r["baseline"] == "A" and r["modes"]["A"]["usd"] == 0.04 and r["modes"]["A"]["remote_tokens"] == 40
    assert r["modes"]["A"]["per_tier"]["crusoe"] == {"input_tokens": 30, "output_tokens": 10}
    assert r["modes"]["B"]["tiers"] == {"local": 1, "cloud_handoff": 1}
    assert r["categories"]["heavy"]["B"]["latency_mean_ms"] > r["categories"]["heavy"]["A"]["latency_mean_ms"]


def test_sse_tail(tmp_path):
    f = tmp_path / "t.jsonl"
    assert hud.read_new_events(f, 0) == ([], 0)  # file not created yet
    f.write_text(json.dumps({"a": 1}) + "\n" + '{"b"')  # second line still being written
    ev, off = hud.read_new_events(f, 0)
    assert ev == [{"a": 1}]
    with open(f, "a") as fh:
        fh.write(': 2}\n')
    ev, off = hud.read_new_events(f, off)
    assert ev == [{"b": 2}]
    f.write_text('{"c": 3}\n')  # truncated by a new demo run
    ev, off = hud.read_new_events(f, off)
    assert ev == [{"c": 3}]


def test_telemetry_per_tier_optional():
    from chimera_core.inference.telemetry import Telemetry, TierUsage
    old = Telemetry(tier_used="local", local_tokens=5)
    assert old.per_tier is None and "per_tier" in old.model_dump()  # old shape still valid
    new = Telemetry(tier_used="cloud_handoff", per_tier={
        "mac_3b": TierUsage(model="qwen2.5-3b", device="mac", input_tokens=40, output_tokens=60, latency_ms=800),
        "crusoe": TierUsage(model="Qwen/Qwen3.8-27B", device="cloud", input_tokens=90, output_tokens=200, dollars=0.0005)})
    back = Telemetry.model_validate(json.loads(json.dumps(new.model_dump())))
    assert back.per_tier["crusoe"].model == "Qwen/Qwen3.8-27B" and back.per_tier["mac_3b"].output_tokens == 60
