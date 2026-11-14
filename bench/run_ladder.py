"""Ladder benchmark: T = all to the top model, L = caches->Mac 3B->GPU 30B->top, Lnb = L without brief
(heavy prompts only), L4 = L with the largest Crusoe model as top.

Needs: llama-server on 127.0.0.1:8080, ssh tunnel to the GPU Ollama on 127.0.0.1:11436, CRUSOE_API_KEY in .env.
    .venv/bin/python bench/run_ladder.py T | L | Lnb | L4 | report
Per-mode rows are kept as ladder_<mode>.json in $KIROCREW_SCRATCH. The API key is never written anywhere.
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import random
import re
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))
import conftest  # noqa: E402,F401

from chimera_core.cache.semantic_cache import OnnxMiniLMEmbedder, SemanticCache  # noqa: E402
from chimera_core.inference.cloud_verifier import OllamaBackend  # noqa: E402
from chimera_core.inference.local_draft import LlamaCppBackend  # noqa: E402
from chimera_core.ladder import LadderConfig, LadderRouter, TopBackend  # noqa: E402
from run_bench import load_env, run_tests  # noqa: E402

STORE = pathlib.Path(os.environ.get("KIROCREW_SCRATCH") or ROOT / "bench")
# model -> (chat_template_kwargs, $/M input, $/M cached input, $/M output, params). Source: Crusoe /v1/models.
TOPS = {
    "T": "openai/gpt-oss-120b", "L": "openai/gpt-oss-120b", "Lnb": "openai/gpt-oss-120b",
    "L4": "deepseek-ai/DeepSeek-V4.1-Flash",
}
MODELS = {
    "openai/gpt-oss-120b": ({"reasoning_effort": "low"}, 0.05, 0.05, 0.25, "120.4B"),
    "deepseek-ai/DeepSeek-V4.1-Flash": ({"thinking": False}, 0.29, 0.007, 1.20, "763.2B"),
}
GRADER = "Qwen/Qwen3.8-27B"  # wrote none of the graded answers
PRICE_GRADER = (0.25, 0.15, 2.00)


def usd(model: str, u: dict) -> float:
    _, pin, pc, pout, _ = MODELS[model]
    return ((u["prompt_tokens"] - u["cached_tokens"]) * pin + u["cached_tokens"] * pc
            + u["completion_tokens"] * pout) / 1e6


def quality(p: dict, ans: str):
    if "expect" in p:
        return int(any(e in ans.lower() for e in p["expect"]))
    if "tests" in p:
        return int(run_tests(ans, p["tests"]))
    return ""


def run(mode: str) -> None:
    load_env()
    prompts = [json.loads(x) for x in (ROOT / "bench/prompts.jsonl").read_text().splitlines() if x.strip()]
    if mode == "Lnb":
        prompts = [p for p in prompts if p["cat"] == "code_heavy"]
    model = TOPS[mode]
    top = TopBackend(model, MODELS[model][0])
    mid = OllamaBackend(base_url="http://127.0.0.1:11436")
    if mode != "T":
        mid.complete("hello", 4)  # load the model; not timed
        mid.usage_log.clear()
    rows, answers = [], {}
    if mode == "T":
        router = None
    else:
        local = LlamaCppBackend()
        local.complete("hello", 4)
        sem = SemanticCache(OnnxMiniLMEmbedder())
        sem._embedder.embed("warm up")
        router = LadderRouter(local, mid, top, LadderConfig(use_brief=mode != "Lnb"), semantic=sem)
    for p in prompts:
        n_top, n_mid = len(top.usage_log), len(mid.usage_log)
        t0 = time.perf_counter()
        if router is None:
            text, tier = top.complete(p["prompt"], 2500), "top"
        else:
            check = (lambda a, p=p: bool(quality(p, a))) if "tests" in p else None
            res = router.generate(p["prompt"], check=check)
            text, tier = res.text, res.telemetry.tier_used
        ms = (time.perf_counter() - t0) * 1000
        tu, mu = top.usage_log[n_top:], mid.usage_log[n_mid:]
        row = {"mode": mode, "id": p["id"], "cat": p["cat"], "tier": tier, "latency_ms": round(ms),
               "top_prompt_tokens": sum(u["prompt_tokens"] for u in tu),
               "top_completion_tokens": sum(u["completion_tokens"] for u in tu),
               "top_cached_tokens": sum(u["cached_tokens"] for u in tu),
               "top_usd": round(sum(usd(model, u) for u in tu), 7),
               "gpu_prompt_tokens": sum(u["prompt_tokens"] for u in mu),
               "gpu_completion_tokens": sum(u["completion_tokens"] for u in mu),
               "quality": quality(p, text)}
        rows.append(row)
        answers[p["id"]] = text
        print(mode, p["id"], tier, round(ms), row["top_prompt_tokens"], row["top_completion_tokens"], flush=True)
    (STORE / f"ladder_{mode}.json").write_text(json.dumps({"rows": rows, "answers": answers}, indent=1))


def grade_heavy(modes: list[str], prompts: dict) -> dict:
    """Blind 1-5 grade of heavy-code answers. One grader call per prompt; answers shuffled and unlabeled."""
    from chimera_core.inference.cloud_verifier import CrusoeBackend
    path = STORE / "ladder_grades.json"
    if path.exists():
        return json.loads(path.read_text())
    data = {m: json.loads((STORE / f"ladder_{m}.json").read_text())["answers"] for m in modes}
    g = CrusoeBackend(model=GRADER)
    rng, out = random.Random(11), {}
    for pid, p in prompts.items():
        if p["cat"] != "code_heavy":
            continue
        have = [m for m in modes if pid in data[m]]
        rng.shuffle(have)
        body = "\n\n".join(f"### Answer {i + 1}\n{data[m][pid]}" for i, m in enumerate(have))
        q = (f"Task:\n{p['prompt']}\n\nGrade each answer for correctness, completeness and clarity, 1-5 (5 best). "
             f"Reply with ONLY JSON like {{\"1\": 3, \"2\": 4}}.\n\n{body}")
        txt = g.complete(q, 1500)
        try:
            j = json.loads(re.search(r"\{[^{}]*\}", txt).group(0))
            out[pid] = {m: int(j[str(i + 1)]) for i, m in enumerate(have)}
        except Exception:
            out[pid] = {"error": txt[-200:]}
        print("G", pid, out[pid], flush=True)
    path.write_text(json.dumps({"grades": out, "usage": g.usage_log}))
    return {"grades": out, "usage": g.usage_log}


def pct(x: list[float], q: float) -> float:
    x = sorted(x)
    return x[min(len(x) - 1, int(q * len(x)))]


def report() -> None:
    prompts = {p["id"]: p for p in (json.loads(x) for x in (ROOT / "bench/prompts.jsonl").read_text().splitlines() if x.strip())}
    modes = [m for m in ("T", "L", "Lnb", "L4") if (STORE / f"ladder_{m}.json").exists()]
    rows = {m: json.loads((STORE / f"ladder_{m}.json").read_text())["rows"] for m in modes}
    gr = grade_heavy(modes, prompts)
    grades = gr["grades"]
    with open(ROOT / "bench/results_ladder.csv", "w", newline="") as fh:
        keys = list(rows[modes[0]][0]) + ["heavy_grade"]
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for m in modes:
            for r in rows[m]:
                r = dict(r, heavy_grade=grades.get(r["id"], {}).get(m, ""))
                w.writerow(r)

    def agg(m: str) -> dict:
        rs = rows[m]
        lat = [r["latency_ms"] for r in rs]
        tt = sum(r["top_prompt_tokens"] + r["top_completion_tokens"] for r in rs)
        return {"n": len(rs), "top_tokens": tt, "top_in": sum(r["top_prompt_tokens"] for r in rs),
                "top_out": sum(r["top_completion_tokens"] for r in rs),
                "usd": sum(r["top_usd"] for r in rs), "med": statistics.median(lat), "p90": pct(lat, 0.9),
                "gpu_tok": sum(r["gpu_prompt_tokens"] + r["gpu_completion_tokens"] for r in rs),
                "top_calls": sum(1 for r in rs if r["top_prompt_tokens"])}
    A = {m: agg(m) for m in modes}
    out = ["| mode | top calls | top tokens (in/out) | top $ | median ms | p90 ms | GPU tokens |", "|---|---|---|---|---|---|---|"]
    for m in modes:
        a = A[m]
        out.append(f"| {m} | {a['top_calls']}/{a['n']} | {a['top_tokens']} ({a['top_in']}/{a['top_out']}) | "
                   f"${a['usd']:.5f} | {a['med']:.0f} | {a['p90']:.0f} | {a['gpu_tok']} |")
    table = "\n".join(out)
    t, l = A["T"], A["L"]
    sav = f"L vs T: top tokens saved {t['top_tokens'] - l['top_tokens']} ({100 * (1 - l['top_tokens'] / t['top_tokens']):.1f}%), " \
          f"top $ saved ${t['usd'] - l['usd']:.5f} ({100 * (1 - l['usd'] / t['usd']):.1f}%)."
    tiers = {}
    for r in rows["L"]:
        tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
    tiers4 = {}
    for r in rows.get("L4", []):
        tiers4[r["tier"]] = tiers4.get(r["tier"], 0) + 1
    cats = sorted({r["cat"] for r in rows["T"]})
    qt = ["| type | " + " | ".join(f"{m} pass" for m in modes if m != "Lnb") + " |", "|---|" + "---|" * len([m for m in modes if m != "Lnb"])]
    for c in cats:
        if c == "code_heavy":
            continue
        cells = []
        for m in modes:
            if m == "Lnb":
                continue
            rs = [r for r in rows[m] if r["cat"] == c]
            cells.append(f"{sum(r['quality'] for r in rs)}/{len(rs)}")
        qt.append(f"| {c} | " + " | ".join(cells) + " |")
    hv = ["| prompt | " + " | ".join(modes) + " |", "|---|" + "---|" * len(modes)]
    heavy_ids = [p for p in prompts if prompts[p]["cat"] == "code_heavy"]
    sums = {m: [] for m in modes}
    for pid in heavy_ids:
        cells = []
        for m in modes:
            v = grades.get(pid, {}).get(m, "")
            cells.append(str(v))
            if v != "":
                sums[m].append(v)
        hv.append(f"| {pid} | " + " | ".join(cells) + " |")
    hv.append("| mean | " + " | ".join(f"{statistics.mean(sums[m]):.2f}" if sums[m] else "" for m in modes) + " |")
    # brief vs no-brief on heavy prompts: compare L and Lnb restricted to those prompts that reached the top
    hb = {}
    for m in ("L", "Lnb"):
        if m in rows:
            rs = [r for r in rows[m] if r["cat"] == "code_heavy"]
            hb[m] = (sum(r["top_prompt_tokens"] for r in rs), sum(r["top_completion_tokens"] for r in rs),
                     sum(r["latency_ms"] for r in rs), sum(r["top_usd"] for r in rs))
    bn = ["| heavy prompts (6) | top in | top out | total latency ms | top $ |", "|---|---|---|---|---|"]
    for m, v in hb.items():
        bn.append(f"| {'brief by 30B' if m == 'L' else 'no brief'} | {v[0]} | {v[1]} | {v[2]} | ${v[3]:.5f} |")
    gu = gr.get("usage", [])
    gcost = sum((u["prompt_tokens"] - u["cached_tokens"]) * PRICE_GRADER[0] + u["cached_tokens"] * PRICE_GRADER[1]
                + u["completion_tokens"] * PRICE_GRADER[2] for u in gu) / 1e6
    total_top = sum(A[m]["top_tokens"] for m in modes) + sum(u["prompt_tokens"] + u["completion_tokens"] for u in gu)
    md = f"""# Ladder benchmark: Mac 3B -> GPU Qwen3-30B -> Crusoe top model

