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
Rows go to $KIROCREW_SCRATCH/backend_rows.jsonl as they finish (a rerun skips finished passes' ids).
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

STORE = pathlib.Path(os.environ.get("KIROCREW_SCRATCH") or ROOT / "bench")
ROWS = STORE / "backend_rows.jsonl"
PAIRS = STORE / "backend_pairs.json"
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
    by = load()
    n = max(len(v) for v in by.values())
    base_in, base_out = (sum(r[k] for r in by["BASE"]) for k in ("big_in", "big_out"))
    base_usd = sum(r["dollars"] for r in by["BASE"])
    p = lambda m, k: sum(r[k] for r in by[m])  # noqa: E731
    lines = ["# Backend end to end: production path, real stack", "",
             f"{n} prompts (30 from `bench/prompts.jsonl`, 30 from `bench/datasets/suite.jsonl`: 10 MMLU, 10 GSM8K, 5 HumanEval, 5 MBPP). "
             "Single run per pass. Router: `config.build_router` with `use_pool` (the same object the gateway and `/api/chat` use). "
             "Tiers: Mac Qwen2.5-3B q4_k_m (llama.cpp), GPU Qwen3-30B (Ollama, V100 box over a tunnel), Crusoe DeepSeek-V4.1-Flash 763B as the big model. "
             "Caches: exact + local SQLite + shared Supabase (tenant role, guard on, threshold 0.97). Gate 0.95. "
             "Local tiers cost $0 here (owned hardware); dollars are Crusoe list price.", "",
             "## Per pass", "",
             "| pass | calls | big-model calls | GPU calls | cache hits (exact/local/shared) | big in+out tokens | big $ | graded correct | p50 ms | p90 ms |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for m in ORDER:
        rs = by[m]
        if not rs:
            continue
        big_calls = sum(1 for r in rs if r["big_in"] + r["big_out"] > 0)
        hits = {k: sum(r["cache_source"] == k for r in rs) for k in ("exact", "local", "shared")}
        lat = [r["latency_ms"] for r in rs]
        lines.append(f"| {m} | {len(rs)} | {big_calls} | {sum(r['gpu_call'] for r in rs)} | "
                     f"{hits['exact']}/{hits['local']}/{hits['shared']} | {p(m, 'big_in') + p(m, 'big_out')} | "
                     f"${p(m, 'dollars'):.5f} | {acc(rs)} | {pct(lat, .5):.0f} | {pct(lat, .9):.0f} |")
    cold, warm, second = by["COLD"], by["WARM"], by["SECOND"]
    if cold and by["BASE"]:
        c_tok = p("COLD", "big_in") + p("COLD", "big_out")
        lines += ["", "## Against the big-model-only baseline (BASE)", "",
                  "| | BASE | COLD | WARM | SECOND |", "|---|---|---|---|---|"]
        for lab, fn in (("big tokens", lambda m: p(m, "big_in") + p(m, "big_out") if by[m] else None),
                        ("big $", lambda m: f"${p(m, 'dollars'):.5f}" if by[m] else None)):
            lines.append(f"| {lab} | " + " | ".join(str(fn(m)) if by[m] else "-" for m in ("BASE", "COLD", "WARM", "SECOND")) + " |")
        bt = base_in + base_out
        lines += ["", f"Tokens kept off the big model: COLD {100 * (1 - c_tok / bt):.1f}%, "
                  f"WARM {100 * (1 - (p('WARM', 'big_in') + p('WARM', 'big_out')) / bt):.1f}%, "
                  f"SECOND {100 * (1 - (p('SECOND', 'big_in') + p('SECOND', 'big_out')) / bt):.1f}%. "
                  f"Dollars saved: COLD ${base_usd - p('COLD', 'dollars'):.5f} of ${base_usd:.5f} "
                  f"({100 * (1 - p('COLD', 'dollars') / base_usd):.1f}%)." if base_usd and bt else ""]
    if warm and cold:
        gc = sum(r["gpu_call"] for r in cold)
        lines += ["", "## Cache: local vs shared", "",
                  f"- WARM (same machine, second pass): hit rate {sum(bool(r['cache_source']) for r in warm) / len(warm):.2f}, "
                  f"all local; GPU calls {sum(r['gpu_call'] for r in warm)} vs {gc} cold (avoided {gc - sum(r['gpu_call'] for r in warm)}), "
                  f"big-model calls {sum(1 for r in warm if r['big_in'] + r['big_out'])} vs {sum(1 for r in cold if r['big_in'] + r['big_out'])} cold."]
    if second:
        sh = [r["shared_ms"] for r in second if r["shared_ms"]]
        gc = sum(r["gpu_call"] for r in cold)
        lines += [f"- SECOND (fresh local cache, shared Supabase): hit rate {sum(bool(r['cache_source']) for r in second) / len(second):.2f} "
                  f"({sum(r['cache_source'] == 'shared' for r in second)} shared, {sum(r['cache_source'] == 'local' for r in second)} local); "
                  f"GPU calls {sum(r['gpu_call'] for r in second)} vs {gc} cold; shared lookup p50 {pct(sh, .5):.0f} ms, p90 {pct(sh, .9):.0f} ms; "
                  f"shared statuses {sorted({r['shared_status'] for r in second if r['shared_status']})}."]
    if cold or warm or second:
        # same-prompt hits must return what COLD answered; a graded-wrong hit whose COLD answer was right is a false hit
        cg = {r["id"]: r["grade"] for r in cold}
        fh = sum(1 for r in warm + second if r["cache_source"] and r["grade"] == 0 and cg.get(r["id"]) == 1)
        lines += [f"- False hits (served from cache, graded wrong, COLD answer was right): {fh}."]
    if PAIRS.exists():
        pr = json.loads(PAIRS.read_text())
        lines += ["", f"## Guard and threshold, {pr['n_pairs']} labeled Quora pairs ({pr['n_dup']} duplicates), real embedder", "",
                  "| threshold | guard | cache hits | right (duplicates) | wrong (not duplicates) |", "|---|---|---|---|---|"]
        for k, v in pr["cells"].items():
            t, g = k.replace("thr", "").split("_guard")
            lines.append(f"| {t} | {g} | {v['hits']} | {v['right']} | {v['wrong']} |")
    if by["GATE85"] and cold:
        lines += ["", "## Confidence gate 0.85 vs 0.95 (no caches, same prompts)", "",
                  "| gate | answered by Mac 3B | GPU calls | big-model calls | big tokens | big $ | graded correct | p50 ms | p90 ms |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for lab, rs in (("0.85", by["GATE85"]), ("0.95", cold)):
            lat = [r["latency_ms"] for r in rs]
            lines.append(f"| {lab} | {sum(r['path'] == 'mac-3b' for r in rs)} | {sum(r['gpu_call'] for r in rs)} | "
                         f"{sum(1 for r in rs if r['big_in'] + r['big_out'])} | {sum(r['big_in'] + r['big_out'] for r in rs)} | "
                         f"${sum(r['dollars'] for r in rs):.5f} | {acc(rs)} | {pct(lat, .5):.0f} | {pct(lat, .9):.0f} |")
        lines += ["", "(0.95 row is COLD, which also had caches on; its duplicates within the 60 prompts may be cache hits.)"]
    lines += ["", "## Accuracy by source (graded rows only)", "", "| source | BASE | COLD | GATE85 |", "|---|---|---|---|"]
    for src in sorted({r["src"] for r in cold}):
        lines.append(f"| {src} | " + " | ".join(acc([r for r in by[m] if r["src"] == src]) for m in ("BASE", "COLD", "GATE85")) + " |")
    lines += ["", "## Latency by path (all passes)", "", "| path | n | p50 ms | p90 ms |", "|---|---|---|---|"]
    allr = [r for m in ORDER if m != "BASE" for r in by[m]]
    for path in sorted({r["path"] for r in allr}):
        lat = [r["latency_ms"] for r in allr if r["path"] == path]
        lines.append(f"| {path} | {len(lat)} | {pct(lat, .5):.0f} | {pct(lat, .9):.0f} |")
    errs = [r for r in allr + by["BASE"] if r["error"]]
    lines += ["", f"Errors (calls where no tier answered): {len(errs)}."]
    (ROOT / "bench/results_backend.md").write_text("\n".join(lines) + "\n")
    with (ROOT / "bench/results_backend.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(allr[0]))
        w.writeheader()
        w.writerows([r for m in ORDER for r in by[m]])
    print("\n".join(lines))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    {"run": lambda: run(sys.argv[2:] or ORDER), "pairs": pairs, "report": report}[cmd]()
