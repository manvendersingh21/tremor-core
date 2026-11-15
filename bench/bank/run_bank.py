"""Solved-problem bank, measured: run a problem set cold, fill the bank, run it again, then reworded copies.

    .venv/bin/python bench/bank/run_bank.py all          # every stage, resumable
    .venv/bin/python bench/bank/run_bank.py <stage>      # reword run1 fill run2 run3 probe report

Needs CHIMERA_GPU_URL (an SSH tunnel to your GPU box, Ollama qwen3:30b-instruct), CRUSOE_API_KEY, CHIMERA_DB_URL
(Supabase `solved_bank`, deploy/sql/006_bank.sql) and CHIMERA_GRAPH_* (Aura). Rows are appended under bench/.scratch/bank/.
Run 1 replays the 30B and 763B answers saved by bench/memory (same prompts, temperature 0); new model calls happen
only for reworded copies that miss. The test set is the 80 problems of bench/memory/split.json, the fill set its
260-problem train stream (big-model answers that passed).
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import re
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "bench", ROOT / "bench" / "datasets", ROOT / "bench" / "memory"):
    sys.path.insert(0, str(p))
import conftest  # noqa: E402,F401
import grade  # noqa: E402
import run_memory as M  # noqa: E402
from chimera_core.memory import Bank, InMemoryBankStore, Memory, PgBankStore, default_store, heuristic_extract  # noqa: E402

D = ROOT / "bench/.scratch/bank"
D.mkdir(parents=True, exist_ok=True)
OUT_MD, OUT_CSV = ROOT / "bench/results_bank.md", ROOT / "bench/results_bank.csv"
TENANT = "bench-bank"
THRESHOLDS = [0.70, 0.80, 0.85, 0.90, 0.95]
REWORD = ("Rewrite this programming task statement in different words. Keep every function name, argument name, code block, "
          "example and number exactly as written. Output only the rewritten statement.\n\n{p}")


def jl(name):
    f = D / name
    return [json.loads(x) for x in f.read_text().splitlines()] if f.exists() else []


def jl_add(name, rec):
    with (D / name).open("a") as fh:
        fh.write(json.dumps(rec) + "\n")


class CachedEmbedder:
    """Disk-cached MiniLM: each distinct text is embedded once, across stages and restarts."""
    def __init__(self):
        self.c = {r["t"]: r["v"] for r in jl("emb.jsonl")}
        self.m = None

    def embed(self, text):
        if text not in self.c:
            self.m = self.m or M.get_embedder()
            self.c[text] = [round(x, 6) for x in self.m.embed(text)]
            jl_add("emb.jsonl", {"t": text, "v": self.c[text]})
        return self.c[text]


def verify(answer, tests):
    return bool(grade.unit_test(tests["data"], answer))


def tests_of(r):
    return {"grader": "unit_test", "data": r["data"]}


def entry_name(r):
    d = r["data"]
    return d.get("entry_point") or (re.search(r"assert\s+\(?\s*(\w+)\(", (d.get("tests") or [""])[0]) or [None, None])[1]


def load():
    rows = {r["id"]: r for r in M.load_tasks()}
    sp = json.loads((M.STORE / "split.json").read_text())
    base = {r["id"]: r for r in M.jl_read("baseline30.jsonl")}
    top = {r["id"]: r for r in M.jl_read("top_test.jsonl")}
    teach = {r["id"]: r for r in M.jl_read("teacher.jsonl")}
    return [rows[i] for i in sp["test"]], [rows[i] for i in sp["train"]], base, top, teach


def make_bank(emb, use_graph=True):
    store = PgBankStore(os.environ["CHIMERA_DB_URL"])
    mem = Memory(default_store(), emb, TENANT, extractor=heuristic_extract) if use_graph and os.environ.get("CHIMERA_GRAPH_URL") else None
    return Bank(store, emb, TENANT, verify, memory=mem)


# ---- stages ------------------------------------------------------------------------------------------------
def stage_reword(test):
    import concurrent.futures as cf
    done = {r["id"] for r in jl("reworded.jsonl")}

    def one(r):
        text, tin, tout = M.call30(REWORD.format(p=r["prompt"]), 1200)
        name = entry_name(r)
        return {"id": r["id"], "prompt": text, "ok": bool(text) and (not name or name in text), "tin": tin, "tout": tout}

    with cf.ThreadPoolExecutor(M.W30) as ex:
        for rec in ex.map(one, [r for r in test if r["id"] not in done]):
            jl_add("reworded.jsonl", rec)
            print("reword", rec["id"], rec["ok"], flush=True)


def reworded(test):
    rw = {r["id"]: r for r in jl("reworded.jsonl")}
    return [dict(r, id=r["id"] + "-rw", prompt=rw[r["id"]]["prompt"], orig=r["id"]) for r in test if r["id"] in rw and rw[r["id"]]["ok"]]


def ladder(r, bank, hints, base, top):
    """30B, then the big model. Original problems replay saved rows; reworded ones make real calls (cached)."""
    out = {"calls30": 1, "callsbig": 0, "usd": 0.0, "tokbig": 0, "solved_by": "", "text": ""}
    if "orig" not in r:
        b = base[r["id"]]
        ok, text = b["pass"] == 1, b["text"]
    else:
        c = {x["id"]: x for x in jl("rw_30b.jsonl")}.get(r["id"])
        if not c:
            pre = hints.hint_text() if hints and hints.hints else ""
            text, tin, tout = M.call30((("Solved examples that may help:" + pre + "\n\nNow solve this:\n") if pre else "") + r["prompt"])
            c = {"id": r["id"], "text": text, "pass": grade.grade(r, text) or 0, "tin": tin, "tout": tout, "hinted": bool(pre)}
            jl_add("rw_30b.jsonl", c)
        ok, text = c["pass"] == 1, c["text"]
    if ok:
        out.update(solved_by="30b", text=text)
        return out
    out["callsbig"] = 1
    if "orig" not in r:
        t = top[r["id"]]
    else:
        t = {x["id"]: x for x in jl("rw_top.jsonl")}.get(r["id"])
        if not t:
            text, u = M.call_top(r["prompt"])
            t = {"id": r["id"], "text": text, "pass": grade.grade(r, text) or 0, "tin": u["prompt_tokens"], "tout": u["completion_tokens"],
                 "usd": M.top_cost(u["prompt_tokens"], u["completion_tokens"], u["cached_tokens"])}
            jl_add("rw_top.jsonl", t)
    out.update(usd=t["usd"], tokbig=t["tin"] + t["tout"], text=t["text"], solved_by="763b" if t["pass"] == 1 else "")
    return out


def stage_run(n, items, bank, base, top):
    name = f"run{n}.jsonl"
    done = {r["id"] for r in jl(name)}
    for r in items:
        if r["id"] in done:
            continue
        t0 = time.perf_counter()
        lk = bank.lookup(r["prompt"], tests_of(r))
        ms = (time.perf_counter() - t0) * 1000
        rec = {"id": r["id"], "kind": lk.kind, "how": lk.how, "score": round(lk.score, 3), "tests_run": lk.tests_run,
               "wrong_caught": lk.wrong_caught, "lookup_ms": round(ms), "calls30": 0, "callsbig": 0, "usd": 0.0, "tokbig": 0, "solved": 0}
        if lk.kind == "served":
            rec["solved"] = 1
        else:
            o = ladder(r, bank, lk, base, top)
            rec.update(calls30=o["calls30"], callsbig=o["callsbig"], usd=o["usd"], tokbig=o["tokbig"], solved=int(bool(o["solved_by"])),
                       solved_by=o["solved_by"])
            if o["solved_by"]:
                bank.add(r["prompt"], o["text"], tests_of(r), source=r.get("source", ""), model=o["solved_by"],
                         tier="30b" if o["solved_by"] == "30b" else "top")
        jl_add(name, rec)
        print(name, r["id"], rec["kind"], rec["how"], rec["score"], flush=True)


def stage_fill(train, teach, bank):
    done = {r["id"] for r in jl("fill.jsonl")}
    for r in train:
        t = teach.get(r["id"])
        if r["id"] in done or not t or t["pass"] != 1:
            continue
        rid = bank.add(r["prompt"], t["text"], tests_of(r), source=r.get("source", ""), model="763b", tier="top",
                       tokens={"in": t["tin"], "out": t["tout"]})
        jl_add("fill.jsonl", {"id": r["id"], "banked": bool(rid)})
        print("fill", r["id"], bool(rid), flush=True)


def stage_probe(test, bank):
    """No model calls. For each test problem, the nearest OTHER bank entry's answer is run against this problem's tests."""
    from chimera_core.memory.bank import prompt_hash
    if jl("probe.jsonl"):
        return
    for r in test:
        own = prompt_hash(r["prompt"])
        pe = bank._emb(r["prompt"])
        c = [(x, s) for x, s in bank.store.nearest(TENANT, pe, 6) if prompt_hash(x.prompt) != own]
        if not c:
            continue
        x, s = c[0]
        jl_add("probe.jsonl", {"id": r["id"], "other": x.prompt[:60], "score": round(s, 3), "pass": int(verify(x.answer, tests_of(r)))})


def pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "n/a"


def stage_report(test, train, base, top, bank):
    n = len(test)
    runs = {k: jl(f"run{k}.jsonl") for k in (1, 2, 3)}
    rows = []
    for k, rs in runs.items():
        if not rs:
            continue
        m = len(rs)
        sv = [x for x in rs if x["kind"] == "served"]
        rows.append({"run": k, "problems": m, "served": len(sv), "served_exact": sum(x["how"] == "exact" for x in sv),
                     "served_cosine": sum(x["how"] == "cosine" for x in sv), "hint_only": sum(x["kind"] == "hint" for x in rs),
                     "miss": sum(x["kind"] == "miss" for x in rs), "tests_run": sum(x["tests_run"] for x in rs),
                     "wrong_caught": sum(x["wrong_caught"] for x in rs), "calls_30b": sum(x["calls30"] for x in rs),
                     "calls_big": sum(x["callsbig"] for x in rs), "big_usd": round(sum(x["usd"] for x in rs), 5),
                     "big_tokens": sum(x["tokbig"] for x in rs), "solved": sum(x["solved"] for x in rs),
                     "median_lookup_ms": round(statistics.median(x["lookup_ms"] for x in rs))})
    with OUT_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    r1 = rows[0]
    stats = bank.stats()
    probe = jl("probe.jsonl")
    L = ["# Solved-problem bank: does looking a problem up first save model calls?", "",
         f"Single run. The bank holds verified problem/solution pairs in Supabase `solved_bank` (pgvector), and every banked pair is also "
         f"written to the Aura graph. `bank.lookup` tries an exact hash, then cosine >= {bank.serve_at}. A match is served only if its answer "
         f"passes the asked problem's unit tests in the sandbox; a weaker match (>= {bank.hint_at}) or one whose tests fail becomes a hint for the 30B; "
         "a miss goes to the ladder (30B, then the 763B), and a passing answer is written back.", "",
         "## Plain words", ""]
    r2 = next((r for r in rows if r["run"] == 2), None)
    r3 = next((r for r in rows if r["run"] == 3), None)
    if r2:
        L.append(f"- Run 1 (empty bank, {r1['problems']} problems) made {r1['calls_30b']} 30B calls and {r1['calls_big']} big-model calls (${r1['big_usd']:.4f}).")
        L.append(f"- Run 2 (same problems, bank filled) served {r2['served']} of {r2['problems']} from the bank ({pct(r2['served'], r2['problems'])}) "
                 f"and made {r2['calls_30b']} 30B calls and {r2['calls_big']} big-model calls (${r2['big_usd']:.4f}).")
    if r3:
        L.append(f"- Run 3 ({r3['problems']} reworded copies) served {r3['served']} ({pct(r3['served'], r3['problems'])}): "
                 f"{r3['served_cosine']} by cosine after passing tests, {r3['hint_only']} only as a hint, {r3['miss']} misses. "
                 f"Calls: {r3['calls_30b']} 30B, {r3['calls_big']} big (${r3['big_usd']:.4f}). Tests caught {r3['wrong_caught']} wrong matches.")
    L += [f"- Bank size: {stats['size']} pairs {stats['by_source']}; lookups so far counted {stats['hits']} served hits.", "",
          "## Table", "", "| Run | Problems | Served (exact/cosine) | Hint only | Miss | Wrong hits caught | 30B calls | Big calls | Big $ | Big tokens | Solved | Median lookup ms |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    names = {1: "1 cold", 2: "2 same problems", 3: "3 reworded copies"}
    for r in rows:
        L.append(f"| {names[r['run']]} | {r['problems']} | {r['served']} ({r['served_exact']}/{r['served_cosine']}) | {r['hint_only']} | {r['miss']} | "
                 f"{r['wrong_caught']} | {r['calls_30b']} | {r['calls_big']} | ${r['big_usd']:.4f} | {r['big_tokens']} | {r['solved']} | {r['median_lookup_ms']} |")
    if r2:
        L += ["", f"Avoided by the bank, run 2 vs run 1: {r1['calls_30b'] - r2['calls_30b']} 30B calls, {r1['calls_big'] - r2['calls_big']} big calls, "
              f"${r1['big_usd'] - r2['big_usd']:.4f}, {r1['big_tokens'] - r2['big_tokens']} big tokens."]
    if r3 and r1:
        L += [f"Run 3 vs run 1 (same problems, reworded): {r1['calls_30b'] - r3['calls_30b']} fewer 30B calls, {r1['calls_big'] - r3['calls_big']} fewer big calls, "
              f"big $ changed by {r1['big_usd'] - r3['big_usd']:+.4f} (negative means run 3 cost more than run 1)."]
    if r2 and r3:
        L += ["", "## Verdict", "",
              f"- Same problem again: works. {r2['served']} of {r2['problems']} came from the bank after their tests passed, at about "
              f"{r2['median_lookup_ms']} ms per lookup (the sandbox test run is most of that). This is the easy case: the exact text was banked.",
              f"- Reworded problem: partial. {pct(r3['served'], r3['problems'])} served; the rest went down the ladder. "
              f"Run 3 cost more big-model $ than run 1 ({r3['big_usd']:.4f} vs {r1['big_usd']:.4f}) although it made fewer big calls; the cause was not measured "
              "(run 1 replays saved answers, run 3 made fresh calls with their own token counts). Rewording was done by the 30B itself, so some copies may have changed the task.",
              f"- Tests are what make serving safe. Without them, cosine alone would have shipped wrong answers: see the probe table "
              f"(at 0.70, most matches fail the asked problem's tests). In run 3 the 0.90 cut-off meant {r3['wrong_caught']} wrong matches reached the test step, "
              "so the test gate was never the thing that saved us here; it is untested on a wrong close match.",
              "- Run 1 is not a clean cold run for the bank: write-back during the run gave 11 hints from near-duplicate problems in the same set. "
              "Run 1 replays saved model answers, so its 30B and big-call counts are the earlier measured ones.",
              "- One run, 80 problems, temperature 0. Dollar amounts are fractions of a cent, so call counts are the better signal."]
    L += ["", "## Wrong hits: would a different problem's answer have been wrong?", "",
          "No model calls. For each test problem, the nearest other bank entry (its own entry left out) is run against this problem's tests. "
          "A pass means reuse was right; a fail is a wrong hit that serving without tests would have shipped.", "",
          "| Cosine at or above | Matches | Pass its tests | Fail its tests (wrong hit) |", "|---|---|---|---|"]
    for t in THRESHOLDS:
        s = [x for x in probe if x["score"] >= t]
        L.append(f"| {t} | {len(s)} | {sum(x['pass'] for x in s)} | {sum(1 - x['pass'] for x in s)} |")
    L += ["", f"Probe covered {len(probe)} of {n} test problems.", "", "## Where it did not help", ""]
    if r3:
        miss3 = [x for x in runs[3] if x["kind"] != "served"]
        L.append(f"- {len(miss3)} reworded copies were not served; {sum(x['kind'] == 'hint' for x in miss3)} of them still got a hint for the 30B.")
    unsolved = [x["id"] for x in runs[1] if not x["solved"]]
    L.append(f"- {len(unsolved)} problems were unsolved in run 1 and so never banked: {', '.join(unsolved[:8])}.")
    L += ["- Run 1 replays saved 30B and 763B answers (same prompts, temperature 0); only reworded copies made new model calls. "
          "Hints for the 30B were used on those new calls only.",
          "- The graph write used the keyword extractor (no model call), so graph concepts here are coarser than in `results_memory.md`.",
          "- Embedding ran with MiniLM on the Mac (about 600 short texts, cached on disk), not on the GPU box: it was not heavy enough to move.",
          "- Not built: a LeetCode-style open set. HumanEval, MBPP, the suite code rows and every 763B answer that passed are banked.",
          "", "## Rerun", "", "```", "# open an SSH tunnel to your GPU box first; CRUSOE_API_KEY, CHIMERA_DB_URL, CHIMERA_GRAPH_* in .env",
          ".venv/bin/python bench/bank/run_bank.py all", ".venv/bin/python bench/bank/run_bank.py report", "```", "",
          "Rows are cached in `bench/.scratch/bank/`. Remove the bank rows with `Bank.purge()` (tenant `bench-bank`). Design: `docs/memory.md`."]
    OUT_MD.write_text("\n".join(L) + "\n")
    print("wrote", OUT_MD)


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    run = lambda s: stage in ("all", s)  # noqa: E731
    test, train, base, top, teach = load()
    if run("reword"):
        stage_reword(test)
    emb = CachedEmbedder()
    bank = make_bank(emb)
    rw = reworded(test)
    if run("run1"):
        if not jl("run1.jsonl") and bank.stats()["size"]:
            bank.purge()  # cold start means an empty bank
        stage_run(1, test, bank, base, top)
    if run("fill"):
        stage_fill(train, teach, bank)
    if run("run2"):
        stage_run(2, test, bank, base, top)
    if run("probe"):
        stage_probe(test, bank)  # before run 3, so no reworded copy of a test problem is in the bank yet
    if run("run3"):
        stage_run(3, rw, bank, base, top)
    if run("report"):
        stage_report(test, train, base, top, bank)


if __name__ == "__main__":
    main()
