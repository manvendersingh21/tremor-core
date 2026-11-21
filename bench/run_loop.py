"""Scenario loop: run the prompt mix through the tier pool, N rounds or forever.

Writes one telemetry JSONL line per call to the HUD's file (HUD_TELEMETRY, default
apps/phantom-phone/hud-web/telemetry.jsonl) and prints a per-tier token table every round.
Usage: .venv/bin/python bench/run_loop.py [--rounds 3 | --forever] [--url gpu-small=http://127.0.0.1:11437]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import conftest  # noqa: E402,F401  (registers chimera_core)
from chimera_core.config import load_config, load_env  # noqa: E402
from chimera_core.inference.telemetry import Telemetry  # noqa: E402
from chimera_core.router import complexity_score  # noqa: E402
from chimera_core.tiers import AllTiersFailed, TierPool, TierUsage  # noqa: E402

HUD_FILE = ROOT / "apps/phantom-phone/hud-web/telemetry.jsonl"
DEVICE_TIER = {"phone": "local", "laptop": "local", "gpu": "gpu", "cloud": "top"}  # Telemetry.tier_used names


def table(totals: dict[str, TierUsage]) -> str:
    rows = [f"{'tier':<12}{'calls':>6}{'errors':>7}{'tok_in':>9}{'tok_out':>9}{'$':>10}"]
    for n, u in totals.items():
        rows.append(f"{n:<12}{u.calls:>6}{u.errors:>7}{u.tokens_in:>9}{u.tokens_out:>9}{u.dollars:>10.5f}")
    return "\n".join(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--forever", action="store_true")
    ap.add_argument("--config", default=None)
    ap.add_argument("--prompts", type=int, default=0, help="use only the first N prompts per round")
    ap.add_argument("--only", default="", help="comma list of tier names to use")
    ap.add_argument("--url", action="append", default=[], metavar="TIER=URL")
    a = ap.parse_args()

    load_env()
    cfg = load_config(a.config)
    tiers = cfg.tiers or load_config(ROOT / "chimera.example.toml").tiers
    over = dict(u.split("=", 1) for u in a.url)
    tiers = [t.model_copy(update={"url": over[t.name]}) if t.name in over else t for t in tiers]
    tiers = [t for t in tiers if not a.only or t.name in a.only.split(",")]
    pool = TierPool(tiers, min_confidence=cfg.thresholds.confidence, max_tokens=512)
    cloud = {t.name for t in pool.tiers if t.device == "cloud"}
    top = next((t for t in reversed(pool.tiers) if t.device == "cloud"), None)  # price baseline for "saved"
    prompts = [json.loads(x) for x in (ROOT / "bench/prompts.jsonl").read_text().splitlines() if x.strip()]
    prompts = prompts[: a.prompts] if a.prompts else prompts
    out = pathlib.Path(os.environ.get("HUD_TELEMETRY", HUD_FILE))
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"tiers: {[t.name for t in pool.tiers]}  prompts: {len(prompts)}  telemetry: {out}")

    totals: dict[str, TierUsage] = {}
    rnd = 0
    while a.forever or rnd < a.rounds:
        rnd += 1
        failed = 0
        for p in prompts:
            try:
                r = pool.generate(p["prompt"], complexity_score(p["prompt"]))
            except AllTiersFailed as e:
                failed += 1
                print(f"  {p['id']}: {e}")
                continue
            for n, u in r.per_tier.items():
                t = totals.setdefault(n, TierUsage())
                for f in ("calls", "errors", "tokens_in", "tokens_out", "dollars"):
                    setattr(t, f, getattr(t, f) + getattr(u, f))
            used = r.per_tier[r.tier]
            owned = r.device != "cloud"
            tel = Telemetry(
                tier_used=DEVICE_TIER[r.device],
                tokens_saved=used.tokens_in + used.tokens_out if owned else 0,
                latency_ms=r.latency_ms,
                dollars_saved=((used.tokens_in * top.cost_per_1k_in + used.tokens_out * top.cost_per_1k_out) / 1000
                               if top and owned else 0.0),
                local_tokens=used.tokens_out if r.device in ("phone", "laptop") else 0,
                gpu_tokens=used.tokens_out if r.device == "gpu" else 0,
                cloud_tokens=sum(x.tokens_out for n, x in r.per_tier.items() if n in cloud),
                per_tier=pool.telemetry_per_tier(r),
            )
            line = tel.model_dump() | {"tier_name": r.tier, "round": rnd, "attempts": r.attempts,
                                       "pool_usage": {k: v.model_dump() for k, v in r.per_tier.items()}}
            with open(out, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line) + "\n")
        print(f"\n== round {rnd} ({failed} failed) cumulative per-tier tokens ==\n{table(totals)}\n", flush=True)
        if a.forever:
            time.sleep(1)


if __name__ == "__main__":
    main()
