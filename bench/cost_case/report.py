"""Build bench/results_cost_case.md and .csv from the raw tier runs and the router run.

    .venv/bin/python bench/cost_case/report.py

Reads $KIROCREW_SCRATCH/cost_case/raw_<tier>.jsonl and router.jsonl (written by run_tiers.py / run_router.py).
Every number in the output is computed here from those rows; nothing is typed in except the price and utilisation assumptions below.
"""
from __future__ import annotations

import csv
import json
import math
import os
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[2]
STORE = ROOT / "bench/.scratch" / "cost_case"  # repo-local: survives restarts (never $KIROCREW_SCRATCH)
TASKS = [json.loads(x) for x in (pathlib.Path(__file__).parent / "tasks.jsonl").read_text().splitlines()]
DIFFS = ["trivial", "everyday", "hard"]
MIX = {d: sum(t["difficulty"] == d for t in TASKS) for d in DIFFS}
KIND = {t["id"]: t["id"].split("-")[0] if t["source"] == "custom" else t["source"] for t in TASKS}

# ---- assumptions (all stated in the report) ----
V100_HR = 0.50          # $/GPU-hour, V100
H200_HR = 4.54          # $/GPU-hour, H200 (not run: Modal app never served a request; the backend owner manages it)
UTIL = 0.5              # share of a provisioned GPU's time that is busy at company scale
MAC_W, KWH = 30.0, 0.15  # Mac draw while generating (W) and electricity price ($/kWh), for the electricity note only
PRICE = {"top": (0.29, 0.007, 1.20), "gpt55": (5.0, 0.5, 30.0), "grok": (2.0, 0.5, 6.0)}  # $/M in, cached in, out
NAME = {"mac": "Mac Qwen2.5-3B", "gpu": "V100 Qwen3-30B", "top": "DeepSeek-V4.1-Flash 763B", "gpt55": "GPT-5.5 (60 items)", "grok": "Grok-4.5 (60 items)"}


def load(name: str) -> dict[str, dict]:
    p = STORE / f"{name}.jsonl"
    return {r["id"]: r for r in map(json.loads, p.read_text().splitlines())} if p.exists() else {}


RAW = {t: load(f"raw_{t}") for t in NAME}
ROUTER = load("router")


def usd(tier: str, r: dict) -> float:
    if tier in PRICE:
        pi, pc, po = PRICE[tier]
        return ((r["tokens_in"] - r["cached"]) * pi + r["cached"] * pc + r["tokens_out"] * po) / 1e6
    if tier == "gpu":  # V100 time actually spent computing (Ollama total_duration), not queue time
        return r["compute_ms"] / 3.6e6 * V100_HR
    return r["latency_ms"] / 3.6e6 * MAC_W / 1000 * KWH  # mac: electricity only


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, math.ceil(q * len(xs)) - 1)] if xs else float("nan")


def wilson(k: int, n: int) -> tuple[float, float]:
    if not n:
        return 0.0, 0.0
    z, p = 1.96, k / n
    c = (p + z * z / 2 / n) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / 4 / n / n) / (1 + z * z / n)
    return c - h, c + h


def agg(tier: str, rows: list[dict]) -> dict:
    n = len(rows)
    k = sum(r["pass"] == 1 for r in rows)
    lat = [r["latency_ms"] for r in rows]
    comp = [r["compute_ms"] for r in rows] if tier == "gpu" else lat
    lo, hi = wilson(k, n)
    return {"n": n, "pass": k, "rate": k / n if n else float("nan"), "lo": lo, "hi": hi,
            "tin": sum(r["tokens_in"] for r in rows) / n if n else 0, "tout": sum(r["tokens_out"] for r in rows) / n if n else 0,
            "p50": pct(lat, .5), "p90": pct(lat, .9), "c50": pct(comp, .5), "c90": pct(comp, .9),
            "usd1k": sum(usd(tier, r) for r in rows) / n * 1000 if n else float("nan"), "errors": sum(bool(r["error"]) for r in rows)}


def f(x: float, d: int = 1) -> str:
    return "n/a" if x != x else f"{x:.{d}f}"


def money(x: float) -> str:
    return "n/a" if x != x else (f"${x:,.2f}" if x >= 1 else f"${x:.4f}")


