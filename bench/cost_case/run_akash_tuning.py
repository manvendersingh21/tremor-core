"""Tune the self-hosted 30B on the V100: same 20 coding tasks, one server config at a time, 1 or 4 calls at once.

    .venv/bin/python bench/cost_case/run_akash_tuning.py run <label> --conc 1|4 [--url URL] [--backend ollama|openai]
                     [--opts '{"num_ctx": 4096}'] [--keep-alive -1] [--no-logprobs] [--all]
    .venv/bin/python bench/cost_case/run_akash_tuning.py table

The 20 tasks are the fixed stratified subset of bench/cost_case/tasks.jsonl (5 trivial, 10 everyday, 5 hard), as in run_tiers.py.
--all runs all 301 tasks instead (the pass-rate check against the cost case).
URL defaults to $CHIMERA_GPU_URL (the local end of an SSH tunnel to your GPU box). One warm-up call loads the model; it is not timed.
Rows go to bench/.scratch/akash_tuning/<label>_c<N>.jsonl as they finish; a rerun skips finished ids and adds to the wall time.
Grading runs after generation, so the Mac's grader never counts as GPU time. Keys and hostnames are never written.
"""
from __future__ import annotations

import json
import os
import pathlib
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT / "bench" / "datasets"))
import conftest  # noqa: E402,F401

import grade  # noqa: E402
from run_bench import load_env  # noqa: E402

STORE = ROOT / "bench/.scratch" / "akash_tuning"
TASKS = pathlib.Path(__file__).parent / "tasks.jsonl"
MODEL = "qwen3:30b-instruct"
MAX_TOKENS = 1536  # same cap as run_tiers.py
PRICES = (0.52, 1.53)  # $/hr range for the V100 box


