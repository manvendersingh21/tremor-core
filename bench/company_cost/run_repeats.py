"""Repeat the key tests 3 times each, so the company cost story has a mean and a spread, not single runs.

    .venv/bin/python bench/company_cost/run_repeats.py cache  [reps]   # Supabase cache, exact + cosine, no model
    .venv/bin/python bench/company_cost/run_repeats.py bank   [reps]   # solved-problem bank, runs 1-3 per repeat
    .venv/bin/python bench/company_cost/run_repeats.py ladder [reps]   # 60-prompt BASE / COLD / WARM (bench/run_backend.py)

Uses only Supabase (CHIMERA_DB_URL), Crusoe (CRUSOE_API_KEY) and the GPU 30B link (CHIMERA_GPU_URL). No Modal.
Rows go to bench/.scratch/company_cost/ (git-ignored), one per item as it finishes; a rerun skips done rows.
Each repeat uses its own tenant or namespace, and its Supabase rows are deleted once the repeat is complete.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import conftest  # noqa: E402,F401
from chimera_core.config import load_env  # noqa: E402

OUT = ROOT / "bench/.scratch/company_cost"
PY = sys.executable


def jl(path: pathlib.Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def jl_add(path: pathlib.Path, rec: dict) -> None:
    with path.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")


# ---- 1. Supabase cache: client A stores, a second client B asks again ------------------------------------
NEAR = [("What is the capital of Germany?", "berlin"), ("What is the chemical symbol for silver?", "ag"),
        ("How many days are in a non-leap year?", "365"), ("Who wrote the novel Emma?", "austen"),
        ("What does HTTP status code 500 mean?", "internal"), ("Convert 0 degrees Celsius to Fahrenheit.", "32")]


def cache_sets(rows: list[dict]) -> dict[str, list[tuple[str, list[str]]]]:
    """Same four sets as bench/run_cache.py: same text, case/spacing, prefix added, near-miss (any hit is wrong)."""
    return {
        "repeat": [(r["prompt"], r["expect"]) for r in rows],
        "format": [("  " + r["prompt"].upper() + "  ", r["expect"]) for r in rows],
        "paraphrase": [("Quick question: " + r["prompt"][0].lower() + r["prompt"][1:], r["expect"]) for r in rows],
        "near_miss": [(q, [e]) for q, e in NEAR],
    }


def cache(reps: int) -> None:
    from chimera_core.cache.guard import make_guard
    from chimera_core.cache.pgvector_cache import PgStore, PgVectorCache
    from chimera_core.cache.semantic_cache import OnnxMiniLMEmbedder

    dsn = os.environ["CHIMERA_DB_URL"]
    f = OUT / "cache.jsonl"
    rows = [r for r in map(json.loads, (ROOT / "bench/prompts.jsonl").read_text().splitlines()) if r.get("expect")]
    emb = OnnxMiniLMEmbedder()
    emb.embed("warm up")
    for k in range(1, reps + 1):
        have = [r for r in jl(f) if r["rep"] == k]
        if any(r["kind"] == "purged" for r in have):
            continue
        tenant = f"bench-cc-cache-r{k}"
        # product settings: no local fallback, guard on, 300 ms budget, threshold 0.97
        mk = lambda: PgVectorCache(emb, lambda: PgStore(dsn), threshold=0.97, tenant=tenant, fallback=None,  # noqa: E731
                                   store_text=True, guard=make_guard(), budget_s=0.3)
        A, B = mk(), mk()  # two objects, two pools: B plays the second machine
        for c in (A, B):  # connect outside the budget so connect time is not lookup time
            c._store_ready()._pool.wait(timeout=30)
            c.ping(10)
        if not any(r["kind"] == "A" for r in have):
            for r in rows:  # client A: every prompt is one model call whose checked answer is stored
                A.put(r["prompt"], " ".join(r["expect"]))
            A.flush()
            jl_add(f, {"rep": k, "kind": "A", "stored": len(rows)})
        done = {(r["set"], r["i"]) for r in have if r["kind"] == "B"}
        for name, items in cache_sets(rows).items():
            for i, (q, exp) in enumerate(items):
                if (name, i) in done:
                    continue
                t0 = time.perf_counter()
                hit, info = B._lookup(q, "")
                ms = (time.perf_counter() - t0) * 1000
                wrong = bool(hit) and not any(e.lower() in hit.response.lower() for e in exp)
                jl_add(f, {"rep": k, "kind": "B", "set": name, "i": i, "hit": bool(hit),
                           "source": hit.source if hit else None, "sim": round(hit.similarity, 4) if hit else info.best_sim,
                           "guard": info.guard, "wrong": wrong, "status": info.status, "ms": round(ms, 1)})
        B.flush()
        n = A.purge()
        jl_add(f, {"rep": k, "kind": "purged", "rows": n})
        print("cache rep", k, "done, purged", n, flush=True)


# ---- 2. Solved-problem bank: bench/bank/run_bank.py stages in a fresh tenant per repeat --------------------
def bank(reps: int) -> None:
    sys.path.insert(0, str(ROOT / "bench" / "bank"))
    import run_bank as B  # noqa: PLC0415  (its imports read .env and the bench/memory rows)

    test, train, base, top, teach = B.load()
    src = ROOT / "bench/.scratch/bank"
    for k in range(1, reps + 1):
        d = OUT / f"bank_r{k}"
        d.mkdir(parents=True, exist_ok=True)
        if (d / "purged.json").exists():
            continue
        for name in ("reworded.jsonl", "emb.jsonl"):  # same reworded copies, same embeddings; model answers are fresh
            if not (d / name).exists():
                shutil.copy(src / name, d / name)
        B.D, B.TENANT = d, f"bench-cc-bank-r{k}"
        emb = B.CachedEmbedder()
        bk = B.make_bank(emb, use_graph=False)  # the graph is not part of the lookup; keep Aura out of the repeats
        if not B.jl("run1.jsonl") and bk.stats()["size"]:
            bk.purge()
        B.stage_run(1, test, bk, base, top)  # replays saved answers: fills the bank with the test problems
        B.stage_fill(train, teach, bk)
        B.stage_run(2, test, bk, base, top)
        B.stage_run(3, B.reworded(test), bk, base, top)  # misses make fresh 30B / 763B calls (no rw_* rows copied)
        n = bk.purge()
        (d / "purged.json").write_text(json.dumps({"rows": n}))
        print("bank rep", k, "done, purged", n, flush=True)


# ---- 3. 60-prompt ladder check: bench/run_backend.py in its own store and namespace per repeat --------------
def ladder(reps: int) -> None:
    from chimera_core.cache.pgvector_cache import PgStore, PgVectorCache

    for k in range(1, reps + 1):
        d = OUT / f"ladder_r{k}"
        d.mkdir(parents=True, exist_ok=True)
        if (d / "purged.json").exists():
            continue
        ns = f"bench-cc-ladder-r{k}"
        env = dict(os.environ, BENCH_STORE=str(d), BENCH_NS=ns)
        with (d / "run.log").open("a") as log:  # one process at a time; run_backend skips done ids itself
            subprocess.run([PY, str(ROOT / "bench/run_backend.py"), "run", "BASE", "COLD", "WARM"],
                           env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        got = {(r["pass"], r["id"]) for r in jl(d / "backend_rows.jsonl")}
        if len(got) < 180:
            raise SystemExit(f"ladder rep {k}: {len(got)} of 180 rows, rerun to resume")
        c = PgVectorCache(None, PgStore(os.environ["CHIMERA_DB_URL"]), tenant="bench-backend")
        n = c.purge(ns)
        (d / "purged.json").write_text(json.dumps({"rows": n}))
        print("ladder rep", k, "done, purged", n, flush=True)


if __name__ == "__main__":
    load_env()
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = sys.argv[1]
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    {"cache": cache, "bank": bank, "ladder": ladder}[cmd](reps)
