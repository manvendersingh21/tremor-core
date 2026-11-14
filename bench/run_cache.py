"""Cache-only benchmark: SQLite cache vs shared Postgres/pgvector cache. No GPU or model server needed.

Client A answers the 30 prompts in bench/prompts.jsonl (every miss counts as one GPU call and stores the known
answer). Client B is a second machine with its own empty local SQLite. It replays four prompt sets:
  repeat (same text), format (case/spacing), paraphrase (prefix added), near_miss (similar words, other answer).
A hit is a false hit when the served answer lacks the expected string of the asked prompt.
Modes: sqlite-same (B reuses A's file), sqlite-split (B has its own empty file), postgres (A and B share the DB).
    .venv/bin/python bench/run_cache.py [--budget-ms 150] > $KIROCREW_SCRATCH/cache.json
Needs CHIMERA_DB_URL for postgres. Uses a throw-away tenant and deletes its rows afterwards.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import conftest  # noqa: E402,F401
from chimera_core.cache.pgvector_cache import PgStore, PgVectorCache  # noqa: E402
from chimera_core.cache.semantic_cache import OnnxMiniLMEmbedder, SemanticCache  # noqa: E402
from chimera_core.config import load_env  # noqa: E402

# Close wording to a cached prompt, different correct answer. Any hit on these is a false hit.
NEAR = [("What is the capital of Germany?", "berlin"), ("What is the chemical symbol for silver?", "ag"),
        ("How many days are in a non-leap year?", "365"), ("Who wrote the novel Emma?", "austen"),
        ("What does HTTP status code 500 mean?", "internal"), ("Convert 0 degrees Celsius to Fahrenheit.", "32")]


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(int(q * len(xs)), len(xs) - 1)] if xs else 0.0


def sets(rows):
    return {
        "repeat": [(r["prompt"], r["expect"]) for r in rows],
        "format": [("  " + r["prompt"].upper() + "  ", r["expect"]) for r in rows],
        "paraphrase": [("Quick question: " + r["prompt"][0].lower() + r["prompt"][1:], r["expect"]) for r in rows],
        "near_miss": [(q, [e]) for q, e in NEAR],
    }


def run(mode, rows, emb, budget_ms, dsn, tmp):
    tenant = f"bench-{uuid.uuid4().hex[:8]}"
    a_local = SemanticCache(emb, 0.97, f"{tmp}/{mode}-a.db")
    b_local = a_local if mode == "sqlite-same" else SemanticCache(emb, 0.97, f"{tmp}/{mode}-b.db")
    if mode == "postgres":
        mk = lambda local: PgVectorCache(emb, lambda: PgStore(dsn), tenant=tenant, fallback=local,  # noqa: E731
                                         budget_s=budget_ms / 1000)
        A, B = mk(a_local), mk(b_local)
        for c in (A, B):  # connect first (outside the 150 ms budget) so connect time is not counted as lookup time
            st = c._store_ready()
            st._pool.wait(timeout=30)
            st.lookup(tenant, "", "x", [0.0] * 384, 1)
    else:
        A, B = a_local, b_local
    gpu_a = a_false = 0
    for r in rows:  # client A: cold, every miss is one "GPU call"
        got = A.get(r["prompt"])
        if got is None:
            gpu_a += 1
            A.put(r["prompt"], " ".join(r["expect"]))
        elif not any(e.lower() in got[0].lower() for e in r["expect"]):
            a_false += 1
    if mode == "postgres":
        A.flush()
    out = {"mode": mode, "A_gpu_calls": gpu_a, "A_false_hits": a_false, "B": {}}
    lat, tot = [], dict(n=0, hits=0, false=0)
    for name, items in sets(rows).items():
        hits = false = 0
        for q, exp in items:
            t0 = time.perf_counter()
            got = B.get(q)
            lat.append((time.perf_counter() - t0) * 1000)
            if got:
                hits += 1
                false += not any(e.lower() in got[0].lower() for e in exp)
        out["B"][name] = {"n": len(items), "hits": hits, "false_hits": false}
        tot["n"] += len(items)
        tot["hits"] += hits
        tot["false"] += false
    out["B_total"] = {**tot, "hit_rate": round(tot["hits"] / tot["n"], 3), "gpu_calls_avoided": tot["hits"],
                      "false_hit_rate": round(tot["false"] / tot["hits"], 3) if tot["hits"] else 0.0,
                      "lookup_p50_ms": round(pct(lat, .5), 1), "lookup_p90_ms": round(pct(lat, .9), 1)}
    if mode == "postgres":
        s = B.summary()
        out["B_fallbacks"] = s["fallbacks"]
        out["B_db_lookup_p50_ms"], out["B_db_lookup_p90_ms"] = round(s["p50_ms"], 1), round(s["p90_ms"], 1)
        B.flush()
        out["purged_rows"] = A.purge()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-ms", type=int, default=150)
    ap.add_argument("--modes", default="sqlite-same,sqlite-split,postgres")
    a = ap.parse_args()
    load_env()
    rows = [r for r in map(json.loads, open(ROOT / "bench/prompts.jsonl")) if r.get("expect")]  # gradable only
    emb = OnnxMiniLMEmbedder()
    emb.embed("warm up")
    with tempfile.TemporaryDirectory() as tmp:
        res = [run(m, rows, emb, a.budget_ms, os.environ.get("CHIMERA_DB_URL", ""), tmp) for m in a.modes.split(",")]
    print(json.dumps(res, indent=1))
