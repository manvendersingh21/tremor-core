"""Tables for bench/results_backend_v3.md: the tuned-30B reruns next to the runs before tuning.

    .venv/bin/python bench/backend_v3_report.py [ladder|suite|terminal|bank|faults ...]   # prints markdown

Reads only git-ignored rows: bench/.scratch/backend_v3/ (this run) and the older folders it compares with
(bench/.scratch/company_cost/ repeats, bench/.scratch/suite_*.jsonl, bench/terminal_*.json). Makes no model call.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "bench"), str(ROOT / "bench/datasets")]
# bench/company_cost/report.py (ladder_pass, bank_run, spread, pct), loaded by path: bench/memory/report.py has the same name
_spec = importlib.util.spec_from_file_location("company_cost_report", ROOT / "bench/company_cost/report.py")
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

V3 = ROOT / "bench/.scratch/backend_v3"
OLD = ROOT / "bench/.scratch/company_cost"
jl, spread, pct = R.jl, R.spread, R.pct


def reps(folder: pathlib.Path, kind: str) -> list[pathlib.Path]:
    return [d for d in sorted(folder.glob(f"{kind}_r*")) if (d / "purged.json").exists()]


# ---- ladder ----------------------------------------------------------------------------------------------------
def gpu_calls(folder: pathlib.Path) -> dict:
    """Every GPU 30B call in a repeat's telemetry: time per call and errors (a 90 s timeout shows as TimeoutError)."""
    ev = [e for t in jl(folder / "backend_telemetry.jsonl") for e in t.get("events", [])
          if e.get("step") == "call" and e.get("tier") == "gpu-small"]
    ok = [e["ms"] for e in ev if e.get("ok")]
    return {"n": len(ev), "p50": pct(ok, .5), "p90": pct(ok, .9), "max": max(ok, default=0),
            "errors": collections.Counter(e.get("error") for e in ev if not e.get("ok")), "over90": sum(m >= 90_000 for m in ok)}


def ladder_stats(folder: pathlib.Path) -> dict:
    rows = jl(folder / "backend_rows.jsonl")
    out = {}
    for m in ("BASE", "COLD", "WARM"):
        rs = [r for r in rows if r["pass"] == m]
        x = R.ladder_pass(rs)
        x["share"] = collections.Counter(r["path"] for r in rs)
        x["wrong_cache"] = sum(1 for r in rs if r["cache_source"] and r["grade"] == 0)
        x["empty_or_failed"] = sum(1 for r in rs if r["path"] == "failed")
        out[m] = x
    out["gpu"] = gpu_calls(folder)
    return out


