"""Terminal coding agent built only on the skeleton API.

ask a task -> Assistant.ask(task, context=files, verify=tests pass) -> show each step (tier, tokens, $) and the diff.
The verify hook applies the edits to a temp copy of the repo and runs the test command there; a failing patch is
never cached and the task climbs from the 30B to the 763B. The repo itself changes only with --apply.
Edit parsing reuses apps/terminal/edits.py (text only, no model calls).
"""
from __future__ import annotations

import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

from skeleton.core import Answer, Assistant
from chimera_core.tiers import AllTiersFailed
from apps.terminal.edits import parse_edits, plan, unified

HERE = pathlib.Path(__file__).resolve().parent
CONFIG = HERE / "coder.toml"
SKIP = shutil.ignore_patterns(".git", ".venv", "node_modules", "__pycache__", ".env*")
_SECRET_FILE = re.compile(r"(^|/)(\.env[^/]*|id_[a-z0-9]+|[^/]*\.(pem|key))(/|$)", re.I)  # any path part, so .env/a is refused too


@dataclass
class Result:
    answer: Answer
    changes: dict[str, tuple[str | None, str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    test_output: str = ""

    @property
    def diff(self) -> str:
        return "".join(line for p, (old, new) in self.changes.items() for line in unified(p, old, new))


class Coder:
    def __init__(self, repo: str | pathlib.Path, files: list[str], test: str, *, config=CONFIG,
                 demo_models=None, assistant: Assistant | None = None) -> None:
        self.repo, self.files, self.test = pathlib.Path(repo).resolve(), list(files), shlex.split(test)
        for f in self.files:
            self._path(f)  # refuse files outside the repo before anything is read
        self.bot = assistant or Assistant(config, demo_models=demo_models)

    def ask(self, task: str) -> Result:
        out = Result(answer=None)  # type: ignore[arg-type]

        def tests_pass(answer: str) -> bool:
            out.changes, out.errors = self.changes(answer)
            if out.errors or not out.changes:
                out.test_output = "\n".join(out.errors) or "the reply had no edits"
                return False
            ok, out.test_output = self.run_tests(out.changes)
            return ok

        out.answer = self.bot.ask(task, context=self.context(), verify=tests_pass)  # last check = served answer
        return out

    def context(self) -> str:
        return "\n\n".join(f"FILE: {f}\n{self._path(f).read_text()}\nEND FILE" for f in self.files)

    def changes(self, answer: str) -> tuple[dict[str, tuple[str | None, str]], list[str]]:
        edits = parse_edits(answer, self.files[0] if len(self.files) == 1 else None)
        bad = [f"refused path: {e.path}" for e in edits if e.path and not self._safe(e.path)]
        if bad:
            return {}, bad
        return plan(edits, self._read, tuple(self.files))

    def run_tests(self, changes: dict[str, tuple[str | None, str]]) -> tuple[bool, str]:
        with tempfile.TemporaryDirectory(prefix="skeleton-coder-") as tmp:
            work = pathlib.Path(tmp) / "repo"
            shutil.copytree(self.repo, work, ignore=SKIP)
            for rel, (_, new) in changes.items():
                (work / rel).parent.mkdir(parents=True, exist_ok=True)
                (work / rel).write_text(new)
            try:
                p = subprocess.run(self.test, cwd=work, capture_output=True, text=True, timeout=120)
            except (OSError, subprocess.TimeoutExpired) as e:
                return False, type(e).__name__
            return p.returncode == 0, (p.stdout + p.stderr)[-1200:]

    def apply(self, changes: dict[str, tuple[str | None, str]]) -> None:
        for rel, (_, new) in changes.items():
            path = self._path(rel)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new)

    def _safe(self, rel: str) -> bool:
        p = (self.repo / rel).resolve()
        return p.is_relative_to(self.repo) and ".git" not in p.relative_to(self.repo).parts \
            and not _SECRET_FILE.search(p.as_posix())

    def _path(self, rel: str) -> pathlib.Path:
        if not self._safe(rel):
            raise ValueError(f"refused path: {rel}")
        return self.repo / rel

    def _read(self, rel: str) -> str | None:
        p = self._path(rel)
        return p.read_text() if p.exists() else None


def report(r: Result) -> str:
    a, lines = r.answer, []
    for i, s in enumerate(a["steps"], 1):
        tests = {True: "PASS", False: "FAIL", None: "-"}[s["verified"]]
        lines.append(f"step {i}  {s['tier']:<15} tokens {s['tokens']:>5}  ${s['dollars']:.6f}  "
                     f"saved ${s['dollars_saved']:.6f}  {s['ms']:>7.0f} ms  tests {tests}")
    lines.append(r.diff.rstrip() or "(no diff)")
    if a["verified"] is False:
        lines.append("tests still fail on the top tier:\n" + r.test_output.strip())
    lines.append(f"answered by {a['tier']}{' (cache)' if a['cache_hit'] else ''}: tokens {a['tokens']}, "
                 f"spent ${a['dollars']:.6f}, saved ${a['dollars_saved']:.6f}, {a['latency_ms']:.0f} ms")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m skeleton.apps.coder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ask = sub.add_parser("ask", help="ask a coding task; show steps and the diff")
    ask.add_argument("task")
    ask.add_argument("--repo", default=".")
    ask.add_argument("--file", action="append", required=True, help="file the task may edit (repeat)")
    ask.add_argument("--test", required=True, help='test command, e.g. "python -m pytest -q"')
    ask.add_argument("--live", action="store_true", help="real tiers (A6000 30B, then 763B) and Supabase cache")
    ask.add_argument("--no-gpu", action="store_true", dest="no_gpu",
                     help="live but Crusoe 763B only (cache -> 763B); no GPU needed")
    ask.add_argument("--apply", action="store_true", help="write the patch to the repo once the tests pass")
    sub.add_parser("demo", help="offline demo: a climb, a 30B answer and a cache hit")
    cls = sub.add_parser("class", help="a class: student 1 pays the model, students 2..N get the cache")
    cls.add_argument("--students", type=int, default=5)
    cls.add_argument("--live", action="store_true")
    cls.add_argument("--no-gpu", action="store_true", dest="no_gpu",
                     help="live but Crusoe 763B only; no GPU needed")
    args = ap.parse_args(argv)
    if args.cmd == "demo":
        from .demo import main as demo
        return demo()
    if args.cmd == "class":
        from .classroom import main as classroom
        return classroom(args.live or args.no_gpu, args.students, no_gpu=args.no_gpu)
    cfg = {**_toml(), "mode": "live"} if (args.live or args.no_gpu) else CONFIG
    if args.no_gpu:
        cfg["ladder"] = ["cloud-deepseek"]
    coder = Coder(args.repo, args.file, args.test, config=cfg)
    try:
        r = coder.ask(args.task)
    except AllTiersFailed as e:  # every tier failed or was unreachable: say so, no traceback, no made-up patch
        print(f"no tier answered: {e}", file=sys.stderr)
        return 2
    print(_vice(report(r), banner=True))
    if args.apply and r.answer["verified"]:
        coder.apply(r.changes)
        print("applied to " + ", ".join(r.changes))
    return 0 if r.answer["verified"] else 1


def _vice(text: str, banner: bool = False) -> str:
    from . import vice
    if not vice.use_color():
        return text
    return (vice.banner() + "\n" if banner else "") + vice.paint(text)


def _toml() -> dict:
    import tomllib
    return tomllib.loads(CONFIG.read_text())


if __name__ == "__main__":
    sys.exit(main())
