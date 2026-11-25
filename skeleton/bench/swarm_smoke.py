"""Live smoke run of the swarm on Crusoe only (no GPU): the 60 help-desk asks and the 40 coder asks of vs_pybot.py.

    .venv/bin/python skeleton/bench/swarm_smoke.py run [helpdesk|store|coder]   # rows -> bench/.scratch/swarm_a/<app>.jsonl
    .venv/bin/python skeleton/bench/swarm_smoke.py judge                        # grade help-desk and store rows (gemma-4-31b)
    .venv/bin/python skeleton/bench/swarm_smoke.py report                       # runs 1, 2 (run1_*, run2_*) and 3 (<app>.jsonl) side by side

Fresh cache namespace per run id (in run_id). Resumable: a row id already in the file is skipped. The key comes from
.env through chimera_core's loader and is never printed. The judge is not a ladder model.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SCRATCH = ROOT / "bench/.scratch/swarm_a"
JUDGE_MODEL = "google/gemma-4-31b-it"
SWARM_NAMES = {"crusoe-small": "Nemotron 3.5 Lightning 30B", "cloud-top": "gpt-oss-120b",
               "cloud-deepseek": "DeepSeek V4.1 Flash 763B"}


def _vp():
    from skeleton.bench import vs_pybot
    return vs_pybot


TAG = __import__("os").environ.get("SWARM_TAG", "")  # run 4a, 4b: file prefix and a fresh namespace per tag


def _run_id() -> str:
    p = SCRATCH / f"{TAG}run_id"
    SCRATCH.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(time.strftime("%Y%m%d%H%M%S"))
    return p.read_text().strip()


def store_set(seed: int = 7) -> list[dict]:
    """~60 shopper asks: 14 seed questions (asked, then again), their rewordings, and the novel ones."""
    import random
    rng = random.Random(seed)
    q = json.loads((ROOT / "skeleton/apps/store/questions.json").read_text())
    seeds = rng.sample(q["seed"], 14)
    first = [{"q": x, "kind": "seed"} for x in seeds] + [{"q": x, "kind": "novel"} for x in q["novel"]]
    later = [{"q": x, "kind": "repeat"} for x in seeds] + [{"q": p, "kind": "reworded"} for p, _ in q["paraphrases"]]
    rng.shuffle(first)
    rng.shuffle(later)
    rows = first + later
    for i, r in enumerate(rows):
        r["id"] = f"s{i:02d}"
    return rows


def blind_set() -> list[dict]:
    """The tester's old blind help-desk set (public since the PR #12 report): bench/.scratch/swarm_c/blind_set.json."""
    rows = json.loads((ROOT / "bench/.scratch/swarm_c/blind_set.json").read_text())["helpdesk"]
    return [{**r, "kind": "general", "expect": "a polite small-talk reply", "blind_kind": "smalltalk"}
            if r["kind"] == "smalltalk" else {**r, "blind_kind": r["kind"]} for r in rows]


def run(app: str) -> None:
    vp = _vp()
    out = SCRATCH / f"{TAG}{app}.jsonl"
    done = vp._done(out)
    ns = f"swarm-a-{app}-{_run_id()}"
    if app in ("helpdesk", "blind"):
        from skeleton.apps.helpdesk import helpdesk as hd
        bot = hd.make_assistant(live=True, swarm=True, namespace=ns)
        rows = vp.helpdesk_set() if app == "helpdesk" else blind_set()
    elif app == "store":
        from skeleton.apps.store import store as stm
        bot, rows = stm.make_assistant(live=True, swarm=True, namespace=ns), store_set()
    else:
        from skeleton.core import Assistant
        from skeleton.core.swarm import SWARM_LADDER, Swarm
        bot = Swarm(Assistant({"mode": "live", "namespace": ns, "ladder": SWARM_LADDER, "max_tokens": 700,
                               "instructions": vp.CODER_INSTRUCTIONS}), fallback="")
        rows = vp.coder_set()
    tracker = bot.router.tracker
    judge = getattr(getattr(bot.check, "__self__", None), "judge", None) if getattr(bot, "check", None) else None
    for r in rows:
        if r["id"] in done:
            continue
        verify = (lambda ans, fn=r["fn"]: vp.run_tests(vp.code_of(ans), fn)[0]) if app == "coder" else None
        n0 = len(tracker.events)
        j0 = judge.bot.stats()["dollars"] if judge else 0.0
        try:
            a = bot.ask(r["q"], verify=verify)
        except Exception as e:  # noqa: BLE001  a tier outage is a row, not a crash
            vp._append(out, {**r, "answer": "", "error": type(e).__name__, "tier": "error", "tried": [], "dollars": 0.0,
                             "tokens": 0, "cache_hit": False, "ms": None, "verified": None, "climbs": {}})
            continue
        climbs = Counter(e["climb_reason"] for t in tracker.events[n0:] for e in (t.events or []) if e.get("climb_reason"))
        climbs["failed_check"] += sum(1 for s in a["steps"][:-1] if s["verified"] is False)
        jd = (judge.bot.stats()["dollars"] - j0) if judge else 0.0  # the yes/no checks are spend too
        row = {**r, "answer": a["answer"], "tier": a["tier"], "tried": a["tried"], "dollars": a["dollars"],  # judge included

               "judge_dollars": jd,
               "tokens": a["tokens"], "cache_hit": a["cache_hit"], "ms": a["latency_ms"], "verified": a["verified"],
               "climbs": {k: v for k, v in climbs.items() if v}}
        if app == "coder":
            row["pass"] = bool(a["answer"]) and vp.run_tests(vp.code_of(a["answer"]), r["fn"])[0]
        vp._append(out, row)
        print(row["id"], row["tier"], row["ms"], flush=True)


