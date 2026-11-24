"""Independent test: the answer swarm vs PyBot, the old skeleton and the 763B alone (docs/research/swarm_vs_pybot.md).

    python bench/run_swarm_vs_pybot.py run SYSTEM SET --code DIR [--env FILE]   # SYSTEM: pybot old_a old_b direct swarm
    python bench/run_swarm_vs_pybot.py judge --code DIR [--env FILE]            # google/gemma-4-31b-it grades help desk + store rows
    python bench/run_swarm_vs_pybot.py report                                   # markdown tables from the rows

SET: hd60 (helpdesk_set(), seed 7), blind (blind_set.json "helpdesk"), store (blind_set.json "store"), coder (coder_set()).
--code DIR is a `git archive` of one version (skeleton/, packages/, conftest.py, chimera.example.toml); each system runs in its
own process. Keys come from the environment (CRUSOE_API_KEY, CHIMERA_DB_URL); --env reads only those two names from a file and
never prints them. Everything is written under bench/.scratch/swarm_c/ (git-ignored). Rows are resumable (one JSON per ask).
Systems: old_a = old skeleton + rules, 763B only; old_b = old skeleton + rules, crusoe-small -> cloud-top -> cloud-deepseek;
direct = every ask straight to the 763B with the knowledge base (no cache, no rules, no check); swarm = PR #11.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import pathlib
import re
import statistics
import sys
import threading
import time
import tomllib

HERE = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(os.environ.get("SWARM_C_OUT", HERE / ".scratch/swarm_c"))
BLIND = OUT / "blind_set.json"
PYBOT_REPO = pathlib.Path(os.environ.get("PYBOT_REPO", HERE / ".scratch/pybot/repo"))
LADDER_B = ["crusoe-small", "cloud-top", "cloud-deepseek"]
JUDGE_MODEL = "google/gemma-4-31b-it"
JUDGE_PRICE = (0.00014, 0.0004)  # dollars per 1k tokens in/out (list price)
SMALLTALK_EXPECT = "a short friendly reply (greeting, you're welcome or goodbye); no invented facts"
EV = threading.local()


def load_env(path: str | None) -> None:
    """Copy only CRUSOE_API_KEY and CHIMERA_DB_URL from an env file into the environment. Values are never printed."""
    if not path:
        return
    for line in pathlib.Path(path).read_text().splitlines():
        k, _, v = line.partition("=")
        if k.strip() in ("CRUSOE_API_KEY", "CHIMERA_DB_URL"):
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def load_vs(code: pathlib.Path):
    sys.path.insert(0, str(code))
    spec = importlib.util.spec_from_file_location("vs_pybot", code / "skeleton/bench/vs_pybot.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vs_pybot"] = mod
    spec.loader.exec_module(mod)
    mod.PYBOT = PYBOT_REPO
    return mod


def scratch_config(code: pathlib.Path) -> str:
    """A copy of chimera.example.toml with N+1 memory off. chimera.toml and the example are never edited."""
    p = OUT / "chimera_scratch.toml"
    p.write_text((code / "chimera.example.toml").read_text() + "\n[memory]\nenabled = false\n")
    return str(p)


def rows_for(vs, sset: str) -> list[dict]:
    if sset == "hd60":
        return vs.helpdesk_set()
    if sset == "coder":
        return vs.coder_set()
    b = json.loads(BLIND.read_text())
    if sset == "store":
        return [{**r, "means": r["q"]} for r in b["store"]]
    out = []
    for r in b["helpdesk"]:
        r = {**r, "means": r.get("fact", r["q"])}
        if r["kind"] == "smalltalk":
            r["expect"] = SMALLTALK_EXPECT
        out.append(r)
    return out


def app_of(sset: str) -> str:
    return {"store": "store", "coder": "coder"}.get(sset, "helpdesk")


def install_event_capture() -> None:
    """Collect the pool's `call` events (climb_reason) for each ask, without touching the code under test."""
    import skeleton.core  # noqa: F401  registers chimera_core
    from chimera_core.tiers import TierPool
    orig = TierPool.generate

    def gen(self, prompt, complexity=None, on_event=None, context=""):
        def ev(step, data):
            if step in ("call", "draft"):
                getattr(EV, "log", []).append(data)
            if on_event:
                on_event(step, data)
        return orig(self, prompt, complexity, ev, context)

    TierPool.generate = gen


