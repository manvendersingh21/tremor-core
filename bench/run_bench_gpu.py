"""GPU benchmark: G = every prompt to the GPU (Ollama qwen3:30b-instruct), H = Mac cascade + GPU tier.

Needs an ssh tunnel to the GPU's Ollama on 127.0.0.1:11435 (see bench/results_gpu.md for the command).
    .venv/bin/python bench/run_bench_gpu.py G        # GPU only
    .venv/bin/python bench/run_bench_gpu.py H        # cascade; needs llama-server on 127.0.0.1:8080
    .venv/bin/python bench/run_bench_gpu.py report   # write results_gpu.csv / results_gpu.md from the two runs
Per-mode rows are kept in $KIROCREW_SCRATCH (or bench/) as gpu_<mode>.json.
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))
import conftest  # noqa: E402,F401

from chimera_core import RouterConfig, SpeculativeCascadeRouter  # noqa: E402
from chimera_core.cache.semantic_cache import OnnxMiniLMEmbedder, SemanticCache  # noqa: E402
from chimera_core.inference.cloud_verifier import CloudVerifier, OllamaBackend  # noqa: E402
from chimera_core.inference.local_draft import LlamaCppBackend  # noqa: E402
from run_bench import run_tests  # noqa: E402  (reuse the unit-test grader)

MAX_GPU = 2500
STORE = pathlib.Path(os.environ.get("KIROCREW_SCRATCH") or ROOT / "bench")


def passed(p: dict, ans: str):
    if "expect" in p:
        return int(any(e in ans.lower() for e in p["expect"]))
    if "tests" in p:
        return int(run_tests(ans, p["tests"]))
    return ""


def run(mode: str) -> None:
    prompts = [json.loads(x) for x in (ROOT / "bench/prompts.jsonl").read_text().splitlines() if x.strip()]
    gpu = OllamaBackend()
    t0 = time.perf_counter()
    gpu.complete("hello", 4)  # first call loads the model; timed separately
    warm = {"first_call_ms": round((time.perf_counter() - t0) * 1000), "load_ms": gpu.last_usage["load_duration_ms"]}
    gpu.usage_log.clear()
    rows = []
    if mode == "G":
        for p in prompts:
            t0 = time.perf_counter()
            ans = gpu.complete(p["prompt"], MAX_GPU)
            ms = (time.perf_counter() - t0) * 1000
            u = gpu.last_usage
            rows.append({"mode": "G", "id": p["id"], "cat": p["cat"], "tier": "gpu", "latency_ms": round(ms),
                         "local_tokens": 0, "gpu_prompt_tokens": u["prompt_tokens"],
                         "gpu_completion_tokens": u["completion_tokens"], "quality": passed(p, ans)})
            print("G", p["id"], round(ms), flush=True)
    else:
        local = LlamaCppBackend()
        local.complete("hello", 4)
        sem = SemanticCache(OnnxMiniLMEmbedder())
        sem._embedder.embed("warm up")
        router = SpeculativeCascadeRouter(local=local, cloud=CloudVerifier(gpu), semantic=sem,
                                          config=RouterConfig(max_cloud_tokens=MAX_GPU))
        for p in prompts:
            n0 = len(gpu.usage_log)
            res = router.generate(p["prompt"])
            t = res.telemetry
            u = gpu.usage_log[-1] if len(gpu.usage_log) > n0 else {"prompt_tokens": 0, "completion_tokens": 0}
            rows.append({"mode": "H", "id": p["id"], "cat": p["cat"], "tier": t.tier_used,
                         "latency_ms": round(t.latency_ms), "local_tokens": t.local_tokens,
                         "gpu_prompt_tokens": u["prompt_tokens"], "gpu_completion_tokens": u["completion_tokens"],
                         "quality": passed(p, res.text)})
            print("H", p["id"], t.tier_used, round(t.latency_ms), flush=True)
    (STORE / f"gpu_{mode}.json").write_text(json.dumps({"warm": warm, "rows": rows}, indent=1))


def agg(rows: list[dict]) -> dict:
    lat = sorted(r["latency_ms"] for r in rows)
    graded = [r["quality"] for r in rows if r["quality"] != ""]
    return {"gpu_prompt": sum(r["gpu_prompt_tokens"] for r in rows),
            "gpu_completion": sum(r["gpu_completion_tokens"] for r in rows),
            "gpu_calls": sum(1 for r in rows if r["gpu_prompt_tokens"]),
            "local": sum(r["local_tokens"] for r in rows),
            "median": statistics.median(lat), "p90": lat[min(len(lat) - 1, int(0.9 * len(lat)))],
            "total_s": sum(lat) / 1000, "pass": sum(graded), "graded": len(graded)}


def report() -> None:
    g, h = (json.loads((STORE / f"gpu_{m}.json").read_text()) for m in "GH")
    with open(ROOT / "bench/results_gpu.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(g["rows"][0]))
        w.writeheader()
        w.writerows(g["rows"] + h["rows"])
    a, b = agg(g["rows"]), agg(h["rows"])
    tg, th = a["gpu_prompt"] + a["gpu_completion"], b["gpu_prompt"] + b["gpu_completion"]
    tiers: dict[str, int] = {}
    for r in h["rows"]:
        tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
    gpu_s_g, gpu_s_h = a["total_s"], b["total_s"]
    md = f"""# GPU benchmark results

