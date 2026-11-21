"""Dec-1 one-command Python driver for the big-model test suite.

Wraps deploy/dec1/run_all.sh and provides a no-op dry-run, a Crusoe smoke test,
and a simple status check.  All output goes to bench/.scratch/dec1/.

Usage:
    .venv/bin/python deploy/dec1/run_all.py               # full run (or no-op if no GPU/120B)
    .venv/bin/python deploy/dec1/run_all.py dry_run       # print commands, do not run
    .venv/bin/python deploy/dec1/run_all.py smoke         # Crusoe + Supabase 1-call smoke test
    .venv/bin/python deploy/dec1/run_all.py status        # show which scratch rows exist

Credentials are read from .env (never printed).  Keys are never committed.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRATCH = ROOT / "bench" / ".scratch" / "dec1"
SCRATCH.mkdir(parents=True, exist_ok=True)


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    envfile = ROOT / ".env"
    if not envfile.exists():
        return env
    for line in envfile.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        idx = line.find("=")
        if idx < 0:
            continue
        env[line[:idx]] = line[idx + 1:]
    return env


def check_env(env: dict[str, str]) -> list[str]:
    """Return list of problems; empty means ready."""
    problems = []
    if not env.get("CRUSOE_API_KEY", "").strip():
        problems.append("CRUSOE_API_KEY not set in .env")
    if not env.get("CHIMERA_DB_URL", "").strip():
        problems.append("CHIMERA_DB_URL not set in .env")
    return problems


def has_gpu() -> bool:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0 and r.stdout.strip() != ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def smoke(env: dict[str, str]) -> None:
    """One call each to Crusoe and Supabase; print latency and result."""
    sys.path.insert(0, str(ROOT))
    import conftest  # noqa: F401  (registers chimera_core)
    for k, v in env.items():
        os.environ.setdefault(k, v)

    # Crusoe
    from chimera_core.ladder import TopBackend  # noqa: WPS433
    t0 = time.perf_counter()
    b = TopBackend(
        "deepseek-ai/DeepSeek-V4.1-Flash",
        {"thinking": False},
        api_key=env["CRUSOE_API_KEY"],
        base_url="https://api.inference.crusoecloud.com",
        timeout=30,
    )
    text = b.complete("Reply with only: dec1-smoke-ok", 10)
    ms_crusoe = (time.perf_counter() - t0) * 1000
    print(f"Crusoe smoke:   {ms_crusoe:.0f} ms  reply={text.strip()[:30]!r}")

    # Supabase
    from chimera_core.cache.pgvector_cache import PgStore  # noqa: WPS433
    t0 = time.perf_counter()
    import hashlib
    st = PgStore(env["CHIMERA_DB_URL"])
    h = hashlib.sha256(b"dec1-smoke-noop").hexdigest()
    result = st.find_exact("dec1-smoke", h, h)
    ms_pg = (time.perf_counter() - t0) * 1000
    print(f"Supabase smoke: {ms_pg:.0f} ms  hit={result is not None}")

    out = {
        "crusoe_ms": round(ms_crusoe),
        "crusoe_reply": text.strip()[:30],
        "supabase_ms": round(ms_pg),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (SCRATCH / "smoke.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"Wrote {SCRATCH / 'smoke.json'}")


def status() -> None:
    """Show which result rows already exist in bench/.scratch/dec1/."""
    files = sorted(SCRATCH.glob("*.jsonl"))
    if not files:
        print("No .jsonl rows yet in", SCRATCH)
        return
    for f in files:
        lines = f.read_text().splitlines()
        done = sum(1 for l in lines if l.strip())
        print(f"  {f.name}: {done} rows")


def dry_run() -> None:
    env = load_env()
    problems = check_env(env)
    if problems:
        print("Missing credentials (fix before Dec 1):")
        for p in problems:
            print(" -", p)
    gpu = has_gpu()
    skip_120b = not env.get("CHIMERA_120B_URL", "").strip()
    print(f"GPU detected: {gpu}")
    print(f"120B tier:    {'skip' if skip_120b else 'run'}")
    print()
    env_copy = os.environ.copy()
    env_copy.update({k: v for k, v in env.items() if k not in env_copy})
    env_copy["DRY_RUN"] = "1"
    if skip_120b:
        env_copy["SKIP_120B"] = "1"
    script = ROOT / "deploy" / "dec1" / "run_all.sh"
    subprocess.run(["bash", str(script)], env=env_copy, check=False)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    env = load_env()
    if cmd == "smoke":
        problems = check_env(env)
        if problems:
            for p in problems:
                print("ERROR:", p)
            sys.exit(1)
        smoke(env)
    elif cmd == "status":
        status()
    elif cmd == "dry_run":
        dry_run()
    else:
        # Full run: delegate to the shell script
        problems = check_env(env)
        if problems:
            print("Missing credentials:")
            for p in problems:
                print(" -", p)
            sys.exit(1)
        env_copy = os.environ.copy()
        env_copy.update({k: v for k, v in env.items() if k not in env_copy})
        if not env.get("CHIMERA_120B_URL", "").strip():
            env_copy["SKIP_120B"] = "1"
        script = ROOT / "deploy" / "dec1" / "run_all.sh"
        subprocess.run(["bash", str(script)], env=env_copy, check=False)


if __name__ == "__main__":
    main()