def subset(rows: list[dict], n: int = 20) -> list[dict]:
    """Fixed, stratified by difficulty (ids sorted, evenly spaced); same rule as run_tiers.subset."""
    out = []
    for d, k in (("trivial", n // 4), ("everyday", n // 2), ("hard", n - n // 4 - n // 2)):
        g = sorted(r["id"] for r in rows if r["difficulty"] == d)
        out += [g[int(i * len(g) / k)] for i in range(k)]
    return [r for r in rows if r["id"] in set(out)]


def post(url: str, path: str, body: dict, timeout: float = 600) -> dict:
    req = urllib.request.Request(url.rstrip("/") + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def call(url: str, backend: str, prompt: str, opts: dict, keep_alive, logprobs: bool) -> dict:
    """-> {text, tokens_in, tokens_out, eval_ms, prompt_ms, load_ms}. eval_ms is the server's decode time (0 if unknown)."""
    msgs = [{"role": "user", "content": prompt}]
    if backend == "ollama":
        body = {"model": MODEL, "stream": False, "think": False, "logprobs": logprobs, "messages": msgs,
                "options": {"num_predict": MAX_TOKENS, **opts}}
        if keep_alive is not None:
            body["keep_alive"] = keep_alive
        d = post(url, "/api/chat", body)
        return {"text": (d.get("message") or {}).get("content") or "", "tokens_in": d.get("prompt_eval_count", 0),
                "tokens_out": d.get("eval_count", 0), "eval_ms": round(d.get("eval_duration", 0) / 1e6),
                "prompt_ms": round(d.get("prompt_eval_duration", 0) / 1e6), "load_ms": round(d.get("load_duration", 0) / 1e6)}
    body = {"model": MODEL, "max_tokens": MAX_TOKENS, "messages": msgs, "chat_template_kwargs": {"enable_thinking": False}, **opts}
    if logprobs:
        body["logprobs"] = True
    d = post(url, "/v1/chat/completions", body)
    u, t = d.get("usage", {}), d.get("timings", {})  # timings: llama.cpp server only
    return {"text": (d["choices"][0]["message"].get("content") or "").strip(), "tokens_in": u.get("prompt_tokens", 0),
            "tokens_out": u.get("completion_tokens", 0), "eval_ms": round(t.get("predicted_ms", 0)),
            "prompt_ms": round(t.get("prompt_ms", 0)), "load_ms": 0}


def run(label: str, conc: int, url: str, backend: str, opts: dict, keep_alive, logprobs: bool, all_tasks: bool = False) -> None:
    rows = [json.loads(x) for x in TASKS.read_text().splitlines()]
    rows = rows if all_tasks else subset(rows)
    STORE.mkdir(parents=True, exist_ok=True)
    out, meta = STORE / f"{label}_c{conc}.jsonl", STORE / f"{label}_c{conc}.wall"
    done = {json.loads(x)["id"] for x in out.read_text().splitlines()} if out.exists() else set()
    todo = [r for r in rows if r["id"] not in done]
    if not todo:
        print(label, conc, "all done")
        return
    try:  # load the model; not timed
        call(url, backend, "Reply with the word ok.", opts, keep_alive, logprobs)
    except Exception as e:  # noqa: BLE001
        print("warm-up failed", type(e).__name__, flush=True)

    def one(r: dict) -> dict:
        res, err, ms = {}, "", 0.0
        for _ in range(2):  # one retry for a transient network error
            t0 = time.perf_counter()
            try:
                res, err = call(url, backend, r["prompt"], opts, keep_alive, logprobs), ""
                ms = (time.perf_counter() - t0) * 1000
                break
            except Exception as e:  # noqa: BLE001
                ms, err = (time.perf_counter() - t0) * 1000, f"{type(e).__name__}: {str(e)[:100]}"
                time.sleep(3)
        return {"id": r["id"], "difficulty": r["difficulty"], "label": label, "conc": conc, "latency_ms": round(ms),
                "answer": res.get("text", ""), "error": err, **{k: v for k, v in res.items() if k != "text"}}

    t0 = time.perf_counter()
    gen = []
    with out.open("a") as fh, ThreadPoolExecutor(conc) as ex:
        for rec in ex.map(one, todo):
            gen.append(rec)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(label, conc, rec["id"], rec["latency_ms"], rec.get("tokens_out"), rec["error"], flush=True)
    wall = time.perf_counter() - t0
    prev = float(meta.read_text()) if meta.exists() else 0.0
    meta.write_text(str(prev + wall))
    regrade(out)
    print(f"{label} c{conc}: {len(todo)} calls, wall {wall:.1f}s")


def regrade(path: pathlib.Path) -> None:
    """Add `pass` (1/0) to every row of a run file by running the code; rows already graded keep their value."""
    tasks = {r["id"]: r for r in map(json.loads, TASKS.read_text().splitlines())}
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    for r in rows:
        if "pass" not in r:
            r["pass"] = (grade.grade(tasks[r["id"]], r["answer"]) or 0) if r["answer"] else 0
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def summarize(rows: list[dict], wall_s: float, prices: tuple[float, ...] = PRICES) -> dict:
    """Per-config numbers. $ per 1,000 calls = box $/hr x wall seconds the batch held the box, scaled to 1,000 calls."""
    n = len(rows)
    lat = sorted(r["latency_ms"] / 1000 for r in rows)
    speeds = [r["tokens_out"] / (r["eval_ms"] / 1000) for r in rows if r.get("eval_ms") and r.get("tokens_out")]
    p90 = lat[min(n - 1, int(0.9 * n))] if n else 0.0
    return {
        "n": n, "pass": sum(int(r.get("pass") or 0) for r in rows),
        "p50_s": round(statistics.median(lat), 1) if n else 0.0, "p90_s": round(p90, 1),
        "decode_tok_s": round(statistics.median(speeds), 1) if speeds else 0.0,
        "tok_s_total": round(sum(r.get("tokens_out", 0) for r in rows) / wall_s, 1) if wall_s else 0.0,
        "wall_s": round(wall_s, 1),
        "usd_per_1k": [round(p * wall_s / 3600 / n * 1000, 2) if n else 0.0 for p in prices],
    }


def table() -> None:
    print("| config | conc | pass | p50 s | p90 s | decode tok/s per call | tok/s all calls | wall s | $/1k calls at $0.52 / $1.53 per hr |")
    print("|---|---|---|---|---|---|---|---|---|")
    for f in sorted(STORE.glob("*_c*.jsonl")):
        label, conc = f.stem.rsplit("_c", 1)
        rows = [json.loads(x) for x in f.read_text().splitlines()]
        w = STORE / f"{f.stem}.wall"
        s = summarize(rows, float(w.read_text()) if w.exists() else 0.0)
        print(f"| {label} | {conc} | {s['pass']}/{s['n']} | {s['p50_s']} | {s['p90_s']} | {s['decode_tok_s']} | {s['tok_s_total']} "
              f"| {s['wall_s']} | ${s['usd_per_1k'][0]} / ${s['usd_per_1k'][1]} |")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "table":
        table()
    elif len(a) >= 2 and a[0] == "run":
        load_env()

        def flag(name, default=None):
            return a[a.index(name) + 1] if name in a else default
        ka = flag("--keep-alive")
        run(a[1], int(flag("--conc", "1")), flag("--url") or os.environ["CHIMERA_GPU_URL"], flag("--backend", "ollama"),
            json.loads(flag("--opts", "{}")), int(ka) if ka and ka.lstrip("-").isdigit() else ka, "--no-logprobs" not in a,
            "--all" in a)
    else:
        print(__doc__)
