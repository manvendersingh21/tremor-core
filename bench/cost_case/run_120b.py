"""Run the 301 cost-case tasks on openai/gpt-oss-120b (vLLM on a Daytona H100 sandbox), at a chosen concurrency.

    .venv/bin/python bench/cost_case/run_120b.py gen <concurrency> [--limit N]   # CHIMERA_120B_URL, CHIMERA_120B_KEY in .env
    .venv/bin/python bench/cost_case/run_120b.py grade <concurrency>

Same prompts, max_tokens 1536, grader and row format as run_h200.py; reasoning effort low (the tier's setting). gen writes
bench/.scratch/daytona/cost_case/gen_c<N>.jsonl, one row per task, resumable; wall_s is the sum over resumed sessions.
tokens_out counts reasoning plus answer tokens (what the GPU computed). Keys and the URL are never printed.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "bench"), str(ROOT / "bench" / "datasets")]
import conftest  # noqa: E402,F401

import grade  # noqa: E402
from chimera_core.config import load_env  # noqa: E402

STORE = ROOT / "bench/.scratch" / "daytona" / "cost_case"
TASKS = pathlib.Path(__file__).parent / "tasks.jsonl"
MODEL = "openai/gpt-oss-120b"
MAX_TOKENS = 1536


def call(url: str, key: str, prompt: str) -> dict:
    body = {"model": MODEL, "max_tokens": MAX_TOKENS, "messages": [{"role": "user", "content": prompt}],
            "reasoning_effort": "low"}
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310 (configured URL)
        return json.load(r)


def gen(conc: int, limit: int | None) -> None:
    load_env()
    url, key = os.environ["CHIMERA_120B_URL"], os.environ["CHIMERA_120B_KEY"]
    rows = [json.loads(x) for x in TASKS.read_text().splitlines()][:limit]
    STORE.mkdir(parents=True, exist_ok=True)
    out, meta = STORE / f"gen_c{conc}.jsonl", STORE / f"gen_c{conc}.wall"
    done = {json.loads(x)["id"] for x in out.read_text().splitlines()} if out.exists() else set()
    todo = [r for r in rows if r["id"] not in done]

    def one(r: dict) -> dict:
        err, text, u, ms = "", "", {}, 0.0
        for _ in range(2):
            t0 = time.perf_counter()
            try:
                d = call(url, key, r["prompt"])
                ms, err = (time.perf_counter() - t0) * 1000, ""
                text, u = (d["choices"][0]["message"].get("content") or "").strip(), d.get("usage", {})
                break
            except Exception as e:  # noqa: BLE001
                ms, err = (time.perf_counter() - t0) * 1000, f"{type(e).__name__}: {str(e)[:100]}"
                time.sleep(3)
        return {"id": r["id"], "difficulty": r["difficulty"], "concurrency": conc, "tokens_in": u.get("prompt_tokens", 0),
                "tokens_out": u.get("completion_tokens", 0),
                "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0,
                "latency_ms": round(ms), "answer": text, "error": err}

    t0 = time.perf_counter()
    with out.open("a") as fh, ThreadPoolExecutor(conc) as ex:
        for rec in ex.map(one, todo):
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(conc, rec["id"], rec["latency_ms"], rec["tokens_out"], rec["error"], flush=True)
    wall = time.perf_counter() - t0
    prev = float(meta.read_text()) if meta.exists() else 0.0
    meta.write_text(str(prev + wall))
    print(f"c{conc}: {len(todo)} calls, wall {wall:.1f}s (total {prev + wall:.1f}s)")


def do_grade(conc: int) -> None:
    tasks = {r["id"]: r for r in map(json.loads, TASKS.read_text().splitlines())}
    src, dst = STORE / f"gen_c{conc}.jsonl", STORE / f"graded_c{conc}.jsonl"
    done = {json.loads(x)["id"] for x in dst.read_text().splitlines()} if dst.exists() else set()
    with dst.open("a") as fh:
        for x in src.read_text().splitlines():
            r = json.loads(x)
            if r["id"] in done:
                continue
            r["pass"] = grade.grade(tasks[r["id"]], r["answer"]) if r["answer"] else 0
            fh.write(json.dumps(r) + "\n")
    print("graded", conc)


if __name__ == "__main__":
    lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    (gen(int(sys.argv[2]), lim) if sys.argv[1] == "gen" else do_grade(int(sys.argv[2])))
