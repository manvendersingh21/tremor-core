"""Run tasks.jsonl through the real router policy: cache -> GPU 30B -> 763B (no Mac 3B).

    .venv/bin/python bench/cost_case/run_router.py

Uses run_suite.build("POOL"): SpeculativeCascadeRouter.generate() over a TierPool, public API only, nothing in
packages/ or apps/ is edited. Needs the Mac llama-server, the GPU tunnel on $GPU_PORT (set it in .env or the shell), CRUSOE_API_KEY.
Rows go to $KIROCREW_SCRATCH/cost_case/router.jsonl; a rerun skips finished ids.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT / "bench" / "datasets"))
import run_suite  # noqa: E402  (importing it sets up sys.path and conftest)
import grade  # noqa: E402
from chimera_core import RouterConfig, SpeculativeCascadeRouter  # noqa: E402
from chimera_core.cache.semantic_cache import OnnxMiniLMEmbedder, SemanticCache  # noqa: E402
from chimera_core.inference.local_draft import LlamaCppBackend  # noqa: E402
from chimera_core.tiers import TierPool  # noqa: E402
from run_bench import load_env  # noqa: E402

STORE = ROOT / "bench/.scratch" / "cost_case"  # repo-local: survives restarts (never $KIROCREW_SCRATCH)
TASKS = pathlib.Path(__file__).parent / "tasks.jsonl"


def main() -> None:
    os.environ.setdefault("GPU_PORT", os.environ.get("GPU_PORT", ""))
    load_env()
    rows = [json.loads(x) for x in TASKS.read_text().splitlines()]
    if os.environ.get("ROUTER_N"):  # shortcut: the shared 30B box is slow; a stratified subset (ids evenly spaced per difficulty) keeps the run finite
        k = int(os.environ["ROUTER_N"])
        keep = set()
        for d in ("trivial", "everyday", "hard"):
            g = sorted(r["id"] for r in rows if r["difficulty"] == d)
            keep |= {g[int(i * len(g) / k)] for i in range(k)}
        rows = [r for r in rows if r["id"] in keep]
    STORE.mkdir(parents=True, exist_ok=True)
    out = STORE / "router.jsonl"
    done = {json.loads(x)["id"] for x in out.read_text().splitlines()} if out.exists() else set()
    # Ladder per the 2026-11-14 decision: cache -> self-hosted 30B -> 763B. No Mac 3B tier.
    pool = TierPool([t for t in run_suite.pool_tiers() if t.name != "mac-3b"], min_confidence=0.85, max_tokens=1024)
    last: dict = {}
    orig = pool.generate

    def spy(prompt, complexity=None, **kw):
        last["r"] = r = orig(prompt, complexity, **kw)
        return r

    pool.generate = spy
    sem = SemanticCache(OnnxMiniLMEmbedder(), threshold=0.97)
    sem._embedder.embed("warm up")
    router = SpeculativeCascadeRouter(LlamaCppBackend(), semantic=sem, config=RouterConfig(min_confidence=0.85), pool=pool)
    for t in router.pool.tiers:  # load the models; not timed
        if t.device != "cloud":
            try:
                router.pool._factory(t).complete("hello", 4)
            except Exception as e:  # noqa: BLE001
                print("warm-up failed", t.name, type(e).__name__, flush=True)
    with out.open("a") as fh:
        for r in rows:
            if r["id"] in done:
                continue
            last.clear()
            t0 = time.perf_counter()
            err = ""
            try:
                res = router.generate(r["prompt"])
                text, tier = res.text, res.telemetry.tier_used
                if "r" in last:
                    tier = last["r"].tier
            except Exception as e:  # noqa: BLE001  AllTiersFailed or an escaped tier error
                text, tier, err = "", "failed", f"{type(e).__name__}: {e}"[:200]
            ms = (time.perf_counter() - t0) * 1000
            pr = last.get("r")
            per = {k: v.model_dump() for k, v in pr.per_tier.items()} if pr else {}
            rec = {"id": r["id"], "difficulty": r["difficulty"], "tier": tier, "latency_ms": round(ms), "answer": text,
                   "attempts": pr.attempts if pr else [], "confidence": pr.confidence if pr else None, "per_tier": per, "error": err,
                   "pass": grade.grade(r, text) if text else 0}
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print("router", r["id"], tier, round(ms), rec["pass"], err, flush=True)


if __name__ == "__main__":
    main()
