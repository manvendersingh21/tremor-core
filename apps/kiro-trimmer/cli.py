"""chimera ask | stats | doctor.  Run: bin/chimera <cmd>  or  python apps/kiro-trimmer/cli.py <cmd>."""
from __future__ import annotations

import argparse
import os
import sys
import urllib.request

from common import build_router, load_config, read_stats, telemetry_line
from chimera_core.config import tier_checks


def _get(url: str, headers: dict | None = None) -> None:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=3):  # noqa: S310
        pass


def doctor(cfg) -> int:
    checks = tier_checks(cfg)  # also loads .env
    key = os.environ.get("CRUSOE_API_KEY", "")
    bad = 0
    for name, base, url, headers in checks:
        try:
            if name == "crusoe" and not key:
                raise RuntimeError("CRUSOE_API_KEY not set")
            _get(url, headers)
            print(f"✅ {name:7} {base}")
        except Exception as e:  # noqa: BLE001  any failure means unreachable
            bad += 1
            print(f"❌ {name:7} {base}  ({e})")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="chimera")
    ap.add_argument("--config", help="path to chimera.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ask = sub.add_parser("ask", help="answer a prompt through the router")
    ask.add_argument("prompt")
    sub.add_parser("stats", help="totals from the telemetry JSONL")
    sub.add_parser("doctor", help="check each tier is reachable")
    keys = sub.add_parser("keys", help="gateway API keys (admin)").add_subparsers(dest="action", required=True)
    keys.add_parser("create", help="print a new key once").add_argument("--tenant", required=True)
    keys.add_parser("list", help="list keys (hashes only)")
    rv = keys.add_parser("revoke", help="revoke a tenant's keys, or one with --id")
    rv.add_argument("--tenant")
    rv.add_argument("--id", type=int)
    cache = sub.add_parser("cache", help="gateway cache admin").add_subparsers(dest="action", required=True)
    cache.add_parser("purge", help="delete a tenant's cached answers").add_argument("--tenant", required=True)
    ev = sub.add_parser("evals", help="one log of every benchmark run").add_subparsers(dest="action", required=True)
    ev.add_parser("import", help="read every bench result file into ~/.chimera/evals.db (and Supabase if CHIMERA_DB_URL is set)")
    for name, h in (("list", "print logged rows"), ("leaderboard", "one row per benchmark and mode")):
        sp = ev.add_parser(name, help=h)
        sp.add_argument("--dataset")
        if name == "list":
            sp.add_argument("--mode")
            sp.add_argument("--limit", type=int, default=50)
    from apps.replay.cli import add_parser as add_replay
    add_replay(sub)
    args = ap.parse_args(argv)
    if args.cmd == "replay":  # builds its own tiers; reads keys from .env
        from apps.replay.cli import main as replay_main
        return replay_main(args)
    if args.cmd == "evals":  # needs no config or models
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bench"))
        import evallog
        return evallog.main(args)
    cfg = load_config(args.config)

    if args.cmd in ("keys", "cache"):
        from apps.gateway.admin import run_admin
        return run_admin(args, cfg)
    if args.cmd == "doctor":
        return doctor(cfg)
    if args.cmd == "stats":
        s = read_stats(cfg.telemetry_path)
        print(f"calls={s['calls']} tiers={s['tiers']} tokens_saved={s['tokens_saved']} "
              f"dollars_saved=${s['dollars_saved']:.6f} mean_latency={s['mean_latency_ms']}ms")
        return 0
    try:
        out = build_router(cfg).generate(args.prompt)
    except Exception as e:  # noqa: BLE001
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(out.text)
    print(telemetry_line(out.telemetry))
    return 0


if __name__ == "__main__":
    sys.exit(main())
