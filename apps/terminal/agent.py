"""The agent: context, prompt, edit review, undo, run-and-repair, status line, session cost."""
from __future__ import annotations

import ast
import hashlib
import pathlib
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

from . import edits as ed
from .routing import BIG, MODES, Reply, RouterError
from .safety import approved, blocked_reason, clean_env, ignored, is_git, redact, risk

SYSTEM = (
    "You edit files in a repo. Reply with edits only, no other text.\n"
    "Small change: a line with only the file path, then\n"
    "<<<<<<< SEARCH\n(exact old lines)\n=======\n(new lines)\n>>>>>>> REPLACE\n"
    "New file or full rewrite: a line FILE: path, the whole new content, then a line END FILE.\n"
)
MAX_FILE_CHARS = 6000
MAX_MAP_CHARS = 500
OUTPUT_TAIL = 1200


def short_model(m: str) -> str:
    m = m.split("/")[-1]
    return re.sub(r"-Instruct.*$|-q4_k_m$", "", m) if m.startswith("Qwen2.5") else m


def kind(tier: str) -> str:
    return "cache" if not tier else "local" if tier in ("mac-3b", "phone-3b") else "gpu" if tier.startswith("gpu") else "cloud"


def money(x: float) -> str:
    return "$0" if x == 0 else f"${x:.5f}".rstrip("0").rstrip(".") if x < 0.01 else f"${x:.3f}"


def status_line(r: Reply) -> str:
    if r.cache:
        who = "cache (supabase)"
    else:
        who = f"{kind(r.tier)} ({short_model(r.model)})"
        if len(r.tried) > 1 and r.tried[0] != r.tier:
            who += f" after {'>'.join(dict.fromkeys(r.tried))}"
    kept = f"kept {r.kept_tokens} tok off the big model" if r.kept_tokens else "went to the big model"
    return (f"-> {who} · {r.tokens} tok · {money(r.dollars)} · {r.ms / 1000:.1f} s · "
            f"{_cache_part(r)} · {kept}")


def _cache_part(r: Reply) -> str:
    """Supabase HIT/MISS and the best cosine seen, on every turn."""
    cos = f"cos {r.cache_score:.2f}" if r.cache_score is not None else "cos -"
    if r.cache:
        return f"supabase HIT {cos}"
    return f"supabase {'unavailable' if r.cache_status == 'unavailable' else 'MISS'} {cos}"


@dataclass
class Tally:
    calls: int = 0
    tokens: int = 0
    dollars: float = 0.0
    baseline: float = 0.0
    kept: int = 0


@dataclass
class Result:
    ok: bool | None = None         # tests passed at the end; None when no tests ran
    rounds: int = 0                # repair rounds used
    applied: int = 0               # edit sets written
    calls: list[dict] = field(default_factory=list)
    note: str = ""


