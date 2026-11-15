"""Regrade the saved raw answers against the current tasks.jsonl (after a test fix). Rewrites `pass` in raw_*.jsonl and router.jsonl.

    .venv/bin/python bench/cost_case/regrade.py [id-prefix ...]
"""
import json, os, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench" / "datasets"))
import grade  # noqa: E402
STORE = ROOT / "bench/.scratch" / "cost_case"  # repo-local: survives restarts (never $KIROCREW_SCRATCH)
tasks = {r["id"]: r for r in map(json.loads, (pathlib.Path(__file__).parent / "tasks.jsonl").read_text().splitlines())}
pre = tuple(sys.argv[1:])
for p in sorted(STORE.glob("raw_*.jsonl")) + [STORE / "router.jsonl"]:
    if not p.exists():
        continue
    rows = [json.loads(x) for x in p.read_text().splitlines()]
    ch = 0
    for r in rows:
        if r["id"].startswith(pre) and r["answer"]:
            g = grade.grade(tasks[r["id"]], r["answer"])
            ch += g != r["pass"]
            r["pass"] = g
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))  # shortcut: not safe while a run appends to the same file
    print(p.name, "changed", ch)