def build(system: str, sset: str, run_id: str, cfgpath: str, code: pathlib.Path):
    """Return (ask(row) -> Answer-like dict). One namespace per system, app and run."""
    app, ns = app_of(sset), f"swarm-c-{run_id}-{system}-{sset}"
    ladder = ["cloud-deepseek"] if system in ("old_a", "direct") else LADDER_B
    if app == "coder" and system == "swarm":
        from skeleton.apps.coder.coder import make_swarm
        return make_swarm({"mode": "live", "namespace": ns, "max_tokens": 700, "chimera_config": cfgpath,
                           "instructions": "You write Python for students. Reply with one ```python code block that defines the "
                                           "requested function and nothing else. No prints, no input(), no explanation."}, namespace=ns)
    if app != "coder" and system == "swarm":
        if app == "store":
            from skeleton.apps.store.store import make_assistant
        else:
            from skeleton.apps.helpdesk.helpdesk import make_assistant
        os.environ["CHIMERA_CONFIG"] = cfgpath
        return make_assistant(live=True, swarm=True, namespace=ns)
    if app == "coder":
        from skeleton.core import Assistant
        bot = Assistant({"mode": "live", "namespace": ns, "ladder": ladder, "max_tokens": 700, "chimera_config": cfgpath,
                         "instructions": "You write Python for students. Reply with one ```python code block that defines the "
                                         "requested function and nothing else. No prints, no input(), no explanation."})
        if system == "direct":
            bot.router.shared = None  # no cache at all
        return bot
    if app == "store":
        from skeleton.apps.store import store as mod
        know = mod.Catalog()
        base, demo = mod.CONFIG, mod.DEMO_MODELS
    else:
        from skeleton.apps.helpdesk import helpdesk as mod
        know = mod.KnowledgeBase()
        base, demo = mod.CONFIG, mod.DEMO_MODELS
    cfg = {**tomllib.loads(base.read_text()), "mode": "live", "namespace": ns, "ladder": ladder, "chimera_config": cfgpath}
    from skeleton.core import Assistant
    bot = Assistant(cfg, knowledge=know, verify=None if system == "direct" else know.grounded, demo_models=demo)
    if system == "direct":
        bot.router.shared = None  # no cache at all
    elif app == "helpdesk":
        from skeleton.core.rules import Rules, RulesFirst
        bot = RulesFirst(bot, Rules.for_faq(know.data))
    return bot


def run(system: str, sset: str, code: pathlib.Path, env: str | None) -> None:
    load_env(env)
    vs = load_vs(code)
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("CHIMERA_TELEMETRY", str(OUT / "telemetry.jsonl"))
    rid = OUT / "run_id"
    rid.write_text(rid.read_text()) if rid.exists() else rid.write_text(str(int(time.time())))
    out = OUT / "rows" / f"{system}_{sset}.jsonl"
    done = vs._done(out)
    rows = [r for r in rows_for(vs, sset) if r["id"] not in done]
    if system == "pybot":
        for r in rows:
            reply, ms, module = vs.pybot_reply(r["q"])
            row = {**r, "system": system, "answer": reply, "ms": ms, "module": module, "dollars": 0.0, "tokens": 0,
                   "cache_hit": False, "tier": "pybot", "tried": [], "reasons": []}
            if sset == "coder":
                row["pass"], row["test_out"] = vs.run_tests(vs.code_of(reply), r["fn"])
            vs._append(out, row)
            print(row["id"], module, flush=True)
        return
    cfgpath = scratch_config(code)
    install_event_capture()
    bot = build(system, sset, rid.read_text().strip(), cfgpath, code)
    for r in rows:
        EV.log = []
        verify = None
        if sset == "coder" and system != "direct":
            verify = lambda ans, fn=r["fn"]: vs.run_tests(vs.code_of(ans), fn)[0]  # noqa: E731
        try:
            a = bot.ask(r["q"], verify=verify) if sset == "coder" else bot.ask(r["q"])
        except Exception as e:  # noqa: BLE001  a tier outage is a row, not a crash
            vs._append(out, {**r, "system": system, "answer": "", "error": type(e).__name__, "ms": None, "dollars": 0.0,
                             "tokens": 0, "cache_hit": False, "tier": "error", "tried": [], "reasons": list(_reasons())})
            continue
        row = {**r, "system": system, "answer": a["answer"], "ms": a["latency_ms"], "dollars": a["dollars"],
               "tokens": a["tokens"], "cache_hit": a["cache_hit"], "tier": a["tier"], "tried": a["tried"],
               "verified": a.get("verified"), "reasons": list(_reasons()), "n_steps": len(a.get("steps", []))}
        if sset == "coder":
            row["pass"], row["test_out"] = vs.run_tests(vs.code_of(a["answer"]), r["fn"])
        vs._append(out, row)
        print(row["id"], row["tier"], row["ms"], flush=True)


def _reasons():
    return [e["climb_reason"] for e in getattr(EV, "log", []) if e.get("climb_reason")]