class Session:
    def __init__(self, root: pathlib.Path, client, *, ask: Callable[[str], str] = input,
                 say: Callable[[str], None] = print, yes: bool = False, mode: str = "auto",
                 test_cmd: str | None = None, max_repairs: int = 3, color: bool = False,
                 runner: Callable[..., subprocess.CompletedProcess] | None = None) -> None:
        self.root, self.client, self.ask, self.say = root.resolve(), client, ask, say
        self.yes, self.mode, self.max_repairs, self.color = yes, mode, max_repairs, color
        self.test_cmd = test_cmd if test_cmd is not None else self._detect_tests()
        self.files: list[str] = []
        self.undo_stack: list[dict[str, str | None]] = []
        self.tally: dict[str, Tally] = {}
        self.last_output = ""
        self._run = runner or subprocess.run

    # ---- files and context ---------------------------------------------------------------------
    def _detect_tests(self) -> str | None:
        has = (self.root / "tests").is_dir() or any(self.root.glob("test_*.py"))
        return f"{sys.executable} -m pytest -q" if has else None

    def _rel(self, p: str | pathlib.Path) -> str:
        return str(pathlib.Path(p).resolve().relative_to(self.root)) if pathlib.Path(p).is_absolute() \
            else str((self.root / p).resolve().relative_to(self.root))

    def add(self, name: str) -> bool:
        path = (self.root / name).resolve()
        why = blocked_reason(path)
        if why:
            self.say(f"refused {name}: {why}")
            return False
        try:
            rel = str(path.relative_to(self.root))
        except ValueError:
            self.say(f"refused {name}: outside the working directory")
            return False
        if not path.is_file():
            self.say(f"no such file: {name}")
            return False
        if ignored(self.root, rel):
            self.say(f"refused {name}: ignored by .gitignore")
            return False
        if rel not in self.files:
            self.files.append(rel)
        return True

    def repo_map(self) -> str:
        """File names and top-level symbols, capped. git-aware: ignored files never show up."""
        names: list[str] = []
        if is_git(self.root):
            r = subprocess.run(["git", "-C", str(self.root), "ls-files", "-co", "--exclude-standard"],
                               capture_output=True, text=True)
            names = r.stdout.split()
        else:
            names = [str(p.relative_to(self.root)) for p in sorted(self.root.rglob("*"))
                     if p.is_file() and not any(x.startswith(".") or x == "__pycache__" for x in p.relative_to(self.root).parts)
                     and not ignored(self.root, str(p.relative_to(self.root)))]
        rows = []
        for n in names[:80]:
            if blocked_reason(pathlib.Path(n)) or not n.endswith((".py", ".js", ".ts", ".go", ".rs", ".md", ".toml")):
                continue
            syms = _symbols(self.root / n) if n.endswith(".py") else []
            rows.append(n + (" [" + ", ".join(syms[:6]) + "]" if syms else ""))
        out = "\n".join(rows)
        return out if len(out) <= MAX_MAP_CHARS else out[:MAX_MAP_CHARS].rsplit("\n", 1)[0] + "\n..."

    def _file_blocks(self) -> str:
        blocks = []
        for rel in self.files:
            try:
                text = (self.root / rel).read_text(errors="replace")
            except OSError:
                continue
            blocks.append(f"--- {rel} ---\n{text[:MAX_FILE_CHARS]}")
        return redact("\n".join(blocks))

    def context_key(self) -> str:
        """Short hash of (path, content) of every context file: part of the cache namespace."""
        if not self.files:
            return ""
        h = hashlib.sha256()
        for rel in sorted(self.files):
            h.update(rel.encode() + b"\0" + (self._read(rel) or "").encode() + b"\0")
        return h.hexdigest()[:16]

    def prompt(self, request: str, failure: str = "") -> str:
        parts = [SYSTEM, "Repo:\n" + self.repo_map(), self._file_blocks()]
        if failure:
            parts.append("The last run failed with:\n" + redact(failure[-OUTPUT_TAIL:]))
        parts.append("Task: " + request)
        return "\n".join(p for p in parts if p)

    # ---- calling the cascade -------------------------------------------------------------------
    def call(self, prompt: str, floor: int, res: Result) -> Reply:
        def step(name: str, d: dict) -> None:
            if name == "decide":
                self.say(f"  . trying {d.get('tier')}")
        # A repair round adds its number to the cache key: a cached answer whose tests just failed is never served again.
        key = self.context_key() + (f":r{res.rounds}" if res.rounds else "")
        rep = self.client.generate(prompt, mode=self.mode, floor=floor, on_event=step, key=key)
        t = self.tally.setdefault(rep.tier or "cache", Tally())
        t.calls += 1
        t.tokens += rep.tokens
        t.dollars += rep.dollars
        t.baseline += rep.baseline_dollars
        t.kept += rep.kept_tokens
        res.calls.append({"tier": rep.tier or "cache", "model": rep.model, "tokens": rep.tokens, "dollars": rep.dollars,
                          "ms": round(rep.ms, 1), "cache": rep.cache, "kept": rep.kept_tokens,
                          "baseline_dollars": rep.baseline_dollars, "tried": rep.tried})
        self.say(status_line(rep))
        return rep

    def cost(self) -> str:
        rows = [f"{'tier':16} {'calls':>5} {'tokens':>8} {'$':>10} {'$ if 763B':>10} {'kept tok':>9}"]
        tot = Tally()
        for name, t in sorted(self.tally.items()):
            rows.append(f"{name:16} {t.calls:>5} {t.tokens:>8} {t.dollars:>10.5f} {t.baseline:>10.5f} {t.kept:>9}")
            tot.calls += t.calls; tot.tokens += t.tokens; tot.dollars += t.dollars; tot.baseline += t.baseline; tot.kept += t.kept
        rows.append(f"{'total':16} {tot.calls:>5} {tot.tokens:>8} {tot.dollars:>10.5f} {tot.baseline:>10.5f} {tot.kept:>9}")
        rows.append(f"saved vs an all-763B baseline ({BIG}): {money(tot.baseline - tot.dollars)}; "
                    f"{tot.kept} tokens kept off the big model")
        return "\n".join(rows)

    # ---- edits: review, apply, undo ------------------------------------------------------------
    def _read(self, rel: str) -> str | None:
        p = self.root / rel
        return p.read_text(errors="replace") if p.is_file() else None

    def _color(self, line: str) -> str:
        if not self.color:
            return line
        c = "32" if line.startswith("+") and not line.startswith("+++") else \
            "31" if line.startswith("-") and not line.startswith("---") else "36" if line.startswith("@@") else ""
        return f"\033[{c}m{line}\033[0m" if c else line

    def review(self, state: dict) -> bool:
        """Show the colored diff, run the write gate, ask y/n/a. True when the edits may be written."""
        for rel, (old, new) in state.items():
            for ln in ed.unified(rel, old, new):
                self.say(self._color(ln.rstrip("\n")))
        for rel in state:
            path = (self.root / rel).resolve()
            why = blocked_reason(path)
            if why:
                self.say(f"refused write to {rel}: {why}")
                return False
            outside = not path.is_relative_to(self.root)
            if not approved(risk(f"write file {path}", outside_cwd=outside), f"write {path}", self.ask, self.say):
                self.say(f"refused write to {rel}")
                return False
            if not outside and ignored(self.root, rel) and (self._read(rel) is None):
                self.say(f"note: {rel} is ignored by .gitignore")
        if self.yes:
            return True
        try:
            a = self.ask("apply? [y]es/[n]o/[a]lways: ").strip().lower()
        except EOFError:
            a = "n"
        if a.startswith("a"):
            self.yes = True
        return a.startswith(("y", "a"))

    def write(self, state: dict) -> None:
        self.undo_stack.append({rel: old for rel, (old, _) in state.items()})
        for rel, (_, new) in state.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(new)
            if rel not in self.files:
                self.files.append(rel)

    def undo(self) -> str:
        if not self.undo_stack:
            return "nothing to undo"
        snap = self.undo_stack.pop()
        for rel, old in snap.items():
            p = self.root / rel
            if old is None:
                p.unlink(missing_ok=True)
                if rel in self.files:
                    self.files.remove(rel)
            else:
                p.write_text(old)
        return "undid: " + ", ".join(snap)

    def diff(self) -> str:
        if is_git(self.root):
            return subprocess.run(["git", "-C", str(self.root), "diff"], capture_output=True, text=True).stdout or "(no changes)"
        return "(not a git repo; edits are shown before writing and /undo reverts them)"

    def commit(self, msg: str) -> str:
        if not is_git(self.root):
            return "not a git repo"
        subprocess.run(["git", "-C", str(self.root), "add", "-u"], capture_output=True)
        r = subprocess.run(["git", "-C", str(self.root), "commit", "-m", msg or "chimera code edits"],
                           capture_output=True, text=True)
        return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else "nothing to commit"

    # ---- run and test --------------------------------------------------------------------------
    def run(self, cmd: str, timeout: int = 120) -> tuple[bool, str]:
        v = risk(cmd)
        if not approved(v, cmd, self.ask, self.say):
            return False, "refused by the risk gate"
        try:
            p = self._run(cmd, shell=True, cwd=self.root, capture_output=True, text=True, timeout=timeout, env=clean_env())
        except subprocess.TimeoutExpired:
            return False, f"timed out after {timeout} s"
        out = redact((p.stdout or "") + (p.stderr or ""))
        self.last_output = out
        return p.returncode == 0, out

    def test(self) -> tuple[bool, str]:
        if not self.test_cmd:
            return True, "no tests found"
        return self.run(self.test_cmd)

    # ---- one request, with at most `max_repairs` repair rounds ---------------------------------
    def task(self, request: str, *, test_first: bool = False) -> Result:
        res = Result()
        floor, failure = 0, ""
        if test_first and self.test_cmd:
            ok, out = self.test()
            if ok:
                self.say("tests already pass")
            else:
                failure = out
        for rnd in range(self.max_repairs + 1):
            try:
                rep = self.call(self.prompt(request, failure), floor, res)
            except RouterError as e:
                res.note = str(e)
                self.say(f"error: {e}")
                return res
            found = ed.parse_edits(rep.text, self.files[0] if len(self.files) == 1 else None)
            if not found and rnd < self.max_repairs and self.test_cmd:
                failure = "Your reply had no edit blocks. Reply only with SEARCH/REPLACE or FILE blocks."
                self.say("no edits in the reply")
                res.rounds += 1
                if self.mode == "auto" and floor < len(MODES["auto"]) - 1:
                    floor += 1
                continue
            if not found:
                self.say(rep.text.strip())
                res.note = "answer without edits"
                return res
            state, errs = ed.plan(found, self._read, tuple(self.files))
            if state:
                if not self.review(state):
                    res.note = "edits refused"
                    return res
                self.write(state)
                res.applied += 1
            if errs:
                failure = "Your edit could not be applied: " + "; ".join(errs)
                self.say(failure)
            else:
                if not self.test_cmd:
                    return res
                ok, out = self.test()
                res.ok = ok
                if ok:
                    self.say("tests pass")
                    return res
                failure = out
                self.say("tests fail" + ("" if rnd < self.max_repairs else ": out of repair rounds"))
            if rnd == self.max_repairs:
                break
            res.rounds += 1
            if self.mode == "auto" and floor < len(MODES["auto"]) - 1:
                floor += 1  # the answer at this tier did not work: the next call starts one tier up
        if res.ok is None and self.test_cmd:
            res.ok = False
        return res


def _symbols(path: pathlib.Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except (OSError, SyntaxError):
        return []
    return [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
