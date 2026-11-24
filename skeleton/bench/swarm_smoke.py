"""Live smoke run of the swarm on Crusoe only (no GPU): the 60 help-desk asks and the 40 coder asks of vs_pybot.py.

    .venv/bin/python skeleton/bench/swarm_smoke.py run [helpdesk|coder]   # rows -> bench/.scratch/swarm_a/<app>.jsonl
    .venv/bin/python skeleton/bench/swarm_smoke.py judge                  # grade help-desk rows with gemma-4-31b
    .venv/bin/python skeleton/bench/swarm_smoke.py report                 # the table for skeleton/RESULTS.md

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


def _run_id() -> str:
    p = SCRATCH / "run_id"
    SCRATCH.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(time.strftime("%Y%m%d%H%M%S"))
    return p.read_text().strip()


def run(app: str) -> None:
    vp = _vp()
    out = SCRATCH / f"{app}.jsonl"
    done = vp._done(out)
    ns = f"swarm-a-{app}-{_run_id()}"
    if app == "helpdesk":
        from skeleton.apps.helpdesk import helpdesk as hd
        bot, rows = hd.make_assistant(live=True, swarm=True, namespace=ns), vp.helpdesk_set()
    else:
        from skeleton.core import Assistant
        from skeleton.core.swarm import SWARM_LADDER, Swarm
        bot = Swarm(Assistant({"mode": "live", "namespace": ns, "ladder": SWARM_LADDER, "max_tokens": 700,
                               "instructions": vp.CODER_INSTRUCTIONS}), fallback="")
        rows = vp.coder_set()
    tracker = bot.router.tracker
    for r in rows:
        if r["id"] in done:
            continue
        verify = (lambda ans, fn=r["fn"]: vp.run_tests(vp.code_of(ans), fn)[0]) if app == "coder" else None
        n0 = len(tracker.events)
        try:
            a = bot.ask(r["q"], verify=verify)
        except Exception as e:  # noqa: BLE001  a tier outage is a row, not a crash
            vp._append(out, {**r, "answer": "", "error": type(e).__name__, "tier": "error", "tried": [], "dollars": 0.0,
                             "tokens": 0, "cache_hit": False, "ms": None, "verified": None, "climbs": {}})
            continue
        climbs = Counter(e["climb_reason"] for t in tracker.events[n0:] for e in (t.events or []) if e.get("climb_reason"))
        climbs["failed_check"] += sum(1 for s in a["steps"][:-1] if s["verified"] is False)
        row = {**r, "answer": a["answer"], "tier": a["tier"], "tried": a["tried"], "dollars": a["dollars"],
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
    kb, be = KnowledgeBase().text, CrusoeBackend(JUDGE_MODEL)
    path = SCRATCH / "helpdesk.jsonl"
    rows = vp._rows(path)
    for r in rows:
        if r.get("grade"):
            continue
        general = r["kind"] == "general"
        prompt = vp.JUDGE.format(kb="(not about this question: judge general correctness)" if general else kb, q=r["q"],
                                 expect=f"Right answer: {r['expect']}\n" if general else "", a=r["answer"] or "(no answer)")
        word = be.complete(prompt, max_tokens=300).strip().upper()
        r["grade"] = next((w for w in ("CORRECT", "MISS", "WRONG") if w in word), "UNGRADED")
        r["judge_tokens"] = sum(be.last_usage.get(k, 0) for k in ("prompt_tokens", "completion_tokens"))
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print("graded", len(rows))


def report() -> str:
    vp = _vp()
    lines = ["| App | Asks | Right | Wrong | Miss | Free modules ($0, no model) | Cache hits ($0) | 763B calls | $ per 1,000 | Climb reasons |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for app in ("helpdesk", "coder"):
        rows = vp._rows(SCRATCH / f"{app}.jsonl")
        if not rows:
            continue
        if app == "helpdesk":
            right = sum(r.get("grade") == "CORRECT" for r in rows)
            wrong = sum(r.get("grade") == "WRONG" for r in rows)
            miss = sum(r.get("grade") == "MISS" for r in rows)
        else:
            right, wrong, miss = sum(bool(r.get("pass")) for r in rows), sum(not r.get("pass") for r in rows), 0
        free = sum(r["tier"] in ("rules", "kb_lookup") for r in rows)
        cache = sum(bool(r["cache_hit"]) for r in rows)
        big = sum("cloud-deepseek" in r["tried"] for r in rows)
        climbs = Counter()
        for r in rows:
            climbs.update(r["climbs"])
        usd = sum(r["dollars"] for r in rows) / len(rows) * 1000
        lines.append(f"| {app} | {len(rows)} | {right} | {wrong} | {miss} | {free} | {cache} | {big} | ${usd:.2f} | "
                     f"{', '.join(f'{k} {v}' for k, v in sorted(climbs.items())) or 'none'} |")
    return "\n".join(lines)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "run":
        for a in (sys.argv[2:] or ["helpdesk", "coder"]):
            run(a)
    elif cmd == "judge":
        judge()
    else:
        print(report())