def judge(code: pathlib.Path, env: str | None) -> None:
    load_env(env)
    vs = load_vs(code)
    import skeleton.core  # noqa: F401  registers chimera_core
    from chimera_core.inference.cloud_verifier import CrusoeBackend
    from skeleton.apps.helpdesk.helpdesk import KnowledgeBase
    from skeleton.apps.store.store import Catalog
    texts = {"helpdesk": KnowledgeBase().text, "store": Catalog().text}
    be = CrusoeBackend(JUDGE_MODEL)
    spent = 0.0
    for path in sorted((OUT / "rows").glob("*.jsonl")):
        sset = path.stem.split("_", 1)[1] if path.stem.split("_")[0] != "old" else path.stem.split("_", 2)[2]
        if sset == "coder":
            continue
        rows, changed = vs._rows(path), False
        for r in rows:
            if r.get("grade") in ("CORRECT", "MISS", "WRONG"):
                continue
            general = r["kind"] in ("general", "smalltalk")
            if general and re.search(r"\bi don'?t know\b", r["answer"], re.I):  # an abstention on small talk or trivia is a miss
                r["grade"], changed = "MISS", True
                continue
            prompt = vs.JUDGE.format(kb="(not about this question: judge general correctness)" if general else texts[app_of(sset)],
                                     q=r["q"], expect=f"Right answer: {r['expect']}\n" if general else "", a=r["answer"] or "(no answer)")
            word = be.complete(prompt, max_tokens=1200).strip().upper()
            r["grade"] = next((w for w in ("CORRECT", "MISS", "WRONG") if w in word), "UNGRADED")
            u = be.last_usage
            spent += u.get("prompt_tokens", 0) / 1000 * JUDGE_PRICE[0] + u.get("completion_tokens", 0) / 1000 * JUDGE_PRICE[1]
            changed = True
        if changed:
            path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        print(path.name, "graded", flush=True)
    print(f"judge spend about ${spent:.4f}")


# ---- report -----------------------------------------------------------------------------------------------------------
SYSTEMS = [("pybot", "PyBot"), ("old_a", "Old skeleton (a) 763B only"), ("old_b", "Old skeleton (b) Crusoe ladder"),
           ("direct", "763B alone"), ("swarm", "Swarm (PR #11)")]
SETS = [("hd60", "Help desk 60"), ("blind", "Blind help desk 60"), ("store", "Blind store 20"), ("coder", "Coder 40")]


def stats(rows: list[dict], sset: str) -> dict:
    n = len(rows)
    key = (lambda r: bool(r.get("pass"))) if sset == "coder" else (lambda r: r.get("grade") == "CORRECT")
    ms = [r["ms"] for r in rows if r.get("ms") is not None]
    d = sum(r.get("dollars", 0.0) for r in rows)
    reasons = collections.Counter(x for r in rows for x in r.get("reasons", []))
    fails = sum(1 for r in rows if r.get("n_steps", 1) > 1)  # asks where the check failed and the ask climbed
    return {"n": n, "correct": sum(map(key, rows)),
            "wrong": n - sum(map(key, rows)) if sset == "coder" else sum(r.get("grade") == "WRONG" for r in rows),
            "miss": 0 if sset == "coder" else sum(r.get("grade") == "MISS" for r in rows),
            "free": sum(1 for r in rows if r.get("dollars", 0.0) == 0.0 and r.get("tier") != "error"),
            "hits": sum(bool(r.get("cache_hit")) for r in rows),
            "b763": sum(t == "cloud-deepseek" for r in rows for t in r.get("tried", [])),
            "per1k": d / n * 1000 if n else 0.0, "ms": round(statistics.median(ms)) if ms else None,
            "429": reasons.get("http_429", 0), "reasons": dict(reasons), "check_climbs": fails,
            "errors": sum(r.get("tier") == "error" for r in rows)}


def report() -> str:
    parts = []
    for sset, title in SETS:
        parts += [f"### {title}", "", "| System | Correct | Wrong | Miss | $0 answers | Cache hits | 763B calls | $ per 1,000 | Median ms | 429 | Climb reasons |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for sys_, name in SYSTEMS:
            p = OUT / "rows" / f"{sys_}_{sset}.jsonl"
            rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
            if not rows:
                continue
            s = stats(rows, sset)
            why = ", ".join(f"{k} {v}" for k, v in sorted(s["reasons"].items())) + (f"; failed check {s['check_climbs']}" if s["check_climbs"] else "")
            parts.append(f"| {name} | {s['correct']}/{s['n']} | {s['wrong']} | {s['miss']} | {s['free']} | {s['hits']} | {s['b763']} | "
                         f"${s['per1k']:.2f} | {s['ms']} | {s['429']} | {why or '-'} |")
        parts.append("")
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "judge", "report"])
    ap.add_argument("system", nargs="?", choices=[s for s, _ in SYSTEMS])
    ap.add_argument("sset", nargs="?", choices=[s for s, _ in SETS])
    ap.add_argument("--code", default=str(HERE.parent))
    ap.add_argument("--env")
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.system, a.sset, pathlib.Path(a.code).resolve(), a.env)
    elif a.cmd == "judge":
        judge(pathlib.Path(a.code).resolve(), a.env)
    else:
        md = report()
        (OUT / "results.md").write_text(md)
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
