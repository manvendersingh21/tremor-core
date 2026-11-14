"""Shared helpers for the Kiro hook scripts. Stdlib only, no network."""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
PY = ROOT / ".venv" / "bin" / "python"
PYTHON = str(PY) if PY.exists() else sys.executable


def event() -> dict:
    """The hook event JSON on STDIN ({} when empty or not JSON)."""
    try:
        data = json.loads(sys.stdin.read() or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def event_paths(ev: dict) -> list[str]:
    """Every string in the event that looks like a file path, relative to the repo root."""
    out: list[str] = []

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str) and re.search(r"\.\w{1,6}$", v) and "\n" not in v and len(v) < 400:
            p = pathlib.Path(v)
            try:
                rel = p.resolve().relative_to(ROOT) if p.is_absolute() else p
            except ValueError:
                return
            out.append(rel.as_posix())

    walk({k: v for k, v in ev.items() if k not in ("cwd", "session_id", "hook_event_name")})
    return out


def run(cmd: list[str], timeout: int = 100) -> int:
    """Run cmd in the repo root. Output goes to stdout (added to the agent's context). Returns the exit code."""
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"timeout after {timeout}s: {' '.join(cmd)}", file=sys.stderr)
        return 1
    tail = (r.stdout + r.stderr).strip().splitlines()[-25:]
    print("\n".join(tail))
    return r.returncode