def judge() -> None:
    vp = _vp()
    import skeleton.core  # noqa: F401
    from chimera_core.config import load_config
    load_config()
    from chimera_core.inference.cloud_verifier import CrusoeBackend
    from skeleton.apps.helpdesk.helpdesk import KnowledgeBase
    from skeleton.apps.store.store import Catalog
    texts = {"helpdesk": KnowledgeBase().text, "blind": KnowledgeBase().text, "store": Catalog().text}
    be = CrusoeBackend(JUDGE_MODEL)
    for app, kb in texts.items():
        path = SCRATCH / f"{TAG}{app}.jsonl"
        rows = vp._rows(path)
        for r in rows:
            if r.get("grade"):
                continue
            general = r["kind"] == "general"
            prompt = vp.JUDGE.format(kb="(not about this question: judge general correctness)" if general else kb,
                                     q=r["q"], expect=f"Right answer: {r['expect']}\n" if general else "",
                                     a=r["answer"] or "(no answer)")
            word = be.complete(prompt, max_tokens=300).strip().upper()
            r["grade"] = next((w for w in ("CORRECT", "MISS", "WRONG") if w in word), "UNGRADED")
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        print("graded", app, len(rows))


def _line(name: str, rows: list[dict], app: str) -> str:
    vp = _vp()
    if app == "coder":
        right, wrong, miss = sum(bool(r.get("pass")) for r in rows), sum(not r.get("pass") for r in rows), 0
    else:
        right = sum(r.get("grade") == "CORRECT" for r in rows)
        wrong = sum(r.get("grade") == "WRONG" for r in rows)
        miss = sum(r.get("grade") == "MISS" for r in rows)
    free = sum(r["tier"] in ("rules", "kb_lookup", "no_fact") for r in rows)
    cache = sum(bool(r["cache_hit"]) for r in rows)
    big = sum("cloud-deepseek" in r["tried"] for r in rows)
    climbs = Counter()
    for r in rows:
        climbs.update(r["climbs"])
    usd = sum(r["dollars"] for r in rows) / len(rows) * 1000
    return (f"| {app} | {name} | {len(rows)} | {right} | {wrong} | {miss} | {free} | {cache} | {big} | ${usd:.2f} | "
            f"{', '.join(f'{k} {v}' for k, v in sorted(climbs.items())) or 'none'} |")


def report() -> str:
    vp = _vp()
    lines = ["| App | Run | Asks | Right | Wrong | Miss | Free ($0, no model) | Cache hits ($0) | 763B calls | $ per 1,000 asks | Climb reasons |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for app in ("helpdesk", "blind", "store", "coder"):
        for name, f in (("1 (words only)", f"run1_{app}.jsonl"), ("2 (meaning + words)", f"run2_{app}.jsonl"),
                        ("3 (meaning + facts)", f"run3_{app}.jsonl"), ("4a (+ judge, no-fact stop)", f"4a{app}.jsonl"),
                        ("4b (repeat)", f"4b{app}.jsonl")):
            rows = vp._rows(SCRATCH / f)
            if rows:
                lines.append(_line(name, rows, app))
    return "\n".join(lines)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "run":
        for a in (sys.argv[2:] or ["helpdesk", "blind", "store", "coder"]):
            run(a)
    elif cmd == "judge":
        judge()
    else:
        print(report())
