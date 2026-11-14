"""Shared bootstrap for the kiro-trimmer scripts: repo venv re-exec, chimera_core import, stats."""
from __future__ import annotations

import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_venv_py = ROOT / ".venv" / "bin" / "python"
if _venv_py.exists() and pathlib.Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
    os.execv(str(_venv_py), [str(_venv_py), *sys.argv])  # e.g. the hook runs plain `python3`

sys.path.insert(0, str(ROOT))
import conftest  # noqa: E402,F401  (registers the hyphenated package as chimera_core)

from chimera_core.config import ChimeraConfig, build_router, load_config  # noqa: E402,F401


def read_stats(path: pathlib.Path) -> dict:
    """Totals from the telemetry JSONL. Missing file or bad lines count as no data."""
    rows = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    tiers: dict[str, int] = {}
    for r in rows:
        tiers[r["tier_used"]] = tiers.get(r["tier_used"], 0) + 1
    return {
        "calls": len(rows),
        "tiers": tiers,
        "tokens_saved": sum(r.get("tokens_saved", 0) for r in rows),
        "dollars_saved": round(sum(r.get("dollars_saved", 0.0) for r in rows), 6),
        "mean_latency_ms": round(sum(r.get("latency_ms", 0.0) for r in rows) / len(rows), 1) if rows else 0.0,
    }


def telemetry_line(t) -> str:
    return (f"[tier={t.tier_used} latency={t.latency_ms:.0f}ms "
            f"tokens_saved={t.tokens_saved} dollars_saved=${t.dollars_saved:.6f}]")
