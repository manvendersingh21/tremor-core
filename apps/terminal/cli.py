"""`chimera code`: REPL, one-shot (-m) and pipe input."""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

from .agent import Session
from .routing import MODES, Cascade

from chimera_core.config import load_config  # noqa: E402  (routing registers chimera_core)
from chimera_core.memory import Bank, PgBankStore  # noqa: E402

HELP = """/add <file>      add a file to the context      /drop [file|all]  remove one or all
/files           list the context files         /diff             git diff (or what this session changed)
/undo            undo the last write            /run <cmd>        run a command (risk-scored)
/test            run the tests                  /fix              run tests, ask the model to fix them
/tier auto|local|gpu|cloud   choose the tier    /cost             session totals per tier
/commit [msg]    git commit tracked changes     /clear            clear the screen and last output
/help            this text                      /exit             quit
Anything else is a request to the model."""


def handle(s: Session, line: str, *, test_first: bool = False) -> bool:
    """Run one input line. False means exit."""
    line = line.strip()
    if not line:
        return True
    if not line.startswith("/"):
        s.task(line, test_first=test_first)
        return True
    cmd, _, arg = line.partition(" ")
    arg = arg.strip()
    if cmd in ("/exit", "/quit"):
        return False
    if cmd == "/help":
        s.say(HELP)
    elif cmd == "/add":
        for name in arg.split():
            if s.add(name):
                s.say(f"added {name}")
    elif cmd == "/drop":
        s.files = [] if arg in ("", "all") else [f for f in s.files if f != arg]
    elif cmd == "/files":
        s.say("\n".join(s.files) or "(none)")
    elif cmd == "/diff":
        s.say(s.diff())
    elif cmd == "/undo":
        s.say(s.undo())
    elif cmd == "/run":
        ok, out = s.run(arg) if arg else (False, "usage: /run <cmd>")
        s.say(out.rstrip())
    elif cmd == "/test":
        ok, out = s.test()
        s.say(out.rstrip() + ("\nPASS" if ok else "\nFAIL"))
    elif cmd == "/fix":
        s.task("Make the failing tests pass.", test_first=True)
    elif cmd == "/tier":
        if arg in MODES:
            s.mode = arg
            s.say(f"tier: {arg}")
        else:
            s.say(f"tier is {s.mode}; use /tier auto|local|gpu|cloud")
    elif cmd == "/cost":
        s.say(s.cost())
    elif cmd == "/commit":
        s.say(s.commit(arg))
    elif cmd == "/clear":
        s.last_output = ""
        s.say("\033[2J\033[H" if s.color else "")
    else:
        s.say(f"unknown command {cmd}; /help lists them")
    return True


def make_bank(config_path, client, s: Session) -> Bank | None:
    """The solved-problem bank in Supabase, or None: no DSN in the env, no embedder on the router, or no driver."""
    cfg = load_config(config_path)
    dsn = os.environ.get(cfg.cache.dsn_env, "")
    emb = getattr(getattr(client, "router", None), "embedder", None)
    if not dsn or emb is None:
        return None
    try:
        return Bank(PgBankStore(dsn), emb, tenant=f"{cfg.cache.tenant}:terminal", verify=s.verify)
    except Exception as e:  # noqa: BLE001  e.g. the optional `postgres` extra is not installed
        print(f"bank off: {type(e).__name__}", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="chimera code", description="terminal coding agent on the cascade")
    ap.add_argument("files", nargs="*", help="files to add to the context")
    ap.add_argument("-m", "--message", help="one-shot request, then exit")
    ap.add_argument("--yes", action="store_true", help="apply edits without asking (risk >= 70 still asks)")
    ap.add_argument("--tier", choices=list(MODES), default="auto")
    ap.add_argument("--test-cmd", help="command that checks the work (default: pytest when tests exist)")
    ap.add_argument("--no-test", action="store_true")
    ap.add_argument("--test-first", action="store_true", help="run the tests before the first call and show the failure")
    ap.add_argument("--max-repairs", type=int, default=3)
    ap.add_argument("--namespace", default="terminal", help="cache namespace")
    ap.add_argument("--no-cache", action="store_true", help="skip the Supabase cache (there is no local cache)")
    ap.add_argument("--no-bank", action="store_true", help="skip the solved-problem bank (Supabase)")
    ap.add_argument("--config", help="path to chimera.toml")
    ap.add_argument("--gpu-url", default=os.environ.get("CHIMERA_GPU_URL"), help="override the gpu-small tier URL")
    ap.add_argument("--stats-json", help="write per-call stats of this run to a file")
    ap.add_argument("--cwd", default=".", help="project directory")
    a = ap.parse_args(argv)

    import logging
    logging.getLogger("neo4j").setLevel(logging.ERROR)  # driver deprecation notices are not for the user
    root = pathlib.Path(a.cwd).resolve()
    tty = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
    piped = not sys.stdin.isatty()
    try:
        client = Cascade(a.config, a.namespace, a.gpu_url, not a.no_cache)
    except Exception as e:  # noqa: BLE001
        print(f"error: cannot start the router: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    s = Session(root, client, yes=a.yes, mode=a.tier, max_repairs=a.max_repairs, color=tty,
                test_cmd="" if a.no_test else a.test_cmd)
    if a.no_test or a.test_cmd == "":
        s.test_cmd = None
    if not a.no_bank:
        s.bank = make_bank(a.config, client, s)  # after the Session: the bank's verify runs in a copy of s.root
    for f in a.files:
        s.add(f)

    results = []
    if a.message is not None:
        results.append(s.task(a.message, test_first=a.test_first))
    elif piped:
        text = sys.stdin.read()
        first = next((x for x in text.splitlines() if x.strip()), "")
        if first.startswith("/"):  # a script of slash commands and requests, one per line
            for ln in text.splitlines():
                s.say(f"chimera> {ln}")
                if not handle(s, ln, test_first=a.test_first):
                    break
        elif text.strip():
            results.append(s.task(text.strip(), test_first=a.test_first))
    else:
        try:
            import readline  # noqa: F401  line editing and history
        except ImportError:
            pass
        s.say("chimera code. /help lists commands. Tier: " + s.mode)
        while True:
            try:
                line = input("\033[1mchimera>\033[0m " if tty else "chimera> ")
            except EOFError:
                break
            except KeyboardInterrupt:
                print()
                continue
            try:
                if not handle(s, line, test_first=a.test_first):
                    break
            except KeyboardInterrupt:
                print("\n(interrupted)")
    if a.stats_json:
        calls = [c for r in results for c in r.calls]
        pathlib.Path(a.stats_json).write_text(json.dumps({
            "calls": calls, "rounds": sum(r.rounds for r in results), "applied": sum(r.applied for r in results),
            "tests_ok": results[-1].ok if results else None, "note": results[-1].note if results else "",
            "totals": {k: {"calls": t.calls, "tokens": t.tokens, "dollars": t.dollars, "baseline": t.baseline, "kept": t.kept}
                       for k, t in s.tally.items()}}, indent=1))
    if s.tally:
        print(s.cost().splitlines()[-1])
    return 0 if all(r.ok is not False for r in results) else 1
