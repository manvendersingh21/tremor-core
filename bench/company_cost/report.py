"""Company cost story: writes bench/results_company_cost.md from the repeat rows and the measured cost files.

    .venv/bin/python bench/company_cost/report.py

Repeat rows: bench/.scratch/company_cost/ (bench/company_cost/run_repeats.py). Prices and pass rates are the measured
ones in bench/results_cost_case.md and bench/results_cost_case_h200.md; each constant below names its source.
"""
from __future__ import annotations

import json
import math
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "bench/.scratch/company_cost"
MD = ROOT / "bench/results_company_cost.md"
DAYS = 30
VOLUMES = (100_000, 1_000_000, 10_000_000)

# ---- measured inputs ---------------------------------------------------------------------------------------
H200_HOUR = 4.54  # $ per hour, Modal GPU meter (results_cost_case_h200.md); CPU and memory meters not included
H200_DAY = 24 * H200_HOUR  # always on: $108.96
H200_CAP = {64: 301 / 16.7 * 86400, 32: 301 / 23.0 * 86400}  # calls per day at 100% busy: 301 calls in 16.7 s / 23.0 s
H200_FULL = {c: H200_DAY / cap * 1000 for c, cap in H200_CAP.items()}  # $ per 1k calls with the GPU always full
PLAN_UTIL = 0.5  # sizing: an H200 is planned at half its measured top rate, for peaks (assumption)
# $ per 1k calls by difficulty, list price on measured tokens (results_cost_case.md)
PRICE = {"763B": {"all": 0.1576, "trivial": 0.0696, "everyday": 0.1241, "hard": 0.3190},
         "GPT-5.5": {"all": 4.02, "trivial": 1.60, "everyday": 2.52, "hard": 9.45}}
PASS = {"763B": "286/301 = 95%", "GPT-5.5": "60/60 = 100% (60-item subset)"}
# 30B on the H200 (concurrency 1): failures by difficulty, 31 of 301 (results_cost_case_h200.md)
FAILS_30B = {"trivial": 2, "everyday": 13, "hard": 16}
N_TASKS = 301
FAIL_RATE = sum(FAILS_30B.values()) / N_TASKS
SUPABASE_MONTH = 25.0  # Pro plan base fee; compute add-ons for a busier DB not included (not measured)


def h200_per_1k(util: float, conc: int = 64) -> float:
    """$ per 1,000 calls for one always-on H200 that is busy `util` of the day (0 < util <= 1)."""
    return H200_FULL[conc] / util


def break_even_util(api_per_1k: float, conc: int = 64) -> float:
    """Share of the day an always-on H200 must be busy to cost the same per call as the API."""
    return H200_FULL[conc] / api_per_1k


def h200_count(calls_per_day: float, conc: int = 64, plan_util: float = PLAN_UTIL) -> int:
    """H200s needed to serve `calls_per_day` at `plan_util` of the measured top rate (at least 1 if any calls)."""
    return math.ceil(calls_per_day / (H200_CAP[conc] * plan_util)) if calls_per_day > 0 else 0


def escalation_per_1k(model: str) -> float:
    """$ per 1k escalated calls: the big model's price weighted by where the 30B fails (mostly hard tasks)."""
    n = sum(FAILS_30B.values())
    return sum(PRICE[model][d] * k for d, k in FAILS_30B.items()) / n


def monthly(calls_per_day: float, big: str, served_free: float = 0.0, conc: int = 64) -> dict:
    """One month (30 days) of the cascade: cache/bank serve `served_free` of calls at $0, the 30B on always-on
    H200s answers the rest, and the 30B's failures (caught by tests) are re-asked of `big`."""
    to_30b = calls_per_day * (1 - served_free)
    n = h200_count(to_30b, conc)
    gpu = n * H200_DAY * DAYS
    esc_calls = to_30b * FAIL_RATE
    esc = esc_calls * DAYS * escalation_per_1k(big) / 1000
    db = SUPABASE_MONTH
    return {"h200s": n, "gpu": gpu, "escalated_per_day": esc_calls, "escalation": esc, "db": db,
            "total": gpu + esc + db, "busy": to_30b / (n * H200_CAP[conc]) if n else 0.0}