def ladder() -> list[str]:
    new = [ladder_stats(d) for d in reps(V3 / "repeats", "ladder")]
    old = [ladder_stats(d) for d in reps(OLD, "ladder")]
    L = ["| Pass | Run | 763B calls | GPU 30B calls | Cache hits | 763B tokens | 763B $ | Graded correct | Wrong cache answers | p50 ms | p90 ms | Calls >= 90 s | Errors |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in ("BASE", "COLD", "WARM"):
        for name, rs in (("before tuning, 3 repeats", old), ("**tuned, 3 repeats**", new)):
            xs = [r[m] for r in rs]
            if not xs:
                continue
            L.append(f"| {m} | {name} | {spread([x['big_calls'] for x in xs])} | {spread([x['gpu_calls'] for x in xs])} | "
                     f"{spread([x['hits'] for x in xs])} | {spread([x['big_tok'] for x in xs], '{:.0f}')} | "
                     f"{spread([x['usd'] for x in xs], '${:.5f}')} | {spread([x['correct'] for x in xs])} of {xs[0]['graded']} | "
                     f"{spread([x['wrong_cache'] for x in xs])} | {spread([x['p50'] for x in xs], '{:.0f}')} | "
                     f"{spread([x['p90'] for x in xs], '{:.0f}')} | {spread([x['slow'] for x in xs])} | {spread([x['errors'] for x in xs])} |")
    L += ["", "Per repeat (tuned):", "", "| Pass | Repeat | Answered by | 763B tokens | 763B $ | Correct | p50 ms | p90 ms |",
          "|---|---|---|---|---|---|---|---|"]
    for m in ("BASE", "COLD", "WARM"):
        for i, r in enumerate(new, 1):
            x = r[m]
            share = ", ".join(f"{k} {v}" for k, v in sorted(x["share"].items(), key=lambda kv: -kv[1]))
            L.append(f"| {m} | {i} | {share} | {x['big_tok']} | ${x['usd']:.5f} | {x['correct']}/{x['graded']} | {x['p50']:.0f} | {x['p90']:.0f} |")
    for name, rs in (("before tuning", old), ("tuned", new)):
        if rs:
            cut_t = [100 * (1 - r["COLD"]["big_tok"] / r["BASE"]["big_tok"]) for r in rs]
            cut_d = [100 * (1 - r["COLD"]["usd"] / r["BASE"]["usd"]) for r in rs]
            L.append(f"\nCOLD against BASE, {name}: 763B tokens cut {spread(cut_t)}%, 763B $ cut {spread(cut_d)}%.")
    L += ["", "GPU 30B calls inside the ladder (every call, from telemetry; timeout 90 s):", "",
          "| Run | Repeat | 30B calls | p50 ms | p90 ms | max ms | >= 90 s | errors |", "|---|---|---|---|---|---|---|---|"]
    for name, rs in (("before tuning", old), ("tuned", new)):
        for i, r in enumerate(rs, 1):
            g = r["gpu"]
            L.append(f"| {name} | {i} | {g['n']} | {g['p50']:.0f} | {g['p90']:.0f} | {g['max']:.0f} | {g['over90']} | "
                     f"{dict(g['errors']) or 0} |")
    return L


# ---- suite -----------------------------------------------------------------------------------------------------
def suite() -> list[str]:
    import run_suite as S  # noqa: PLC0415
    rows = {r["id"]: r for r in jl(S.SUITE)}
    runs = {"TOP (763B only, before)": jl(ROOT / "bench/.scratch/suite_TOP.jsonl"),
            "POOL before tuning": jl(ROOT / "bench/.scratch/suite_POOL.jsonl"),
            "**POOL tuned**": jl(V3 / "suite/suite_POOL.jsonl")}
    L = ["| Run | Items | 763B calls | 763B tokens | 763B $ | Pass (tests, exact, choice) | p50 ms | p90 ms | Sum of latencies s | Errors | Empty answers | Answered by |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, rs in runs.items():
        if not rs:
            continue
        tu = [S.top_usage(r) for r in rs]
        g = [r["grade"] for r in rs if rows[r["id"]]["grader"] not in ("pair", "llm") and r["grade"] is not None]
        lat = [r["latency_ms"] for r in rs]
        L.append(f"| {name} | {len(rs)} | {sum(1 for t in tu if t[0] or t[1])} | {sum(t[0] + t[1] for t in tu):,} | "
                 f"${sum(t[2] for t in tu):.4f} | {sum(g)}/{len(g)} | {pct(lat, .5):.0f} | {pct(lat, .9):.0f} | "
                 f"{sum(lat) / 1000:.0f} | {sum(bool(r['error']) for r in rs)} | {sum(not r['answer'].strip() for r in rs)} | "
                 f"{json.dumps(dict(collections.Counter(r['tier'] for r in rs)))} |")
    new = {r["id"]: r for r in runs["**POOL tuned**"]}
    if new:
        L += ["", "Per source (tuned POOL vs POOL before tuning vs TOP): pass on graded items, median ms, 763B calls", "",
              "| Source/type | n | Pass TOP | Pass POOL before | Pass POOL tuned | Median ms TOP / before / tuned | 763B calls before / tuned |",
              "|---|---|---|---|---|---|---|"]
        maps = {k: {r["id"]: r for r in v} for k, v in runs.items()}
        keys = sorted({(rows[i]["source"], rows[i]["type"]) for i in new})
        for s, t in keys:
            ids = [i for i in new if (rows[i]["source"], rows[i]["type"]) == (s, t)]
            cells = []
            for k in runs:
                g = [maps[k][i]["grade"] for i in ids if i in maps[k] and rows[i]["grader"] not in ("pair", "llm")
                     and maps[k][i]["grade"] is not None]
                cells.append(f"{sum(g)}/{len(g)}" if g else "n/a")
            med = " / ".join(f"{statistics.median([maps[k][i]['latency_ms'] for i in ids if i in maps[k]] or [0]):.0f}" for k in runs)
            big = " / ".join(str(sum(1 for i in ids if i in maps[k] and any(S.top_usage(maps[k][i])[:2])))
                             for k in list(runs)[1:])
            L.append(f"| {s}/{t} | {len(ids)} | {' | '.join(cells)} | {med} | {big} |")
        cs = S.cache_stats([rows[i] for i in new], new)
        L += ["", f"Cache on the suite (tuned): {cs['dup_true_hit']} of {cs['dup_b']} real duplicates served, "
              f"{cs['neg_hit'] + cs['dup_wrong_hit'] + cs['other_hit']} wrong-source hits."]
        g30 = [r["per_tier"]["gpu-small"]["latency_ms"] for r in new.values() if "gpu-small" in r["per_tier"]]
        e30 = sum(r["per_tier"]["gpu-small"]["errors"] for r in new.values() if "gpu-small" in r["per_tier"])
        L.append(f"GPU 30B attempts (tuned): {len(g30)}, time per attempt p50 {pct(g30, .5):.0f} ms, p90 {pct(g30, .9):.0f} ms, "
                 f"max {max(g30, default=0):.0f} ms, errors {e30}.")
    return L


# ---- terminal --------------------------------------------------------------------------------------------------
def terminal() -> list[str]:
    old = json.loads((ROOT / "bench/terminal_auto.json").read_text())
    cloud = json.loads((ROOT / "bench/terminal_cloud.json").read_text())
    new = sorted(jl(ROOT / "bench/.scratch/terminal-agent/v3nobank.jsonl"), key=lambda r: r["id"])
    warm = sorted(jl(ROOT / "bench/.scratch/terminal-agent/v3auto.jsonl"), key=lambda r: r["id"])
    L = ["| Run | Passed | Fully on the 30B | Reached the 763B | Calls | Repair rounds | Tokens | 763B $ | Model s (sum) | Median s per task |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for name, rs in (("763B only (before)", cloud), ("ladder before tuning (no bank then)", old),
                     ("**ladder tuned, bank off**", new), ("ladder tuned, bank on (filled by earlier runs)", warm)):
        if not rs:
            continue
        n = len(rs)
        L.append(f"| {name} | {sum(r['passed'] for r in rs)}/{n} | {sum(r['passed'] and not r['reached_big'] for r in rs)} | "
                 f"{sum(r['reached_big'] for r in rs)} | {sum(r['calls'] for r in rs)} | {sum(r['repair_rounds'] for r in rs)} | "
                 f"{sum(r['tokens'] for r in rs)} | ${sum(r['dollars'] for r in rs):.5f} | {sum(r['agent_ms'] for r in rs) / 1000:.0f} | "
                 f"{statistics.median(r['agent_ms'] for r in rs) / 1000:.1f} |")
    if new:
        o = {r["id"]: r for r in old}
        L += ["", "| # | Task | Tuned: pass | tiers | s | Before: pass | tiers | s |", "|---|---|---|---|---|---|---|---|"]
        for r in new:
            b = o.get(r["id"], {})
            L.append(f"| {r['id']} | {r['task']} | {'yes' if r['passed'] else 'NO'} | {r['tiers']} | {r['agent_ms'] / 1000:.1f} | "
                     f"{'yes' if b.get('passed') else 'NO'} | {b.get('tiers', '')} | {b.get('agent_ms', 0) / 1000:.1f} |")
    return L


# ---- bank ------------------------------------------------------------------------------------------------------
def bank() -> list[str]:
    L = ["| Run | Repeats | Served (exact/cosine) | Hint only | Miss | 30B calls | 763B calls | 763B $ | Solved | Median lookup ms |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for n, label in ((2, "2 same problems"), (3, "3 reworded copies")):
        for name, folder in (("before tuning", OLD), ("**tuned**", V3 / "repeats")):
            rs = [R.bank_run(jl(d / f"run{n}.jsonl")) for d in reps(folder, "bank")]
            if not rs:
                continue
            L.append(f"| {label}, {name} | {len(rs)} | {spread([r['served'] for r in rs])} "
                     f"({spread([r['exact'] for r in rs])}/{spread([r['cosine'] for r in rs])}) | {spread([r['hint'] for r in rs])} | "
                     f"{spread([r['miss'] for r in rs])} | {spread([r['calls30'] for r in rs])} | {spread([r['callsbig'] for r in rs])} | "
                     f"{spread([r['usd'] for r in rs], '${:.4f}')} | {spread([r['solved'] for r in rs])} | "
                     f"{spread([r['lookup_ms'] for r in rs], '{:.0f}')} |")
    w = [sum(1 for x in jl(d / f"run{n}.jsonl") if x["kind"] == "served" and not x["solved"])
         for d in reps(V3 / "repeats", "bank") for n in (2, 3)]
    L.append(f"\nServed but wrong (tuned, all repeats, runs 2 and 3): {sum(w)}.")
    return L


# ---- faults ----------------------------------------------------------------------------------------------------
def faults() -> list[str]:
    rows = jl(V3 / "faults.jsonl")
    L = ["| Case | Variant | Calls | Answered | Right | Empty answers | Failed (error, no answer) | Answered by | Call ms (median) | Heal s | Note |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    by = collections.defaultdict(list)
    for r in rows:
        by[(r["case"], r["variant"])].append(r)
    for (c, v), rs in by.items():
        heal = [r["heal_s"] for r in rs if r.get("heal_s") is not None]
        note = []
        if c in ("tunnel", "hung"):
            nxt = collections.Counter(r["next_call"]["tier"] for r in rs)
            note.append("next call: " + ", ".join(f"{k} {n}" for k, n in nxt.items()))
            note.append("30B errors: " + ", ".join(sorted({str(x["error"]) for r in rs for x in r["calls"] if not x["ok"]})))
        if c == "ratelimit":
            note.append("upstream: " + "; ".join(",".join(map(str, r["upstream"])) or "none sent" for r in rs))
        if c in ("supabase", "neo4j"):
            note.append(f"cache: {dict(collections.Counter(r['cache_status'] for r in rs))}; memory retrieve ms "
                        f"{[r['memory_ms'] for r in rs]}")
        L.append(f"| {c} | {v} | {len(rs)} | {sum(not r['empty'] for r in rs)} | {sum(r['right'] for r in rs)} | "
                 f"{sum(r['empty'] and not r['error'] for r in rs)} | {sum(bool(r['error']) for r in rs)} | "
                 f"{dict(collections.Counter(r['tier'] for r in rs))} | "
                 f"{statistics.median(r['ms'] for r in rs):.0f} | {spread(heal) if heal else '-'} | {'; '.join(note)} |")
    return L


if __name__ == "__main__":
    for part in sys.argv[1:] or ["ladder", "suite", "terminal", "bank", "faults"]:
        print(f"\n### {part}\n")
        print("\n".join({"ladder": ladder, "suite": suite, "terminal": terminal, "bank": bank, "faults": faults}[part]()))
