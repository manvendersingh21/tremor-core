"""End-to-end backend bench: the production path (config.build_router) on the real stack.

Stack (product ladder): Supabase cache (exact hash, then cosine; the only cache) -> GPU 30B (Ollama over a tunnel,
logprob gate) -> Crusoe DeepSeek-V4.1-Flash 763B. No Mac 3B. Modal H200 off.
Passes over 60 prompts (30 from prompts.jsonl, 30 from datasets/suite.jsonl):
    BASE    big model only (the 763B), no cache
    COLD    full ladder, fresh Supabase namespace, gate 0.95, guard on
    WARM    same prompts again: Supabase hits (any machine sees the same rows)
    GATE85  ladder with no cache, gate 0.85 on the 30B: the effect of the gate
    pairs   offline: labeled Quora pairs (cache_eval.jsonl) through the real embedder, guard on/off, threshold 0.97/0.94

    .venv/bin/python bench/run_backend.py run [BASE COLD WARM SECOND GATE85] | pairs | report
Rows go to bench/.scratch/backend/backend_rows.jsonl, one per item as it finishes; a rerun skips done ids.
Needs CHIMERA_GPU_URL (the local end of an SSH tunnel to your GPU box), CRUSOE_API_KEY and CHIMERA_DB_URL in .env.
No key or DSN is written anywhere.
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
sys.path.insert(0, str(ROOT / "bench" / "datasets"))
import conftest  # noqa: E402,F401

import grade  # noqa: E402
from chimera_core.cache.guard import consistent  # noqa: E402
from chimera_core.cache.semantic_cache import OnnxMiniLMEmbedder, SemanticCache  # noqa: E402
from chimera_core.config import CacheCfg, ChimeraConfig, Thresholds, build_router, load_env  # noqa: E402
from chimera_core.tiers import TierCfg  # noqa: E402

# in the repo, git-ignored: $KIROCREW_SCRATCH is lost on a gateway restart. BENCH_STORE: another run's folder
STORE = pathlib.Path(os.environ.get("BENCH_STORE") or ROOT / "bench/.scratch/backend")
STORE.mkdir(parents=True, exist_ok=True)
ROWS = STORE / "backend_rows.jsonl"
PAIRS = STORE / "backend_pairs.json"
VERDICT_FILE = ROOT / "bench/results_backend_verdict.md"  # hand-written verdict, kept across report reruns
TENANT = "bench-backend"
NS = os.environ.get("BENCH_NS", "bench-backend-run1")
TOP_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"
ORDER = ["BASE", "COLD", "WARM", "GATE85"]


def tiers(only_top: bool = False) -> list[TierCfg]:
    top = TierCfg(name="cloud-deepseek", device="cloud", backend="openai", url="https://api.inference.crusoecloud.com",
                  model=TOP_MODEL, family="deepseek", cost_per_1k_in=0.00029, cost_per_1k_out=0.0012,
                  timeout_s=120, template_kwargs={"thinking": False})
    if only_top:
        return [top]
    return [
        TierCfg(name="gpu-small", device="gpu", backend="ollama",
                url=os.environ.get("CHIMERA_GPU_URL", ""), model="qwen3:30b-instruct",
                family="qwen", max_complexity=0.6, timeout_s=90),
        top,
    ]


def make_router(mode: str):
    shared = mode in ("COLD", "WARM")
    cfg = ChimeraConfig(
        use_pool=True, tiers=tiers(only_top=mode == "BASE"),
        thresholds=Thresholds(confidence=0.85 if mode == "GATE85" else 0.95),
        cache=CacheCfg(backend="supabase", tenant=TENANT, store_text=True, guard=True),
        telemetry={"path": str(STORE / "backend_telemetry.jsonl")})
    r = build_router(cfg)
    if not shared:
        r.shared, r.embedder = None, None  # BASE and GATE85 run with no cache
    r.pool.max_tokens = 1024
    r.cfg = r.cfg.model_copy(update={"namespace": NS})
    return r


def items() -> list[dict]:
    p = [json.loads(x) for x in (ROOT / "bench/prompts.jsonl").read_text().splitlines() if x.strip()]
    out = [{"id": r["id"], "src": "prompts:" + r["cat"], "prompt": r["prompt"], "expect": r["expect"]}
           for r in p if "expect" in r]
    out += [{"id": r["id"], "src": "prompts:" + r["cat"], "prompt": r["prompt"], "expect": None}
            for r in p if "expect" not in r]  # shortcut: ungraded prompts (code_heavy) are timed, not graded
    s = [json.loads(x) for x in (ROOT / "bench/datasets/suite.jsonl").read_text().splitlines()]
    pick = [("mmlu", None, 10), ("gsm8k", None, 10), ("humaneval", "code", 5), ("mbpp", None, 5)]
    for src, typ, n in pick:
        out += [{"id": r["id"], "src": src, "prompt": r["prompt"], "expect": None, "row": r}
                for r in [x for x in s if x["source"] == src and (typ is None or x["type"] == typ)][:n]]
    return out


def grade_item(it: dict, text: str) -> int | None:
    if it.get("expect"):
        return int(any(e in text.lower() for e in it["expect"]))
    if it.get("row") and it["row"]["grader"] in ("choice", "exact", "unit_test"):
        return grade.grade(it["row"], text)
    return None


def done_ids(mode: str) -> set[str]:
    if not ROWS.exists():
        return set()
    return {r["id"] for r in map(json.loads, ROWS.read_text().splitlines()) if r["pass"] == mode}


def one(r, it: dict, mode: str) -> dict:
    t0 = time.perf_counter()
    err, text, tel = "", "", None
    try:
        check = (lambda a: bool(grade_item(it, a))) if it.get("row") and it["row"]["grader"] == "unit_test" else None
        res = r.generate(it["prompt"], check=check)  # unit tests decide what is cached
        text, tel = res.text, res.telemetry
    except Exception as e:  # noqa: BLE001  AllTiersFailed or a tier error that escaped
        err = type(e).__name__
    ms = (time.perf_counter() - t0) * 1000
    ev = {e["step"]: e for e in (tel.events if tel else [])}
    per = {k: v.model_dump() for k, v in (tel.per_tier or {}).items()} if tel else {}
    big = per.get("crusoe", {})
    path = "failed" if tel is None else (f"cache:{tel.cache_source}" if tel.cache_source else tel.tier_name or tel.tier_used)
    return {
        "pass": mode, "id": it["id"], "src": it["src"], "path": path, "latency_ms": round(ms, 1),
        "grade": grade_item(it, text) if text else (0 if it.get("expect") or it.get("row") else None),
        "tier_used": tel.tier_used if tel else "failed", "cache_source": tel.cache_source if tel else None,
        "big_in": big.get("input_tokens", 0), "big_out": big.get("output_tokens", 0),
        "dollars": tel.dollars_spent or 0.0 if tel else 0.0, "kept_off_big": tel.tokens_saved if tel else 0,
        "dollars_saved_est": tel.dollars_saved if tel else 0.0,
        "gpu_call": int(any(e["step"] == "call" and e.get("tier") == "gpu-small" for e in (tel.events if tel else []))),
        "gpu_in": per.get("gpu_small", {}).get("input_tokens", 0), "gpu_out": per.get("gpu_small", {}).get("output_tokens", 0),
        "memory_stored": any(e["step"] == "memory" and e.get("stored") for e in (tel.events if tel else [])),
        "draft_conf": ev.get("draft", {}).get("confidence"),
        "local_score": ev.get("cache_local", {}).get("score"), "local_guard": ev.get("cache_local", {}).get("guard"),
        "shared_status": ev.get("cache_shared", {}).get("status"), "shared_ms": ev.get("cache_shared", {}).get("ms"),
        "shared_score": ev.get("cache_shared", {}).get("score"), "shared_guard": ev.get("cache_shared", {}).get("guard"),
        "error": err,
    }


def run(modes: list[str]) -> None:
    load_env()
    its = items()
    print(f"{len(its)} prompts, namespace {NS}", flush=True)
    routers: dict[str, object] = {}
    for mode in modes:
        todo = [i for i in its if i["id"] not in done_ids(mode)]
        r = routers["COLD"] if mode == "WARM" else make_router(mode)
        routers[mode] = r
        if mode in ("BASE", "COLD", "GATE85") and r.pool:  # load models; not timed, not cached
            for t in r.pool.tiers:
                if t.device != "cloud":
                    try:
                        r.pool._factory(t).complete("hello", 4)
                    except Exception as e:  # noqa: BLE001
                        print("warm-up failed", t.name, type(e).__name__, flush=True)
        with ROWS.open("a") as fh:
            for it in todo:
                row = one(r, it, mode)
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                print(mode, row["id"], row["path"], round(row["latency_ms"]), row["grade"], row["error"], flush=True)
        if getattr(r, "shared", None) is not None:
            r.shared.flush()


# ---------------------------------------------------------------- offline pairs ----
def pairs() -> None:
    """Labeled Quora pairs (bench/datasets/cache_eval.jsonl), real embedder: hits and wrong hits by threshold and guard."""
    rows = [json.loads(x) for x in (ROOT / "bench/datasets/cache_eval.jsonl").read_text().splitlines()]
    by: dict[int, dict] = {}
    for r in rows:
        by.setdefault(r["pair"], {})[r["role"]] = r
    ab = [(v["a"], v["b"]) for v in by.values() if "a" in v and "b" in v]
    emb = OnnxMiniLMEmbedder()
    sims = []
    for a, b in ab:
        va, vb = emb.embed(a["text"]), emb.embed(b["text"])
        sims.append(sum(x * y for x, y in zip(va, vb)))  # embedder output is unit length
    out = {"n_pairs": len(ab), "n_dup": sum(a["pair_dup"] for a, _ in ab), "cells": {}}
    for thr in (0.97, 0.94):
        for guard in (False, True):
            hits = wrong = right = 0
            for (a, b), sim in zip(ab, sims):
                if sim >= thr and (not guard or consistent(b["text"], a["text"])):
                    hits += 1
                    wrong += not a["pair_dup"]
                    right += bool(a["pair_dup"])
            out["cells"][f"thr{thr}_guard{'on' if guard else 'off'}"] = {"hits": hits, "right": right, "wrong": wrong}
    PAIRS.write_text(json.dumps(out, indent=1))
    print(json.dumps(out), flush=True)


# ---------------------------------------------------------------- report ----
def pct(x: list[float], q: float) -> float:
    x = sorted(x)
    return x[min(len(x) - 1, int(q * len(x)))] if x else 0.0


def load() -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {m: [] for m in ORDER}
    for r in map(json.loads, ROWS.read_text().splitlines()):
        by[r["pass"]].append(r)
    return by


def acc(rows: list[dict]) -> str:
    g = [r["grade"] for r in rows if r["grade"] is not None]
    return f"{sum(g)}/{len(g)}" if g else "n/a"


def report() -> None:
    import backend_report  # noqa: PLC0415  (kept apart: it imports this module)
    backend_report.report(VERDICT_FILE.read_text() if VERDICT_FILE.exists() else "")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    {"run": lambda: run(sys.argv[2:] or ORDER), "pairs": pairs, "report": report}[cmd]()