30 prompts from `bench/prompts.jsonl`, one pass per mode. Real counts come from each server's usage field.

## Setup
| tier | model | size | price (per M tokens) |
|---|---|---|---|
| caches | exact SHA-256 + semantic MiniLM (cos >= 0.94) | - | free |
| 1 | Mac Qwen2.5-3B-Instruct Q4, llama.cpp, logprob gate 0.85 | 3B | free (own Mac) |
| 2 | GPU Ollama `qwen3:30b-instruct` (Q4_K_M, already running; `think:false`) | 30.5B (MoE) | free (own server) |
| 3 | Crusoe `openai/gpt-oss-120b` (`reasoning_effort: low`) | 120.4B (published in /v1/models) | $0.05 in / $0.05 cached / $0.25 out |
| 4 (opt.) | Crusoe `deepseek-ai/DeepSeek-V4.1-Flash` (`thinking: false`) | 763.2B | $0.29 in / $0.007 cached / $1.20 out |
| grader | Crusoe `Qwen/Qwen3.8-27B` (wrote no graded answer) | 27.8B | $0.25 / $0.15 / $2.00 |

Largest model on the key: DeepSeek-V4.1-Flash at 763.2B. No ~1T model is listed. Next: GLM-5.3 at 753.3B ($1.40 in / $4.40 out), GLM-5.3-Flash 321.3B, Nemotron-3.5-Super-VL 124.5B. Sizes are Crusoe's `parameter_count`; the MoE active size is not given except Nemotron (12B active).
Tunnel: GPU Ollama via an SSH tunnel to your GPU box.

