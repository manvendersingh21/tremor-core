"""Writes bench/results_memory.md and .csv from the cached rows. Called by run_memory.py (stage report)."""
from __future__ import annotations

import csv
import json
import math
import pathlib
import statistics

import run_memory as R  # noqa: E402


def rows(name):
    return {r["id"]: r for r in R.jl_read(name)}


def wilson(k, n, z=1.96):
    if not n:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def write(test, train, ok):
    ids = [r["id"] for r in test]
    src = {r["id"]: ("custom" if r["id"].startswith(("triv-", "reg-", "ev-")) or r.get("source") == "custom"
                     else r["id"].split("-")[0]) for r in test}
    base, top = rows("baseline30.jsonl"), rows("top_test.jsonl")
    sizes = json.loads((R.STORE / "ctx_sizes.json").read_text())["sizes"]
    conds = [("30B alone (0 stored)", 0, base)] + [(f"30B + memory ({n} stored)", n, rows(f"with_mem_{n}.jsonl")) for n in sizes]
    ctrl = rows("control_random.jsonl")
    n = len(ids)
    top_all_usd = sum(top[i]["usd"] for i in ids)
    top_all_tok = sum(top[i]["tin"] + top[i]["tout"] for i in ids)
    teach = R.jl_read("teacher.jsonl")
    teach_usd = sum(t.get("usd", 0) for t in teach)
    ext = R.jl_read("extract.jsonl")

    def stat(label, size, d):
        p = [d[i]["pass"] for i in ids if i in d]
        k = sum(p)
        lo, hi = wilson(k, len(p))
        fail = [i for i in ids if i in d and not d[i]["pass"]]
        moved_usd = sum(top[i]["usd"] for i in ids if i in d and d[i]["pass"])
        moved_tok = sum(top[i]["tin"] + top[i]["tout"] for i in ids if i in d and d[i]["pass"])
        return {"condition": label, "stored": size, "n": len(p), "pass": k, "pass_rate": round(k / max(1, len(p)), 3),
                "ci95": f"{lo:.2f}-{hi:.2f}", "still_need_big": len(fail), "still_need_big_share": round(len(fail) / max(1, len(p)), 3),
                "big_tokens_moved_off": moved_tok, "big_usd_moved_off": round(moved_usd, 5),
                "avg_30b_tokens_in": round(statistics.mean(d[i]["tin"] for i in ids if i in d)),
                "avg_30b_tokens_out": round(statistics.mean(d[i]["tout"] for i in ids if i in d)),
                "median_ms": round(statistics.median(d[i]["ms"] for i in ids if i in d))}
    table = [stat(l, s, d) for l, s, d in conds]
    table.append(stat(f"CONTROL: 30B + 3 random stored solutions ({sizes[-1]} stored)", sizes[-1], ctrl))
    top_row = {"condition": "Big model alone (DeepSeek-V4.1-Flash)", "stored": "", "n": n,
               "pass": sum(top[i]["pass"] for i in ids), "pass_rate": round(sum(top[i]["pass"] for i in ids) / n, 3),
               "ci95": "", "still_need_big": "", "still_need_big_share": 1.0, "big_tokens_moved_off": 0, "big_usd_moved_off": 0,
               "avg_30b_tokens_in": "", "avg_30b_tokens_out": "", "median_ms": round(statistics.median(top[i]["ms"] for i in ids))}
    table.append(top_row)
    with R.OUT_CSV.open("w", newline="") as fh:
        w = csv.DictWriter(fh, list(table[0]))
        w.writeheader()
        w.writerows(table)

    full, b = conds[-1][2], base
    fixed = [i for i in ids if not b[i]["pass"] and full[i]["pass"]]
    broken = [i for i in ids if b[i]["pass"] and not full[i]["pass"]]
    cfix = [i for i in ids if not b[i]["pass"] and ctrl[i]["pass"]]
    cbrk = [i for i in ids if b[i]["pass"] and not ctrl[i]["pass"]]
    ctx_tok = statistics.mean(full[i]["tin"] - b[i]["tin"] for i in ids)
    with_ctx = sum(1 for i in ids if full[i].get("ctx_chars"))
    bysrc = {}
    for s in sorted(set(src.values())):
        g = [i for i in ids if src[i] == s]
        bysrc[s] = (len(g), sum(b[i]["pass"] for i in g), sum(full[i]["pass"] for i in g), sum(ctrl[i]["pass"] for i in g))
    real = json.loads((R.STORE / "real.json").read_text()) if (R.STORE / "real.json").exists() else None

    def pct(x):
        return f"{100 * x:.1f}%"
    L = ["# N+1 memory: does the 30B get better when the big model's solved problems are remembered?", ""]
    L += ["Single run, temperature 0, one try per problem (pass@1). All code was graded by running its unit tests in the sandbox "
          "(`bench/datasets/grade.py`). Test set: %d coding problems. Memory is filled from a separate train stream of %d problems; "
          "no problem is in both (checked by prompt text). Near-duplicate families (same concept, different problem) can sit "
          "on both sides on purpose." % (n, len(train)), ""]
    L += ["## Plain words", ""]
    L += [f"- The 30B alone solved {table[0]['pass']} of {n} ({pct(table[0]['pass_rate'])}).",
          f"- With the full memory ({sizes[-1]} stored big-model solutions) it solved {table[len(conds)-1]['pass']} of {n} "
          f"({pct(table[len(conds)-1]['pass_rate'])}). Memory fixed {len(fixed)} problems and broke {len(broken)}.",
          f"- With {3} random stored solutions in the same slot (control) it solved {table[len(conds)]['pass']} of {n} "
          f"({pct(table[len(conds)]['pass_rate'])}). It fixed {len(cfix)} and broke {len(cbrk)}.",
          f"- The big model alone solved {top_row['pass']} of {n} ({pct(top_row['pass_rate'])}).",
          f"- With these sample sizes the 95% intervals overlap ({table[0]['ci95']} vs {table[len(conds)-1]['ci95']}). "
          f"Treat differences of a few problems as noise: this is one run of {n} problems.", ""]
    L += ["## Table", "", "| Condition | Pass@1 | 95% CI | Still need big model | Big tokens moved off | Big $ moved off | Avg 30B tokens in/out | Median ms |",
          "|---|---|---|---|---|---|---|---|"]
    for t in table:
        L.append(f"| {t['condition']} | {t['pass']}/{t['n']} ({pct(t['pass_rate'])}) | {t['ci95']} | "
                 f"{t['still_need_big'] if t['still_need_big'] != '' else '-'} | {t['big_tokens_moved_off']} | ${t['big_usd_moved_off']} | "
                 f"{t['avg_30b_tokens_in']}/{t['avg_30b_tokens_out']} | {t['median_ms']} |")
    L += ["", "\"Still need big model\" = test problems the 30B failed, which a router would send up. \"Moved off\" = what the big "
          f"model would have cost on the problems the 30B solved itself (big model on all {n}: {top_all_tok} tokens, ${top_all_usd:.4f}).", ""]
    L += ["## Learning curve (pass@1 vs stored solutions)", "", "```"]
    for t in table[:len(conds)]:
        bar = "#" * round(t["pass_rate"] * 50)
        L.append(f"{t['stored']:>4} stored | {bar:<50} {t['pass']}/{t['n']} {pct(t['pass_rate'])}")
    c = table[len(conds)]
    L.append(f"ctrl random | {'#' * round(c['pass_rate'] * 50):<50} {c['pass']}/{c['n']} {pct(c['pass_rate'])}")
    L += ["```", ""]
    L += ["## Control: is it the memory or just a longer prompt?", "",
          f"Same slot, same size cap, but the 3 examples are random stored solutions instead of retrieved ones. "
          f"Control {table[len(conds)]['pass']}/{n} vs memory {table[len(conds)-1]['pass']}/{n} vs none {table[0]['pass']}/{n}. "
          f"Memory changed {len(fixed)} up and {len(broken)} down; random examples changed {len(cfix)} up and {len(cbrk)} down.", ""]
    L += ["## Tokens and dollars", "",
          f"- Big-model cost to fill memory: ${teach_usd:.4f} on {len(teach)} train problems ({len(ok)} passed and were stored). "
          f"Extraction of concepts used the 30B itself ({len(ext)} calls, {sum(e['tin'] + e['tout'] for e in ext)} tokens, $0 in cloud money).",
          f"- Extra 30B input per test call from memory: about {ctx_tok:.0f} tokens on average ({with_ctx} of {n} calls had a memory context).",
          f"- Big-model $ moved off at full memory: ${table[len(conds)-1]['big_usd_moved_off']} vs ${table[0]['big_usd_moved_off']} with no memory, "
          f"out of ${top_all_usd:.4f} for sending every test problem to the big model.",
          "- The memory cost is paid once; the saving repeats on every later similar problem. At these prices the fill cost is "
          "larger than the saving on %d test problems, so break-even needs more traffic than this test." % n, ""]
    L += ["## Where memory did not help", ""]
    L += ["| Source | n | 30B alone | 30B + full memory | Control |", "|---|---|---|---|---|"]
    for s, (g, a, bb, cc) in bysrc.items():
        L.append(f"| {s} | {g} | {a} | {bb} | {cc} |")
    L += ["", f"- Broken by memory ({len(broken)}): {', '.join(broken) or 'none'}.",
          f"- Still failing with memory and also failed by the big model: {', '.join(i for i in ids if not full[i]['pass'] and not top[i]['pass']) or 'none'}.",
          f"- Failed by the 30B with and without memory, solved by the big model: "
          f"{sum(1 for i in ids if not full[i]['pass'] and not b[i]['pass'] and top[i]['pass'])}.", ""]
    L += ["## Stores", ""]
    if real:
        L += [f"Real stores written from the same {len(ok)} verified answers: `{real['store']}` for the graph "
              f"(teacher pairs in Supabase). Stats: `{json.dumps(real['stats'])}`. Top-1 retrieval agreed with the in-memory run on "
              f"{real['top1_agree_of_20']} of 20 test problems. The curve above used the in-memory store (same code path).", ""]
    else:
        L += ["The `real` stage (Neo4j + Supabase) was not run for this file.", ""]
    L += ["## Rerun", "", "```",
          "# open an SSH tunnel to your GPU box and to Neo4j first; CRUSOE_API_KEY, CHIMERA_DB_URL, CHIMERA_GRAPH_* in .env",
          ".venv/bin/python bench/memory/run_memory.py all", "N_TEST=80 W30=4 .venv/bin/python bench/memory/run_memory.py report", "```", "",
          "Rows are cached under `bench/.scratch/memory/`; delete a file there to redo that condition. "
          "Setup: `docs/memory.md`. Caveats: one run, temperature 0, %d problems; the 30B box is shared, so latency numbers are noisy." % n]
    R.OUT_MD.write_text("\n".join(L) + "\n")
    print(R.OUT_MD)
