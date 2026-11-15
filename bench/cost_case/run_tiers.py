"""Run every task in tasks.jsonl on ONE tier (thinking off) and grade it by running the code.

    .venv/bin/python bench/cost_case/run_tiers.py mac|gpu|top|gpt55|grok [--subset 60]

mac  : Qwen2.5-3B q4_k_m on llama.cpp (127.0.0.1:8080). Real output tokens and mean token probability from the server;
       real prompt tokens from the server's /tokenize on the ChatML prompt.
gpu  : Ollama qwen3:30b-instruct on a V100, via the ssh tunnel on $GPU_PORT (set it in the shell). Real counts and Ollama's own
       total_duration, so queue time (wall minus compute) is recorded apart from compute time.
top  : Crusoe deepseek-ai/DeepSeek-V4.1-Flash (763B), thinking off. CRUSOE_API_KEY from .env.
gpt55, grok : GMI openai/gpt-5.5 and x-ai/grok-4.5 on a fixed 60-item subset (stratified by difficulty). GMI_API_KEY from .env.
Rows go to $KIROCREW_SCRATCH/cost_case/raw_<tier>.jsonl as they finish; a rerun skips finished ids. Keys are never written.
Calls are sequential so latency is not inflated by this script's own concurrency.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT / "bench" / "datasets"))
import conftest  # noqa: E402,F401

import grade  # noqa: E402
from chimera_core.inference.cloud_verifier import OllamaBackend  # noqa: E402
from chimera_core.inference.local_draft import LlamaCppBackend, LlamaCppTokenizer, chatml  # noqa: E402
from chimera_core.ladder import TopBackend  # noqa: E402
from run_bench import load_env  # noqa: E402

STORE = ROOT / "bench/.scratch" / "cost_case"  # repo-local: survives restarts (never $KIROCREW_SCRATCH)
TASKS = pathlib.Path(__file__).parent / "tasks.jsonl"
MAX_TOKENS = 1536
# $ per 1M tokens (input, cached input, output). Crusoe list for the 763B; GMI /v1/models pricing for the other two.
PRICE = {"top": (0.29, 0.007, 1.20), "gpt55": (5.0, 0.5, 30.0), "grok": (2.0, 0.5, 6.0)}
MODEL = {"mac": "Qwen2.5-3B-Instruct-q4_k_m", "gpu": "qwen3:30b-instruct", "top": "deepseek-ai/DeepSeek-V4.1-Flash",
         "gpt55": "openai/gpt-5.5", "grok": "x-ai/grok-4.5"}
GMI = "https://api.gmi-serving.com"


def subset(rows: list[dict], n: int = 60) -> list[dict]:
    """Fixed, stratified by difficulty (ids sorted, evenly spaced) so every tier sees the same items."""
    out = []
    for d, k in (("trivial", n // 4), ("everyday", n // 2), ("hard", n - n // 4 - n // 2)):
        g = sorted(r["id"] for r in rows if r["difficulty"] == d)
        out += [g[int(i * len(g) / k)] for i in range(k)]
    return [r for r in rows if r["id"] in set(out)]


def make(tier: str):
    """-> call(prompt) returning (text, tokens_in, tokens_out, cached, extra dict)."""
    if tier == "mac":
        b, tok = LlamaCppBackend(timeout=300), LlamaCppTokenizer()

        def call(p):
            d = b.complete(p, MAX_TOKENS)
            return d.text, len(tok.encode(chatml(p))), d.n_tokens, 0, {"confidence": round(d.mean_confidence, 4)}
    elif tier == "gpu":
        b = OllamaBackend(base_url=f"http://127.0.0.1:{os.environ['GPU_PORT']}", timeout=300)

        def call(p):
            t = b.complete(p, MAX_TOKENS)
            u = b.last_usage
            return t, u["prompt_tokens"], u["completion_tokens"], 0, {"compute_ms": u["total_duration_ms"], "load_ms": u["load_duration_ms"]}
    else:
        if tier == "top":
            b = TopBackend(MODEL[tier], {"thinking": False}, api_key=os.environ["CRUSOE_API_KEY"],
                           base_url="https://api.inference.crusoecloud.com", timeout=300)
        else:  # GMI premium models: reasoning off through the top-level OpenAI field
            b = TopBackend(MODEL[tier], {"reasoning_effort": "none" if tier == "gpt55" else "low"},  # grok-4.5 rejects "none"; "low" is its lowest
                           api_key=os.environ["GMI_API_KEY"], base_url=GMI, timeout=300)

        def call(p):
            t = b.complete(p, MAX_TOKENS)
            u = b.last_usage
            return t, u["prompt_tokens"], u["completion_tokens"], u["cached_tokens"], {}
    return call


def run(tier: str, n_subset: int | None) -> None:
    load_env()
    rows = [json.loads(x) for x in TASKS.read_text().splitlines()]
    if tier in ("gpt55", "grok"):
        rows = subset(rows, n_subset or 60)
    STORE.mkdir(parents=True, exist_ok=True)
    out = STORE / f"raw_{tier}.jsonl"
    done = {json.loads(x)["id"] for x in out.read_text().splitlines()} if out.exists() else set()
    call = make(tier)
    if tier in ("mac", "gpu"):  # load the model; not timed
        try:
            call("Reply with the word ok.")
        except Exception as e:  # noqa: BLE001
            print("warm-up failed", type(e).__name__, flush=True)
    with out.open("a") as fh:
        for r in rows:
            if r["id"] in done:
                continue
            t0 = time.perf_counter()
            err, text, tin, tout, cached, extra = "", "", 0, 0, 0, {}
            for attempt in range(2):  # one retry for a transient network error; the failed attempt is not timed
                try:
                    t0 = time.perf_counter()
                    text, tin, tout, cached, extra = call(r["prompt"])
                    err = ""
                    break
                except Exception as e:  # noqa: BLE001
                    err = f"{type(e).__name__}: {str(e)[:120]}"
                    time.sleep(3)
            ms = (time.perf_counter() - t0) * 1000
            g = grade.grade(r, text) if text else 0
            rec = {"id": r["id"], "difficulty": r["difficulty"], "tier": tier, "model": MODEL[tier], "pass": g, "tokens_in": tin,
                   "tokens_out": tout, "cached": cached, "latency_ms": round(ms), "answer": text, "error": err, **extra}
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(tier, r["id"], g, round(ms), tin, tout, err, flush=True)


if __name__ == "__main__":
    n = int(sys.argv[sys.argv.index("--subset") + 1]) if "--subset" in sys.argv else None
    run(sys.argv[1], n)