Measured by `bench/run_bench_gpu.py` on {len(g['rows'])} prompts (`bench/prompts.jsonl`). Raw rows: `bench/results_gpu.csv`.

## Setup
- GPU tier: Ollama `qwen3:30b-instruct` (Q4_K_M) on a Tesla V100 32 GB, reached through an ssh tunnel on 127.0.0.1:11435. `think=false`, `num_predict`={MAX_GPU}.
- G = every prompt goes to the GPU. H = `SpeculativeCascadeRouter`: exact + semantic cache, local Qwen2.5-3B (llama.cpp, Mac), GPU as the cloud tier with a local-written brief.
- Model load on first call (not in the numbers below): G first call {g['warm']['first_call_ms']} ms (load {g['warm']['load_ms']} ms); H first call {h['warm']['first_call_ms']} ms (load {h['warm']['load_ms']} ms).
- Quality = `expect` keyword match or unit tests ({a['graded']} graded prompts). No LLM grader.

## G vs H
| | G: GPU only | H: Mac cascade + GPU |
|---|---|---|
| GPU calls | {a['gpu_calls']} | {b['gpu_calls']} |
| GPU prompt tokens | {a['gpu_prompt']} | {b['gpu_prompt']} |
| GPU completion tokens | {a['gpu_completion']} | {b['gpu_completion']} |
| GPU tokens total | {tg} | {th} |
| Local (Mac) tokens | 0 | {b['local']} |
| Median latency ms | {a['median']:.0f} | {b['median']:.0f} |
| p90 latency ms | {a['p90']:.0f} | {b['p90']:.0f} |
| Total wall time s | {a['total_s']:.0f} | {b['total_s']:.0f} |
| Passed | {a['pass']}/{a['graded']} | {b['pass']}/{b['graded']} |

GPU tokens saved by H: **{tg - th}** ({100 * (tg - th) / tg if tg else 0:.1f}%). GPU calls saved: {a['gpu_calls'] - b['gpu_calls']}.

H tier breakdown: {', '.join(f'{k}: {v}' for k, v in sorted(tiers.items()))}

## GPU time
Wall time is a latency sum, not a GPU-busy time. At an assumed $/hr R, G costs about {gpu_s_g / 3600:.3f}*R and H at most {gpu_s_h / 3600:.3f}*R (H wall time includes local-model time, so its GPU share is lower). No $/hr was given, so no dollar figure is stated.

## Rerun
```
ssh -f -N -L 127.0.0.1:<port>:127.0.0.1:11434 <gpu-host>   # an SSH tunnel to your GPU box
.venv/bin/python bench/run_bench_gpu.py G
.venv/bin/python bench/run_bench_gpu.py H     # needs bench/serve_local.sh running
.venv/bin/python bench/run_bench_gpu.py report
pkill -f "ssh -f -N -L 127.0.0.1:11435"       # close the tunnel
```

## Verdict
VERDICT_PLACEHOLDER
"""
    (ROOT / "bench/results_gpu.md").write_text(md)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg in ("G", "H"):
        run(arg)
    elif arg == "report":
        report()
    else:
        sys.exit(__doc__)