def api_only(calls_per_day: float, model: str) -> float:
    return calls_per_day * DAYS * PRICE[model]["all"] / 1000


# ---- repeat rows --------------------------------------------------------------------------------------------
def jl(p: pathlib.Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def spread(xs: list[float], fmt: str = "{:.1f}") -> str:
    """mean ± sd (min-max) over repeats; one value prints alone."""
    if not xs:
        return "n/a"
    if len(xs) == 1:
        return fmt.format(xs[0])
    sd = statistics.stdev(xs)
    return f"{fmt.format(statistics.mean(xs))} ± {fmt.format(sd)} ({fmt.format(min(xs))}-{fmt.format(max(xs))})"


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else 0.0


def cache_reps() -> list[dict]:
    rows = jl(OUT / "cache.jsonl")
    out = []
    for k in sorted({r["rep"] for r in rows}):
        b = [r for r in rows if r["rep"] == k and r["kind"] == "B"]
        s = lambda name: [r for r in b if r["set"] == name]  # noqa: E731
        out.append({"rep": k, "n": len(b), "hits": sum(r["hit"] for r in b),
                    "exact": sum(r["source"] == "exact" for r in b), "cosine": sum(r["source"] == "vector" for r in b),
                    "repeat": sum(r["hit"] for r in s("repeat")), "format": sum(r["hit"] for r in s("format")),
                    "paraphrase": sum(r["hit"] for r in s("paraphrase")), "near_miss": sum(r["hit"] for r in s("near_miss")),
                    "wrong": sum(r["wrong"] for r in b), "unavailable": sum(r["status"] != "ok" for r in b),
                    "p50": pct([r["ms"] for r in b], .5), "p90": pct([r["ms"] for r in b], .9)})
    return out


def bank_run(rows: list[dict]) -> dict:
    sv = [x for x in rows if x["kind"] == "served"]
    return {"n": len(rows), "served": len(sv), "exact": sum(x["how"] == "exact" for x in sv),
            "cosine": sum(x["how"] == "cosine" for x in sv), "hint": sum(x["kind"] == "hint" for x in rows),
            "miss": sum(x["kind"] == "miss" for x in rows), "wrong_caught": sum(x["wrong_caught"] for x in rows),
            "calls30": sum(x["calls30"] for x in rows), "callsbig": sum(x["callsbig"] for x in rows),
            "usd": sum(x["usd"] for x in rows), "solved": sum(x["solved"] for x in rows),
            "lookup_ms": statistics.median(x["lookup_ms"] for x in rows) if rows else 0}


def bank_reps() -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {2: [], 3: []}
    for d in sorted(OUT.glob("bank_r*")):
        if not (d / "purged.json").exists():
            continue  # an unfinished repeat is not reported
        for n in (2, 3):
            out[n].append(bank_run(jl(d / f"run{n}.jsonl")))
    return out


def ladder_pass(rows: list[dict]) -> dict:
    lat = [r["latency_ms"] for r in rows]
    g = [r["grade"] for r in rows if r["grade"] is not None]
    return {"n": len(rows), "big_calls": sum(1 for r in rows if r["big_in"] + r["big_out"]),
            "gpu_calls": sum(r["gpu_call"] for r in rows), "hits": sum(bool(r["cache_source"]) for r in rows),
            "big_tok": sum(r["big_in"] + r["big_out"] for r in rows), "usd": sum(r["dollars"] for r in rows),
            "correct": sum(g), "graded": len(g), "p50": pct(lat, .5), "p90": pct(lat, .9),
            "slow": sum(x >= 90_000 for x in lat), "errors": sum(bool(r["error"]) for r in rows)}


def ladder_reps() -> list[dict]:
    out = []
    for d in sorted(OUT.glob("ladder_r*")):
        if not (d / "purged.json").exists():
            continue
        rows = jl(d / "backend_rows.jsonl")
        out.append({m: ladder_pass([r for r in rows if r["pass"] == m]) for m in ("BASE", "COLD", "WARM")})
    return out


# ---- report -------------------------------------------------------------------------------------------------
def money(x: float) -> str:
    s = "-" if x < 0 else ""
    return f"{s}${abs(x):,.0f}" if abs(x) >= 100 else f"{s}${abs(x):,.2f}"


def per_1k_table() -> list[str]:
    u_m, u_g = break_even_util(PRICE["763B"]["all"]), break_even_util(PRICE["GPT-5.5"]["all"])
    L = ["| Tier | $ per 1,000 calls | Pass on 301 coding tasks | Source |", "|---|---|---|---|",
         "| Supabase cache hit (exact or cosine 0.97) | $0 in tokens | 0 wrong in the repeats below | this file |",
         "| Solved-problem bank hit (served after its tests pass) | $0 in tokens, plus one test run on CPU | 0 wrong served | this file, `results_bank.md` |"]
    for u in (1.0, 0.5, 0.1, 0.01):
        L.append(f"| 30B on one H200, busy {u:.0%} of the day (concurrency 64) | ${h200_per_1k(u):.3f} | 270/301 = 90% | "
                 "`results_cost_case_h200.md` |")
    L += [f"| 30B on one H200, busy 100% (concurrency 32) | ${H200_FULL[32]:.3f} | 271/301 = 90% | `results_cost_case_h200.md` |",
          "| 30B on one H200, one request at a time | $1.089 | 270/301 = 90% | `results_cost_case_h200.md` |",
          "| 30B on the shared V100 (Akash), one request at a time | $11.02 | 269/301 = 89% | `results_cost_case.md` |",
          f"| DeepSeek-V4.1-Flash 763B (Crusoe list price) | ${PRICE['763B']['all']:.4f} | {PASS['763B']} | `results_cost_case.md` |",
          f"| GPT-5.5 (list price) | ${PRICE['GPT-5.5']['all']:.2f} | {PASS['GPT-5.5']} | `results_cost_case.md` |"]
    L += ["", "An idle H200 still bills: an always-on H200 is $4.54 x 24 = **$108.96 a day** with or without calls. "
          "So its price per call is the full-GPU price divided by how busy it is: "
          f"`$ per 1k = ${H200_FULL[64]:.4f} / busy share` at concurrency 64.", "",
          "### Break-even: how busy the H200 must be", "",
          "`break-even busy share = H200 $ per 1k when full / API $ per 1k`", "",
          "| Against | API $ per 1k | Concurrency 64 (full: $%.4f) | Concurrency 32 (full: $%.4f) |" % (H200_FULL[64], H200_FULL[32]),
          "|---|---|---|---|",
          f"| 763B | ${PRICE['763B']['all']:.4f} | {u_m:.0%} busy | {break_even_util(PRICE['763B']['all'], 32):.0%} busy |",
          f"| GPT-5.5 | ${PRICE['GPT-5.5']['all']:.2f} | {u_g:.1%} busy | {break_even_util(PRICE['GPT-5.5']['all'], 32):.1%} busy |", "",
          f"One H200 at concurrency 64 serves about {H200_CAP[64] / 1e6:.2f} million short coding calls a day at 100% busy. "
          f"Busy {u_g:.1%} of that is about {u_g * H200_CAP[64]:,.0f} calls a day: above that, one H200 is cheaper per call than GPT-5.5. "
          f"Against the 763B it needs about {u_m * H200_CAP[64]:,.0f} calls a day ({u_m:.0%} busy)."]
    return L


def projection(served_free: float) -> list[str]:
    L = [f"| Coding calls a day | GPT-5.5 only | 30B + GPT-5.5 for failures | Saved vs GPT-5.5 | 763B only | 30B + 763B for failures | "
         "Saved vs 763B | H200s (busy) |", "|---|---|---|---|---|---|---|---|"]
    for d in VOLUMES:
        g, m = api_only(d, "GPT-5.5"), api_only(d, "763B")
        cg, cm = monthly(d, "GPT-5.5", served_free), monthly(d, "763B", served_free)
        L.append(f"| {d:,} | {money(g)} | {money(cg['total'])} | {money(g - cg['total'])} ({1 - cg['total'] / g:.0%}) | {money(m)} | "
                 f"{money(cm['total'])} | {money(m - cm['total'])} ({1 - cm['total'] / m:+.0%}) | {cg['h200s']} ({cg['busy']:.0%}) |")
    return L


def worked(d: int = 1_000_000) -> list[str]:
    c = monthly(d, "GPT-5.5")
    e = escalation_per_1k("GPT-5.5")
    return [f"Worked example, {d:,} calls a day, no cache or bank hits, failures to GPT-5.5:", "",
            "```",
            f"GPT-5.5 only   = {d:,} x 30 x ${PRICE['GPT-5.5']['all']:.2f} / 1000                    = {money(api_only(d, 'GPT-5.5'))}",
            f"H200s          = ceil({d:,} / ({H200_CAP[64]:,.0f} x {PLAN_UTIL}))                 = {c['h200s']}",
            f"GPU            = {c['h200s']} x $108.96 x 30                                   = {money(c['gpu'])}",
            f"failures       = {d:,} x {FAIL_RATE:.3f} (31 of 301 fail)                = {c['escalated_per_day']:,.0f} a day",
            f"failure price  = GPT-5.5 $ per 1k weighted by where the 30B fails     = ${e:.2f}",
            f"escalation     = {c['escalated_per_day']:,.0f} x 30 x ${e:.2f} / 1000                       = {money(c['escalation'])}",
            f"database       = Supabase Pro base fee                                = {money(c['db'])}",
            f"cascade total  = GPU + escalation + database                          = {money(c['total'])}",
            "```"]


def cache_section() -> list[str]:
    reps = cache_reps()
    if not reps:
        return ["Not run yet."]
    L = ["| Repeat | Asked | Hits | Exact | Cosine | Same text | Case/spacing | Prefix added | Near-miss hits | Wrong | DB unavailable | Lookup p50 / p90 ms |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in reps:
        L.append(f"| {r['rep']} | {r['n']} | {r['hits']} | {r['exact']} | {r['cosine']} | {r['repeat']}/18 | {r['format']}/18 | "
                 f"{r['paraphrase']}/18 | {r['near_miss']}/6 | {r['wrong']} | {r['unavailable']} | {r['p50']:.0f} / {r['p90']:.0f} |")
    L.append(f"| **mean ± sd (range)** | 60 | {spread([r['hits'] for r in reps])} | {spread([r['exact'] for r in reps])} | "
             f"{spread([r['cosine'] for r in reps])} | | | | {spread([r['near_miss'] for r in reps])} | {spread([r['wrong'] for r in reps])} | | "
             f"{spread([r['p50'] for r in reps], '{:.0f}')} / {spread([r['p90'] for r in reps], '{:.0f}')} |")
    return L


def bank_section() -> list[str]:
    reps = bank_reps()
    if not reps[2]:
        return ["Not run yet."]
    L = ["| Run | Repeat | Served (exact/cosine) | Hint only | Miss | 30B calls | 763B calls | 763B $ | Solved | Median lookup ms |",
         "|---|---|---|---|---|---|---|---|---|---|",
         "| 2 same problems | earlier single run | 75 (75/0) | 2 | 3 | 5 | 5 | $0.0026 | 75 | 472 |"]
    for n, name in ((2, "2 same problems"), (3, "3 reworded copies")):
        if n == 3:
            L.append("| 3 reworded copies | earlier single run | 24 (0/24) | 40 | 16 | 56 | 7 | $0.0065 | 75 | 336 |")
        for i, r in enumerate(reps[n], 1):
            L.append(f"| {name} | {i} | {r['served']} ({r['exact']}/{r['cosine']}) | {r['hint']} | {r['miss']} | {r['calls30']} | "
                     f"{r['callsbig']} | ${r['usd']:.4f} | {r['solved']} | {r['lookup_ms']:.0f} |")
        rs = reps[n]
        L.append(f"| **{name}** | **mean ± sd (range)** | {spread([r['served'] for r in rs])} | {spread([r['hint'] for r in rs])} | "
                 f"{spread([r['miss'] for r in rs])} | {spread([r['calls30'] for r in rs])} | {spread([r['callsbig'] for r in rs])} | "
                 f"{spread([r['usd'] for r in rs], '${:.4f}')} | {spread([r['solved'] for r in rs])} | {spread([r['lookup_ms'] for r in rs], '{:.0f}')} |")
    return L


def ladder_section() -> list[str]:
    reps = ladder_reps()
    if not reps:
        return ["Not run yet."]
    L = ["| Pass | Repeat | 763B calls | GPU 30B calls | Cache hits | 763B tokens | 763B $ | Graded correct | p50 ms | p90 ms | Calls >= 90 s | Errors |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|",
         "| COLD | earlier single run (v2) | 14 | 51 | 5 | 5956 | $0.00615 | 48/48 | 8594 | 21758 | 0 | 0 |"]
    for m in ("BASE", "COLD", "WARM"):
        for i, r in enumerate(reps, 1):
            x = r[m]
            L.append(f"| {m} | {i} | {x['big_calls']} | {x['gpu_calls']} | {x['hits']} | {x['big_tok']} | ${x['usd']:.5f} | "
                     f"{x['correct']}/{x['graded']} | {x['p50']:.0f} | {x['p90']:.0f} | {x['slow']} | {x['errors']} |")
        xs = [r[m] for r in reps]
        L.append(f"| **{m}** | **mean ± sd (range)** | {spread([x['big_calls'] for x in xs])} | {spread([x['gpu_calls'] for x in xs])} | "
                 f"{spread([x['hits'] for x in xs])} | {spread([x['big_tok'] for x in xs], '{:.0f}')} | {spread([x['usd'] for x in xs], '${:.5f}')} | "
                 f"{spread([x['correct'] for x in xs])} of {xs[0]['graded']} | {spread([x['p50'] for x in xs], '{:.0f}')} | "
                 f"{spread([x['p90'] for x in xs], '{:.0f}')} | {spread([x['slow'] for x in xs], '{:.0f}')} | {spread([x['errors'] for x in xs], '{:.0f}')} |")
    cut_tok = [100 * (1 - r["COLD"]["big_tok"] / r["BASE"]["big_tok"]) for r in reps]
    cut_usd = [100 * (1 - r["COLD"]["usd"] / r["BASE"]["usd"]) for r in reps]
    L += ["", f"COLD against BASE in the same repeat: 763B tokens cut {spread(cut_tok)}%, 763B $ cut {spread(cut_usd)}% "
          "(earlier single run: -53.0% tokens, -46.5% $)."]
    return L


VERDICT = (ROOT / "bench/company_cost/verdict.md")


def report() -> None:
    e_g, e_m = escalation_per_1k("GPT-5.5"), escalation_per_1k("763B")
    L = ["# What a company saves by not sending easy coding calls to a frontier API", "",
         "Question: a company sends every coding call, FizzBuzz included, to a frontier API (GPT-5.5). "
         "What does it pay per 1,000 calls and per month if a cache, a bank of solved problems and a self-hosted 30B take the easy calls first?", ""]
    if VERDICT.exists():
        L += ["## Verdict", "", VERDICT.read_text().rstrip(), ""]
    L += ["## Cost per 1,000 coding calls", ""] + per_1k_table()
    L += ["", "## Monthly cost at 100k, 1M and 10M coding calls a day", "",
          "Math (30 days a month, D = calls a day, h = share served by the cache or bank):", "",
          "```",
          "frontier only  = D x 30 x P_api / 1000",
          "H200s          = ceil(D x (1 - h) / (1,557,000 x 0.5))      # measured top rate, planned at half for peaks",
          "cascade        = H200s x $108.96 x 30                         # always on",
          f"               + D x (1 - h) x {FAIL_RATE:.3f} x 30 x P_fail / 1000  # the 30B's failures, caught by tests, re-asked",
          "               + $25                                          # Supabase Pro base fee",
          "```", "",
          f"P_api: GPT-5.5 ${PRICE['GPT-5.5']['all']:.2f}, 763B ${PRICE['763B']['all']:.4f} per 1k (measured mix of 101 trivial, 120 everyday, 80 hard). "
          f"P_fail is the same API's price weighted by where the 30B fails (2 trivial, 13 everyday, 16 hard): GPT-5.5 ${e_g:.2f}, 763B ${e_m:.3f} per 1k.", "",
          "### h = 0: no repeats at all (the cautious case)", ""] + projection(0.0)
    L += ["", "### h = 30%: three in ten calls are repeats or rewordings of solved problems", "",
          "30% is the share the bank served on reworded copies of problems it had already solved (bank run 3 below). "
          "It is not a measured rate of company traffic. On open chat (oasst1, `results_replay.md`) under 1% of requests were repeats.", ""] + projection(0.30)
    L += ["", *worked(), ""]
    L += ["## Repeated tests (3 runs each)", "",
          "Each repeat ran in its own Supabase tenant or namespace, which was deleted after the repeat. "
          "Only Supabase, Crusoe and the GPU 30B on the Akash V100 were used. No Modal GPU was started.", "",
          "### Supabase cache: one client stores 18 answers, a second client asks 60 questions", "",
          "Same sets as `bench/run_cache.py`: 18 same text, 18 changed case and spacing, 18 with \"Quick question:\" in front (cosine), "
          "6 near-misses (similar words, other answer: any hit is wrong). Product settings: no local fallback, guard on, 300 ms budget, cosine 0.97.", ""]
    L += cache_section()
    L += ["", "### Solved-problem bank: run 2 (same 80 problems) and run 3 (80 reworded copies)", "",
          "Each repeat: a fresh tenant, run 1 replays saved answers to fill the bank with the test problems, then the 260-problem train fill, "
          "run 2, run 3. Run 3 misses make fresh 30B and 763B calls (temperature 0). The graph write is off: it is not part of the lookup.", ""]
    L += bank_section()
    L += ["", "### 60-question ladder check: BASE (763B only), COLD (empty cache), WARM (same questions again)", "",
          "`bench/run_backend.py` unchanged: Supabase cache -> GPU 30B on the Akash V100 (gate 0.95) -> 763B. "
          "The 30B here is the slow shared V100, not the H200.", ""]
    L += ladder_section()
    L += ["", "## Rerun", "", "```",
          "# .env: CHIMERA_DB_URL, CRUSOE_API_KEY, CHIMERA_GPU_URL (an SSH tunnel to your GPU box)",
          ".venv/bin/python bench/company_cost/run_repeats.py cache 3",
          ".venv/bin/python bench/company_cost/run_repeats.py bank 3",
          ".venv/bin/python bench/company_cost/run_repeats.py ladder 3",
          ".venv/bin/python bench/company_cost/report.py", "```", "",
          "Rows: `bench/.scratch/company_cost/` (git-ignored, one row per item, a rerun skips done rows). "
          "Price sources: [Modal H200](https://modal.com/blog/introducing-b200-h200), [Supabase pricing](https://supabase.com/pricing), "
          "Crusoe and GMI list prices as in `results_cost_case.md`."]
    MD.write_text("\n".join(L) + "\n")
    print("wrote", MD)


if __name__ == "__main__":
    report()