Climb rules: 3B stays if mean token prob >= 0.85 (and asserts pass, when the prompt has them). Else the 30B answers. The 30B answer goes up if its self-check says ESCALATE or the asserts fail. Prompts with `complexity_score >= 0.6` skip both small answers: the 30B writes a brief of at most 200 tokens and the top model answers.

## T (top only) vs L (ladder)
{table}

{sav}
L4 uses {models_name('L4')} as top; its $ is not comparable to T (different price).
GPU/Mac tokens are not priced (own hardware). Grader used {gcost:.5f} $ and {sum(u['prompt_tokens'] + u['completion_tokens'] for u in gu)} tokens; total Crusoe tokens this benchmark: {total_top}.

## Which tier answered (L)
{tiers}
L4: {tiers4}

## Quality
Pass counts (asserts for code_small, keyword match for the rest):

{chr(10).join(qt)}

Heavy code, blind 1-5 grade by {GRADER}, answers shuffled per prompt:

{chr(10).join(hv)}

## Brief vs no brief (heavy prompts)
{chr(10).join(bn)}

## Verdict
__VERDICT__

## Rerun
```
bench/serve_local.sh &        # Mac 3B on 127.0.0.1:8080
ssh -N -f -L 127.0.0.1:<port>:127.0.0.1:11434 <gpu-host>   # an SSH tunnel to your GPU box
.venv/bin/python bench/run_ladder.py T && .venv/bin/python bench/run_ladder.py L
.venv/bin/python bench/run_ladder.py Lnb && .venv/bin/python bench/run_ladder.py L4
.venv/bin/python bench/run_ladder.py report   # delete $KIROCREW_SCRATCH/ladder_grades.json to regrade
```
Raw rows: `bench/results_ladder.csv`.
"""
    (ROOT / "bench/results_ladder.md").write_text(md)
    print(md)


def models_name(m: str) -> str:
    return TOPS[m]


if __name__ == "__main__":
    report() if sys.argv[1] == "report" else run(sys.argv[1])
