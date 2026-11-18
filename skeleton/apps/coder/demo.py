"""Offline demo of the coder (no model, no key, no network): `python -m skeleton.apps.coder demo`.

Three small repos. The stub 30B fixes two and breaks one; the broken patch fails its tests and climbs to the stub
763B. Then every task is asked again: the cache serves the checked patch, the tests re-run, 0 tokens.
The same tasks run live with `python skeleton/bench/run.py --live` (real 30B and 763B).
"""
from __future__ import annotations

import pathlib
import shlex
import sys
import tempfile

from skeleton.core import Assistant

from .coder import CONFIG, Coder, report

PY = shlex.quote(sys.executable)
TASKS = [
    {"name": "fix-add", "task": "Fix add() in calc.py so that add(2, 3) == 5.", "file": "calc.py",
     "code": "def add(a, b):\n    return a - b\n",
     "test": "from calc import add\nassert add(2, 3) == 5\nassert add(-1, 1) == 0\n"},
    {"name": "greet", "task": "Make greet(name) in greet.py return 'Hello, <name>!'.", "file": "greet.py",
     "code": "def greet(name):\n    return name\n",
     "test": "from greet import greet\nassert greet('Ada') == 'Hello, Ada!'\n"},
    {"name": "clamp", "task": "Fix clamp(x, lo, hi) in clamp.py: it must keep x between lo and hi.", "file": "clamp.py",
     "code": "def clamp(x, lo, hi):\n    return max(x, lo)\n",
     "test": "from clamp import clamp\nassert clamp(5, 0, 3) == 3\nassert clamp(-1, 0, 3) == 0\nassert clamp(2, 0, 3) == 2\n"},
]


def _edit(path: str, old: str, new: str) -> str:
    return f"{path}\n<<<<<<< SEARCH\n{old}\n=======\n{new}\n>>>>>>> REPLACE\n"


GOOD = {"fix-add": _edit("calc.py", "    return a - b", "    return a + b"),
        "greet": _edit("greet.py", "    return name", "    return f'Hello, {name}!'"),
        "clamp": _edit("clamp.py", "    return max(x, lo)", "    return min(max(x, lo), hi)")}
BAD = {**GOOD, "fix-add": _edit("calc.py", "    return a - b", "    return a * b")}  # the 30B's wrong fix


def _stub(answers: dict[str, str]):
    def answer(prompt: str) -> str:
        q = prompt.rsplit("Question:", 1)[-1]
        return next((answers[t["name"]] for t in TASKS if t["task"] in q), "")
    return answer


DEMO_MODELS = {"gpu-small": _stub(BAD), "cloud-deepseek": _stub(GOOD)}


def make_repo(root: pathlib.Path, t: dict) -> pathlib.Path:
    repo = root / t["name"]
    repo.mkdir(parents=True)
    (repo / t["file"]).write_text(t["code"])
    (repo / "check.py").write_text(t["test"])
    return repo


def run(live: bool = False, passes: int = 2, echo=None) -> list[dict]:
    """Each task `passes` times on one Assistant. Rows: task, pass, tiers tried, verified, tokens, $, ms."""
    cfg = CONFIG if not live else {**__import__("tomllib").loads(CONFIG.read_text()), "mode": "live"}
    bot = Assistant(cfg, demo_models=DEMO_MODELS)
    rows = []
    with tempfile.TemporaryDirectory(prefix="skeleton-coder-demo-") as tmp:
        repos = {t["name"]: make_repo(pathlib.Path(tmp), t) for t in TASKS}
        for n in range(1, passes + 1):
            for t in TASKS:
                r = Coder(repos[t["name"]], [t["file"]], f"{PY} check.py", assistant=bot).ask(t["task"])
                if echo:
                    echo(f"\n== pass {n}: {t['name']} ==\n{report(r)}")
                a = r.answer
                rows.append({"task": t["name"], "pass": n, "tier": a["tier"], "tried": a["tried"],
                             "climbs": max(len(a["tried"]) - 1, 0), "cache_hit": a["cache_hit"], "verified": a["verified"],
                             "tokens": a["tokens"], "dollars": a["dollars"], "dollars_saved": a["dollars_saved"],
                             "ms": a["latency_ms"]})
    return rows


def main() -> int:
    rows = run(echo=print)
    ok = all(r["verified"] for r in rows)
    print(f"\n{sum(r['cache_hit'] for r in rows)} of {len(rows)} asks served from the cache; "
          f"{sum(r['climbs'] for r in rows)} climb(s); all tests pass: {ok}  (demo: stub models)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