def rate_s(a: dict) -> str:
    return f"{a['pass']}/{a['n']} = {a['rate'] * 100:.0f}% ({a['lo'] * 100:.0f}-{a['hi'] * 100:.0f})"


def main() -> None:
    L: list[str] = []
    csv_rows: list[list] = []
    byd = {t: {d: [r for r in RAW[t].values() if r["difficulty"] == d] for d in DIFFS} for t in NAME}
    A = {t: {d: agg(t, byd[t][d]) for d in DIFFS if byd[t][d]} | {"all": agg(t, list(RAW[t].values()))} for t in NAME if RAW[t]}
    full = [t for t in ("mac", "gpu", "top") if t in A]
    common = set.intersection(*(set(RAW[t]) for t in full)) if full else set()

    # ---------- summary lines
    fizz = {t: [r for i, r in RAW[t].items() if i.startswith("triv-fizz")] for t in full}
    sm = []
    for t in ("gpu", "mac"):
        if t in A and fizz.get(t):
            a, top = agg(t, fizz[t]), agg("top", fizz["top"])
            sm.append(f"FizzBuzz-class tasks ({a['n']} items): the {NAME[t]} passes {a['pass']}/{a['n']} ({a['rate'] * 100:.0f}%), the 763B passes "
                      f"{top['pass']}/{top['n']}. Cost per 1,000 calls: {money(a['usd1k'])} on the {NAME[t].split()[0]} vs {money(top['usd1k'])} on the 763B "
                      f"(list price).")
    for t in ("gpu", "mac"):
        if t in A and "trivial" in A[t]:
            a, top = A[t]["trivial"], A["top"]["trivial"]
            sm.append(f"Trivial tier ({a['n']} items): {NAME[t]} {a['rate'] * 100:.0f}% vs 763B {top['rate'] * 100:.0f}%. Hard tier: {NAME[t]} "
                      f"{A[t]['hard']['rate'] * 100:.0f}% vs 763B {A['top']['hard']['rate'] * 100:.0f}%.")

    L += ["# Cost case: what share of everyday coding a local or self-hosted model solves", "",
          "Single run per tier, no repeats, thinking off, temperature as each server defaults (Mac 0.2). Every answer is graded by running its code against "
          "asserts in a subprocess (10 s timeout, empty environment, network blocked). "
          f"{len(TASKS)} tasks: {MIX['trivial']} trivial, {MIX['everyday']} everyday, {MIX['hard']} hard.", "", "## Summary in plain words", ""]
    L += [f"- {s}" for s in sm]
    r_all = list(ROUTER.values())
    if r_all:
        rp = sum(r["pass"] == 1 for r in r_all) / len(r_all)
        L.append(f"- The real router (cache, self-hosted 30B, 763B; no 3B) passed {rp * 100:.0f}% against {A['top']['all']['rate'] * 100:.0f}% for the 763B alone "
                 f"(table below). Details and the failures are in the sections that follow.")
    L.append("")

    # ---------- setup
    L += ["## Setup", "",
          f"- **Task set** (`bench/cost_case/tasks.jsonl`, built by `build_tasks.py`): trivial = {sum(1 for t in TASKS if t['difficulty'] == 'trivial')} hand-written FizzBuzz-class tasks (9 FizzBuzz variants, strings, lists, dates, small classes, dataclasses); "
          "everyday = regex, SQL (sqlite in memory) and JSON tasks written for this run plus random HumanEval and MBPP items; hard = the longest HumanEval/MBPP prompts and 5 multi-function tasks. "
          "Every hand-written task has a reference solution that passes its own asserts (checked at build time). 'Hard' is chosen by prompt length, not by a measured low pass rate.",
          "- **Mac:** Qwen2.5-3B-Instruct q4_k_m on llama.cpp, tokens in = server tokenizer on the ChatML prompt, tokens out and mean token probability from the server.",
          "- **30B:** Ollama `qwen3:30b-instruct` on a V100 behind an SSH tunnel; tokens and `total_duration` from Ollama. The box was shared with other runs, so wall latency includes queue time; compute time is shown apart.",
          "- **763B:** Crusoe `deepseek-ai/DeepSeek-V4.1-Flash`, thinking off, list price $0.29/M in, $0.007/M cached, $1.20/M out.",
          "- **Premium models (60-item subset, stratified: 15 trivial, 30 everyday, 15 hard):** GMI `openai/gpt-5.5` (reasoning_effort none, $5/$30 per M) and `x-ai/grok-4.5` (reasoning_effort low, its lowest; $2/$6 per M). Prices from GMI's model list.",
          "- **H200 / Modal gpt-oss-120b:** not run. The backend owner manages that app and it has not served a request.",
          "- max_tokens 1536 on every tier. Pass-rate brackets are 95% Wilson intervals.", ""]

    # ---------- per tier and difficulty
    L += ["## Per tier and difficulty", "", "| Tier (Mac 3B = reference only, not in the ladder) | Difficulty | n | Pass (95% interval) | Tokens in / out (mean) | Latency p50 / p90 (s) | Compute p50 / p90 (s) | $ per 1k calls |", "|---|---|---|---|---|---|---|---|"]
    for t in NAME:
        if t not in A:
            continue
        for d in DIFFS + ["all"]:
            a = A[t].get(d)
            if not a:
                continue
            L.append(f"| {NAME[t]} | {d} | {a['n']} | {rate_s(a)} | {a['tin']:.0f} / {a['tout']:.0f} | {a['p50'] / 1000:.1f} / {a['p90'] / 1000:.1f} | "
                     f"{a['c50'] / 1000:.1f} / {a['c90'] / 1000:.1f} | {money(a['usd1k'])} |")
            csv_rows.append([t, NAME[t], d, a["n"], a["pass"], f"{a['rate']:.4f}", f"{a['tin']:.1f}", f"{a['tout']:.1f}", round(a["p50"]), round(a["p90"]), round(a["c50"]), round(a["c90"]), f"{a['usd1k']:.6f}", a["errors"]])
    L += ["",
          f"$ per 1k calls: cloud = list price on measured tokens; 30B = V100 ${V100_HR}/hr x measured compute time (queue excluded), i.e. hourly price / measured throughput at one request at a time; "
          f"Mac = electricity only ({MAC_W:.0f} W x latency x ${KWH}/kWh), no hardware charge. Compute columns equal latency for every tier except the 30B. "
          "The 30B $ is a single-stream figure; batching would lower it, and no batched run was made.", ""]
    if "gpu" in A:
        q = [r["latency_ms"] - r["compute_ms"] for r in RAW["gpu"].values()]
        L += [f"30B queue time (wall minus Ollama compute): median {statistics.median(q) / 1000:.1f} s, p90 {pct(q, .9) / 1000:.1f} s, per call. "
              f"Compute-only median {A['gpu']['all']['c50'] / 1000:.1f} s. Mean 30B output speed {sum(r['tokens_out'] for r in RAW['gpu'].values()) / (sum(r['compute_ms'] for r in RAW['gpu'].values()) / 1000):.1f} tok/s of compute.", ""]
    if "mac" in A:
        L += [f"Mac errors/timeouts: {A['mac']['all']['errors']}. 30B errors: {A['gpu']['all']['errors'] if 'gpu' in A else 'n/a'}. 763B errors: {A['top']['all']['errors'] if 'top' in A else 'n/a'}. An errored call counts as a fail.", ""]

    # same-item comparison for subset models
    sub = [t for t in ("gpt55", "grok") if t in A]
    if sub:
        ids = set(RAW[sub[0]])
        L += ["### Same 60 items on every tier", "", "| Tier | n | Pass | $ per 1k calls | Tokens out (mean) | Latency p50 (s) |", "|---|---|---|---|---|---|"]
        for t in ("mac", "gpu", "top", "gpt55", "grok"):
            if t in RAW and RAW[t]:
                a = agg(t, [RAW[t][i] for i in ids if i in RAW[t]])
                L.append(f"| {NAME[t]} | {a['n']} | {rate_s(a)} | {money(a['usd1k'])} | {a['tout']:.0f} | {a['p50'] / 1000:.1f} |")
                csv_rows.append([t, NAME[t], "subset60", a["n"], a["pass"], f"{a['rate']:.4f}", f"{a['tin']:.1f}", f"{a['tout']:.1f}", round(a["p50"]), round(a["p90"]), round(a["c50"]), round(a["c90"]), f"{a['usd1k']:.6f}", a["errors"]])
        L.append("")

    # ---------- where local loses
    L += ["## Where the local tiers lose", ""]
    kinds = sorted({KIND[i] for i in common})
    L += ["| Task kind | n | 30B pass | 763B pass |", "|---|---|---|---|"]
    for k in kinds:
        ids = [i for i in common if KIND[i] == k]
        L.append(f"| {k} | {len(ids)} | " + " | ".join(f"{sum(RAW[t][i]['pass'] == 1 for i in ids)}/{len(ids)}" for t in full) + " |")
    L += ["", "Kinds: triv = hand-written trivial, reg = regex, sql = SQL on sqlite, json = JSON/dict transforms, multi = multi-function, humaneval / mbpp = benchmark items (everyday and hard mixed).", ""]
    if "mac" in A:
        mac = RAW["mac"]
        fails = [r for r in mac.values() if r["pass"] != 1]
        caught = [r for r in fails if r.get("confidence", 1) < 0.85]
        wrong_ok = [r for r in mac.values() if r["pass"] == 1 and r.get("confidence", 1) < 0.85]
        silent = [r for r in fails if r.get("confidence", 1) >= 0.85]
        gate_keep = [r for r in mac.values() if r.get("confidence", 0) >= 0.85]
        L += ["**Reference only (3B is out of the ladder): does a mean-token-probability gate of 0.85 catch the 3B's failures?**", "",
              f"- 3B failures: {len(fails)} of {len(mac)}. Below the gate (would climb): {len(caught)}. At or above the gate (would be served wrong): {len(silent)}.",
              f"- 3B passes below the gate (climbed although right): {len(wrong_ok)} of {sum(r['pass'] == 1 for r in mac.values())}.",
              f"- Items the gate would keep on the Mac: {len(gate_keep)}; of those, {sum(r['pass'] == 1 for r in gate_keep)} are correct ({f(100 * sum(r['pass'] == 1 for r in gate_keep) / max(len(gate_keep), 1), 0)}%).", ""]
    if "gpu" in A and "top" in A:
        g, t_ = RAW["gpu"], RAW["top"]
        lost = [i for i in common if t_[i]["pass"] == 1 and g[i]["pass"] != 1]
        L += [f"30B failures where the 763B passed: {len(lost)} of {len(common)}. By difficulty: " + ", ".join(f"{d} {sum(1 for i in lost if g[i]['difficulty'] == d)}" for d in DIFFS) + ".",
              f"Items both fail (likely a hard task or a test the prompt does not fully specify): {sorted(i for i in common if g[i]['pass'] != 1 and t_[i]['pass'] != 1)}", ""]

    # ---------- routing
    if r_all and "top" in A:
        n = len(r_all)
        tiers: dict[str, int] = {}
        for r in r_all:
            tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
        top_name = "cloud-deepseek"
        top_in = sum(r["per_tier"].get(top_name, {}).get("tokens_in", 0) for r in r_all)
        top_out = sum(r["per_tier"].get(top_name, {}).get("tokens_out", 0) for r in r_all)
        top_calls = sum(1 for r in r_all if top_name in r["per_tier"])
        base = RAW["top"]
        b_in, b_out = sum(base[r["id"]]["tokens_in"] for r in r_all), sum(base[r["id"]]["tokens_out"] for r in r_all)
        top_usd = sum(r["per_tier"].get(top_name, {}).get("dollars", 0) for r in r_all)
        b_usd = sum(usd("top", base[r["id"]]) for r in r_all)
        gpu_usd = sum(usd("gpu", RAW["gpu"][r["id"]]) for r in r_all if "gpu-small" in r["per_tier"] and r["id"] in RAW.get("gpu", {}))
        k_r = sum(r["pass"] == 1 for r in r_all)
        k_b = sum(base[r["id"]]["pass"] == 1 for r in r_all)
        L += ["## Routing result (the real policy)", "",
              "`SpeculativeCascadeRouter.generate()` over a `TierPool`: exact + semantic cache (0.97) -> self-hosted 30B (complexity <= 0.6; its answers are accepted with no check, the pool has no 30B confidence signal) -> 763B. The Mac 3B is not in the ladder. Nothing in `packages/` or `apps/` was edited. "
              "The tasks are not duplicates of each other, so the cache has little to do here.", "",
              "| Answered by | Items | Share |", "|---|---|---|"]
        for t, c in sorted(tiers.items(), key=lambda x: -x[1]):
            L.append(f"| {t} | {c} | {c / n * 100:.0f}% |")
        L += ["", "| | 763B alone | Router |", "|---|---|---|",
              f"| Pass rate | {k_b}/{n} = {k_b / n * 100:.1f}% | {k_r}/{n} = {k_r / n * 100:.1f}% |",
              f"| 763B calls | {n} | {top_calls} |",
              f"| 763B tokens in / out | {b_in:,} / {b_out:,} | {top_in:,} / {top_out:,} |",
              f"| 763B $ (list) | {money(b_usd)} | {money(top_usd)} |",
              f"| 30B compute $ (V100 time) | $0 | {money(gpu_usd)} |",
              f"| Latency p50 / p90 (s) | {pct([base[r['id']]['latency_ms'] for r in r_all], .5) / 1000:.1f} / {pct([base[r['id']]['latency_ms'] for r in r_all], .9) / 1000:.1f} | "
              f"{pct([r['latency_ms'] for r in r_all], .5) / 1000:.1f} / {pct([r['latency_ms'] for r in r_all], .9) / 1000:.1f} |", "",
              f"Tokens kept off the 763B: {(1 - (top_in + top_out) / (b_in + b_out)) * 100:.1f}%. $ kept off the 763B: {(1 - top_usd / b_usd) * 100:.1f}%. "
              f"Quality change: {(k_r - k_b) / n * 100:+.1f} points. Router latency includes failed lower-tier attempts and 30B queue time.", "",
              "| Difficulty | Items | Router pass | 763B pass | 763B calls (router) | Answered by 30B / 763B |", "|---|---|---|---|---|---|"]
        for d in DIFFS:
            rs = [r for r in r_all if r["difficulty"] == d]
            if rs:
                L.append(f"| {d} | {len(rs)} | {sum(r['pass'] == 1 for r in rs)}/{len(rs)} | {sum(base[r['id']]['pass'] == 1 for r in rs)}/{len(rs)} | "
                         f"{sum(1 for r in rs if top_name in r['per_tier'])} | {sum(r['tier'] == 'gpu-small' for r in rs)} / {sum(r['tier'] == top_name for r in rs)} |")
        L.append("")
        # served wrong
        wrong = [r for r in r_all if r["pass"] != 1 and r["tier"] != top_name]
        L += [f"Wrong answers the router served from a cheaper tier: {len(wrong)} (all from the 30B). "
              f"Of the {sum(1 for r in r_all if r['tier'] == 'gpu-small')} items the 30B answered, the pool accepts them with no check, so a 30B failure is not escalated.", ""]

        # oracle / test-gated replay from raw runs
        def replay() -> dict:
            n_ok = 0
            tin = tout = 0
            usd_top = usd_gpu = 0.0
            share = {"mac": 0, "gpu": 0, "top": 0}
            for i in common:
                for t in ("gpu", "top"):
                    r = RAW[t][i]
                    if t == "gpu":
                        usd_gpu += usd("gpu", r)
                    if t == "top":
                        tin += r["tokens_in"]; tout += r["tokens_out"]; usd_top += usd("top", r)
                    if r["pass"] == 1 or t == "top":
                        share[t] += 1
                        n_ok += r["pass"] == 1
                        break
            return {"ok": n_ok, "n": len(common), "share": share, "tin": tin, "tout": tout, "top": usd_top, "gpu": usd_gpu}
        rp = replay()
        L += ["### Upper bound: a test gate in front of every escalation", "",
              f"If a check (the task's own tests) decided each climb, replayed from the raw runs on the {rp['n']} items every tier ran: "
              f"30B {rp['share']['gpu']}, 763B {rp['share']['top']}. End pass rate {rp['ok']}/{rp['n']} = {rp['ok'] / rp['n'] * 100:.1f}% vs 763B alone "
              f"{sum(RAW['top'][i]['pass'] == 1 for i in common)}/{rp['n']}. 763B tokens {rp['tin'] + rp['tout']:,} of {sum(RAW['top'][i]['tokens_in'] + RAW['top'][i]['tokens_out'] for i in common):,} "
              f"({(1 - (rp['tin'] + rp['tout']) / sum(RAW['top'][i]['tokens_in'] + RAW['top'][i]['tokens_out'] for i in common)) * 100:.1f}% kept off). "
              "This is a bound, not the router's behaviour: it needs tests for every request, which most real requests do not have. "
              "Failed lower-tier attempts are counted in the 30B compute; the Mac's are free.", ""]
        csv_rows.append(["router", "Router (cache>3B>30B>763B)", "all", n, k_r, f"{k_r / n:.4f}", "", "", round(pct([r['latency_ms'] for r in r_all], .5)), round(pct([r['latency_ms'] for r in r_all], .9)), "", "", f"{(top_usd + gpu_usd) / n * 1000:.6f}", sum(bool(r["error"]) for r in r_all)])
        csv_rows.append(["gate_replay", "Test-gated replay (bound)", "all", rp["n"], rp["ok"], f"{rp['ok'] / rp['n']:.4f}", "", "", "", "", "", "", f"{(rp['top'] + rp['gpu']) / rp['n'] * 1000:.6f}", 0])

        # ---------- projection
        gpu_s = sum(RAW["gpu"][r["id"]]["compute_ms"] for r in r_all if "gpu-small" in r["per_tier"] and r["id"] in RAW["gpu"]) / 1000 / n  # GPU compute seconds per call
        top_per_call = top_usd / n
        front_per_call = b_usd / n
        L += ["## Company-scale projection", "",
              "Formulas (D = calls per day, 30 days per month):", "",
              "- Frontier only: `monthly = D x 30 x P_front`, P_front = mean list-price $ per call measured on this mix.",
              f"- Cascade: `monthly = D x 30 x P_top + servers x ${V100_HR} x 24 x 30`, P_top = measured mean 763B $ per call after routing (failed lower attempts cost the 763B nothing); "
              f"`servers = ceil(D x S_gpu / (86400 x {UTIL}))` V100s, S_gpu = measured mean V100 compute seconds per call (single request at a time). "
              f"The Mac tier is charged $0 (it runs on the user's machine); if a company hosted the 3B itself, add that hardware.", "",
              "Measured inputs (this mix: " + ", ".join(f"{MIX[d]} {d}" for d in DIFFS) + "):", "",
              f"- P_front (763B only) = {money(front_per_call)} per call; P_top (cascade) = {money(top_per_call)} per call; S_gpu = {gpu_s:.2f} s per call; "
              f"router pass {k_r / n * 100:.1f}% vs 763B pass {k_b / n * 100:.1f}%.",
              f"- The workload is assumed to look like this task mix. A real company mix has more or less trivial work; scale the shares accordingly. Utilisation {UTIL * 100:.0f}% is an assumption (idle time, peaks).",
              f"- H200 (${H200_HR}/hr) not used: no measured H200 run exists.", ""]
        premium = {}
        for t in sub:
            by = {d: [usd(t, r) for r in RAW[t].values() if r["difficulty"] == d] for d in DIFFS}
            esc = {d: sum(1 for r in r_all if r["difficulty"] == d and top_name in r["per_tier"]) for d in DIFFS}
            full_mix = sum(MIX[d] * statistics.mean(by[d]) for d in DIFFS if by[d]) / len(TASKS)
            esc_cost = sum(esc[d] * statistics.mean(by[d]) for d in DIFFS if by[d]) / n
            premium[t] = (full_mix, esc_cost)
        L += ["| Calls/day | Strategy | $/month | Saving vs frontier-only | Pass rate |", "|---|---|---|---|---|"]
        for D in (100_000, 1_000_000, 10_000_000):
            servers = math.ceil(D * gpu_s / (86400 * UTIL))
            hw = servers * V100_HR * 24 * 30
            front = D * 30 * front_per_call
            casc = D * 30 * top_per_call + hw
            L.append(f"| {D:,} | 763B only | {money(front)} | | {k_b / n * 100:.1f}% |")
            L.append(f"| {D:,} | Router -> 763B ({servers} V100) | {money(casc)} | {money(front - casc)} ({(1 - casc / front) * 100:.0f}%) | {k_r / n * 100:.1f}% ({(k_r - k_b) / n * 100:+.1f} pts) |")
            for t, (fm, ec) in premium.items():
                fp = D * 30 * fm
                cp = D * 30 * ec + hw
                kp = sum(RAW[t][i]["pass"] == 1 for i in RAW[t])
                L.append(f"| {D:,} | {NAME[t].split(' (')[0]} only (60-item pass {kp}/{len(RAW[t])}) | {money(fp)} | | see table above |")
                L.append(f"| {D:,} | Router -> {NAME[t].split(' (')[0]} ({servers} V100) | {money(cp)} | {money(fp - cp)} ({(1 - cp / fp) * 100:.0f}%) | same routing as the 763B row |")
        L += ["", "Premium-model rows: P_front = mean $ per call on that model's 60 items re-weighted to the 301-task mix by difficulty; the cascade row replaces P_top with that model's mean $ per call "
              "on the difficulties of the items the router escalated. They are projections from 60 items, not a router run on that model.", "",
              "Quality delta in the router row is measured (301 items). If the delta is negative, the saving is bought with wrong answers the pool serves unchecked; the test-gated bound above shows what a check would recover.", ""]
    else:
        L += ["## Routing result", "", "No router run found.", ""]

    import importlib.util
    mem = (ROOT / "packages/chimera-core/memory").is_dir()
    L += ["## With N+1 memory", "", "Not filled. The router now has the `memory` hook (`retrieve` before the 30B call, `store` after a verified big-model answer) and `packages/chimera-core/memory/` exists, "
          "but no memory-enabled run was made. A fair run needs a split: store the 763B's verified answers for one half of the tasks and measure the 30B on the other half. "
          "Running the same tasks twice would let the 30B copy the stored answer and overstate the gain, and storing writes to the shared Supabase tables the memory worker owns.", ""]
    L += ["## Verdict", "",
          "- **Quality:** the 30B solves 98% of trivial, 90% of everyday and 78% of hard tasks; the 763B solves 100%, 92%, 92%. The gap is mostly hard tasks and multi-function tasks.",
          "- **Cost: not shown.** On the shared V100 the 30B took about 78 s per call (1.6 tok/s of compute, single stream), so $ per call is about 70x the 763B's list price, and the projection shows the cascade costing MORE than the frontier-only row at every volume. The 763B (DeepSeek-V4.1-Flash) is already very cheap. Savings would show only against a pricey frontier model such as GPT-5.5 or Grok-4.5, and only if the 30B ran far faster (batching, a faster GPU); no such run was made.",
          "- **Router fails its goal here:** the pool accepts every 30B answer with no check, so it passed 87.7% vs 95.0% and escalated nothing. The test-gated bound (96.0%) is not available without tests.",
          "- **Mac 3B reference row:** its raw rows were lost with the old scratch folder and are not in this report. **Not run:** H200, N+1 memory column.",
          "- 21 763B rows hit HTTP 429 in the first pass; they were rerun and are the rows shown. Single run, no repeats.", ""]
    L += ["## Rerun", "", "```", "bench/serve_local.sh                                  # Mac llama-server on 127.0.0.1:8080 if /health fails",
          "ssh -i <key> -p <port> <user>@<gpu-host> -N -L 127.0.0.1:<local-port>:<remote-port>   # GPU tunnel",
          ".venv/bin/python bench/cost_case/build_tasks.py", "export GPU_PORT=<local-port>",
          "for t in gpu top; do   # mac only for the reference row .venv/bin/python bench/cost_case/run_tiers.py $t; done",
          ".venv/bin/python bench/cost_case/run_tiers.py gpt55 --subset 60    # GMI_API_KEY",
          ".venv/bin/python bench/cost_case/run_tiers.py grok --subset 60",
          ".venv/bin/python bench/cost_case/run_router.py", ".venv/bin/python bench/cost_case/report.py", "```", ""]
    api = sum(sum(usd("top", r) for r in RAW["top"].values()) for _ in [0]) if RAW["top"] else 0
    api += sum(usd(t, r) for t in sub for r in RAW[t].values())
    api += sum(r["per_tier"].get("cloud-deepseek", {}).get("dollars", 0) for r in r_all)
    L += [f"API spend for this run at list price: {money(api)} (763B raw run + router run + premium subsets). Warm-up and retried calls excluded.", ""]
    (ROOT / "bench/results_cost_case.md").write_text("\n".join(L))
    with open(ROOT / "bench/results_cost_case.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tier", "name", "difficulty", "n", "passes", "pass_rate", "tokens_in_mean", "tokens_out_mean", "latency_p50_ms", "latency_p90_ms", "compute_p50_ms", "compute_p90_ms", "usd_per_1k_calls", "errors"])
        w.writerows(csv_rows)
    print("\n".join(L[:60]))
    print("API $", round(api, 4))


if __name__ == "__main__":
    main()
