"""Collect paired outcomes for router training: for every auto-graded suite prompt, run the Mac 3B and the top model.

    .venv/bin/python bench/run_research_collect.py local | top

Writes bench/research_data_<which>.jsonl (one row per prompt, resumable). Needs llama-server on :8080 (local)
or CRUSOE_API_KEY in .env (top). The key is never written. Dolly (LLM-judged) and QQP (cache pairs) are skipped.
"""
from __future__ import annotations

import json
import math
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "bench"), str(ROOT / "bench" / "datasets")]
import conftest  # noqa: E402,F401

import grade  # noqa: E402
from chimera_core.inference.local_draft import LlamaCppBackend  # noqa: E402
from chimera_core.ladder import TopBackend  # noqa: E402
from run_bench import load_env  # noqa: E402

SUITE = ROOT / "bench/datasets/suite.jsonl"
TOP_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"
PRICE = (0.29, 1.20)  # $/M in, out (Crusoe list)


def rows() -> list[dict]:
    return [r for r in map(json.loads, SUITE.read_text().splitlines()) if r["grader"] in ("unit_test", "exact", "choice")]


def one_local(be: LlamaCppBackend, row: dict) -> dict:
    t = time.perf_counter()
    d = be.complete(row["prompt"], 512)
    probs = [math.exp(x) for x in d.logprobs] or [0.0]
    return {"id": row["id"], "answer": d.text, "n_tokens": d.n_tokens, "mean_conf": d.mean_confidence,
            "min_prob": min(probs), "first_conf": probs[0], "entropy": d.mean_entropy,
            "latency_ms": round((time.perf_counter() - t) * 1000), "grade": grade.grade(row, d.text)}


def one_top(be: TopBackend, row: dict) -> dict:
    t = time.perf_counter()
    text = be.complete(row["prompt"], 1500)
    u = be.last_usage
    return {"id": row["id"], "answer": text, "tokens_in": u["prompt_tokens"], "tokens_out": u["completion_tokens"],
            "usd": (u["prompt_tokens"] * PRICE[0] + u["completion_tokens"] * PRICE[1]) / 1e6,
            "latency_ms": round((time.perf_counter() - t) * 1000), "grade": grade.grade(row, text)}


def main(which: str) -> None:
    load_env()
    out = ROOT / f"bench/research_data_{which}.jsonl"
    done = {json.loads(x)["id"] for x in out.read_text().splitlines()} if out.exists() else set()
    todo = [r for r in rows() if r["id"] not in done]
    if which == "local":
        be = LlamaCppBackend()
        be.complete("hello", 4)  # warm-up, not recorded
        with out.open("a") as fh:
            for r in todo:
                rec = one_local(be, r)
                fh.write(json.dumps(rec) + "\n"); fh.flush()
                print("local", r["id"], rec["grade"], round(rec["mean_conf"], 2), flush=True)
    else:
        def work(r):
            be = TopBackend(TOP_MODEL, {"thinking": False}, timeout=240)  # own backend per call: usage_log is not thread safe
            return one_top(be, r)
        with out.open("a") as fh, ThreadPoolExecutor(4) as ex:
            for rec in ex.map(work, todo):
                fh.write(json.dumps(rec) + "\n"); fh.flush()
                print("top", rec["id"], rec["grade"], flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
