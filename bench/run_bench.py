"""Benchmark: A = every prompt to Crusoe, B = SpeculativeCascadeRouter (local Qwen + caches + Crusoe).

Run from repo root, with llama-server up on 127.0.0.1:8080 and CRUSOE_API_KEY in .env:
    .venv/bin/python bench/run_bench.py
Writes bench/results.csv, bench/raw.json (answers + scores), bench/summary.json.
The API key is read from the environment only and is never written anywhere.
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import random
import re
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import conftest  # noqa: E402,F401  (exposes chimera_core)

from chimera_core import RouterConfig, SpeculativeCascadeRouter  # noqa: E402
from chimera_core.cache.semantic_cache import OnnxMiniLMEmbedder, SemanticCache  # noqa: E402
from chimera_core.inference.cloud_verifier import CloudVerifier, CrusoeBackend  # noqa: E402
from chimera_core.inference.local_draft import LlamaCppBackend  # noqa: E402

PRICE_IN, PRICE_CACHED, PRICE_OUT = 0.25, 0.15, 2.00  # USD per 1M tokens, Crusoe list price
MAX_CLOUD = 2500


def load_env() -> None:
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def dollars(u: dict) -> float:
    fresh = u["prompt_tokens"] - u["cached_tokens"]
    return (fresh * PRICE_IN + u["cached_tokens"] * PRICE_CACHED + u["completion_tokens"] * PRICE_OUT) / 1e6


def code_of(text: str) -> str:
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.S)
    return m.group(1) if m else text


def run_tests(answer: str, tests: str) -> bool:
    with tempfile.TemporaryDirectory(dir=os.environ.get("KIROCREW_SCRATCH")) as d:
        p = pathlib.Path(d) / "t.py"
        p.write_text(code_of(answer) + "\n\n" + tests + "\n")
        try:
            return subprocess.run([sys.executable, str(p)], capture_output=True, timeout=10).returncode == 0
        except subprocess.TimeoutExpired:
            return False


def main() -> None:
    load_env()
    prompts = [json.loads(x) for x in (ROOT / "bench/prompts.jsonl").read_text().splitlines() if x.strip()]
    cloud_a = CrusoeBackend()
    cloud_b = CrusoeBackend()
    local = LlamaCppBackend()
    local.complete("hello", 4)  # warm the local model

    # ---- A: cloud only ----
    rows: list[dict] = []
    raw: dict[str, dict] = {}
    for p in prompts:
        t0 = time.perf_counter()
        text = cloud_a.complete(p["prompt"], MAX_CLOUD)
        ms = (time.perf_counter() - t0) * 1000
        u = cloud_a.last_usage
        rows.append({"mode": "A", "id": p["id"], "cat": p["cat"], "tier": "cloud", "latency_ms": round(ms),
                     "local_tokens": 0, "cloud_prompt_tokens": u["prompt_tokens"],
                     "cloud_completion_tokens": u["completion_tokens"], "cloud_cached_tokens": u["cached_tokens"],
                     "usd": round(dollars(u), 6)})
        raw[f"A:{p['id']}"] = {"answer": text}
        print("A", p["id"], round(ms), u, flush=True)

    # ---- B: cascade ----
    sem = SemanticCache(OnnxMiniLMEmbedder())
    sem._embedder.embed("warm up")
    router = SpeculativeCascadeRouter(
        local=local, cloud=CloudVerifier(cloud_b), semantic=sem,
        config=RouterConfig(max_cloud_tokens=MAX_CLOUD),
    )
    for p in prompts:
        n0 = len(cloud_b.usage_log)
        res = router.generate(p["prompt"])
        t = res.telemetry
        u = cloud_b.usage_log[-1] if len(cloud_b.usage_log) > n0 else {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
        rows.append({"mode": "B", "id": p["id"], "cat": p["cat"], "tier": t.tier_used,
                     "latency_ms": round(t.latency_ms), "local_tokens": t.local_tokens,
                     "cloud_prompt_tokens": u["prompt_tokens"], "cloud_completion_tokens": u["completion_tokens"],
                     "cloud_cached_tokens": u["cached_tokens"], "usd": round(dollars(u), 6)})
        raw[f"B:{p['id']}"] = {"answer": res.text}
        print("B", p["id"], t.tier_used, round(t.latency_ms), u, flush=True)

    # ---- quality ----
    by_id = {p["id"]: p for p in prompts}
    scores: dict[str, dict] = {}
    rng = random.Random(7)
    grade_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    grader = CrusoeBackend()
    for pid, p in by_id.items():
        s: dict = {}
        for mode in "AB":
            ans = raw[f"{mode}:{pid}"]["answer"]
            if "expect" in p:
                s[mode] = int(any(e in ans.lower() for e in p["expect"]))
            elif "tests" in p:
                s[mode] = int(run_tests(ans, p["tests"]))
        if p["cat"] == "code_heavy":
            order = ["A", "B"]
            rng.shuffle(order)  # blind: grader sees "Answer 1/2" only
            a1, a2 = (raw[f"{m}:{pid}"]["answer"] for m in order)
            q = (f"Task:\n{p['prompt']}\n\nGrade two answers for correctness, completeness and clarity, "
                 f"each 1-5 (5 best). Reply with ONLY JSON like {{\"answer1\": 3, \"answer2\": 4}}.\n\n"
                 f"### Answer 1\n{a1}\n\n### Answer 2\n{a2}")
            out = grader.complete(q, 4000)
            m = re.search(r"\{[^{}]*\}", out)
            try:
                g = json.loads(m.group(0))
                s[order[0]], s[order[1]] = int(g["answer1"]), int(g["answer2"])
            except Exception:
                s["grade_error"] = out[-200:]
        scores[pid] = s
        print("Q", pid, s, flush=True)
    grade_usage = {k: sum(u[k] for u in grader.usage_log) for k in ("prompt_tokens", "completion_tokens")}

    # ---- outputs ----
    with open(ROOT / "bench/results.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) + ["quality"])
        w.writeheader()
        for r in rows:
            r["quality"] = scores[r["id"]].get(r["mode"], "")
            w.writerow(r)
    (ROOT / "bench/raw.json").write_text(json.dumps({"answers": raw, "scores": scores}, indent=1))

    def agg(mode: str) -> dict:
        rs = [r for r in rows if r["mode"] == mode]
        lat = sorted(r["latency_ms"] for r in rs)
        return {"calls_to_cloud": sum(1 for r in rs if r["cloud_prompt_tokens"]),
                "cloud_prompt_tokens": sum(r["cloud_prompt_tokens"] for r in rs),
                "cloud_completion_tokens": sum(r["cloud_completion_tokens"] for r in rs),
                "cloud_cached_tokens": sum(r["cloud_cached_tokens"] for r in rs),
                "usd": round(sum(r["usd"] for r in rs), 5),
                "median_ms": statistics.median(lat), "p90_ms": lat[min(len(lat) - 1, int(0.9 * len(lat)))],
                "total_ms": sum(lat)}
    tiers: dict[str, int] = {}
    for r in rows:
        if r["mode"] == "B":
            tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
    summary = {"A": agg("A"), "B": agg("B"), "B_tiers": tiers, "grader_usage": grade_usage}
    (ROOT / "bench/summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
