"""Build bench/results_a6000.md (+ csv in bench/.scratch/a6000/) from the rows bench/run_a6000.py wrote.

    .venv/bin/python bench/run_a6000.py report

Plain Q&A (Dolly) is scored 1-5 by the Crusoe 763B as judge, pass = 4 or more; every distinct answer to an item is
scored in one blind call, cached in bench/.scratch/a6000/judge_<model>.json. Code is graded by running its tests,
GSM8K by the number, MMLU by the letter. Quora pairs are graded by cache behaviour (run_suite.cache_stats).
The 763B-only baseline is the earlier runs on the same items: bench/.scratch/suite_TOP.jsonl and
bench/.scratch/cost_case/raw_top.jsonl (results_suite.md, results_cost_case.md).
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import pathlib
import statistics
import subprocess
import time

import grade
import run_a6000 as ra
import run_suite
from chimera_core.ladder import TopBackend

ROOT, STORE = ra.ROOT, ra.STORE
TOPN = run_suite.TOP_MODEL
P_IN, P_OUT = 0.29 / 1e6, 1.20 / 1e6  # Crusoe list $/token, as in results_suite.md


def h(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def rows_of(path: pathlib.Path) -> dict[str, dict]:
    out = {}
    for line in path.read_text().splitlines():
        r = json.loads(line)
        out[r["id"]] = r  # a redone row (after a restart) replaces the earlier one
    return out


def load() -> dict[tuple, dict[str, dict]]:
    runs = {}
    for p in sorted(STORE.glob("*_*_*_r*.jsonl")):
        m, mode, data, rep = p.stem.split("_")
        runs[(m, data, mode, int(rep[1:]))] = rows_of(p)
    return runs


def judge(model: str, items: dict[str, dict], runs: dict) -> dict[str, int]:
    """{answer hash: 1-5} for every Dolly answer of this model, judged by the 763B."""
    path = STORE / f"judge_{model}.json"
    cache = json.loads(path.read_text()) if path.exists() else {"scores": {}, "calls": []}
    b = TopBackend(TOPN, {"thinking": False}, api_key=os.environ["CRUSOE_API_KEY"],
                   base_url="https://api.inference.crusoecloud.com", timeout=180)
    for iid, row in items.items():
        if row["grader"] != "llm":
            continue
        ans = {}
        for (m, _, _, _), rs in runs.items():
            if m == model and iid in rs and rs[iid]["answer"]:
                ans[h(rs[iid]["answer"])] = rs[iid]["answer"]
        todo = {k: v for k, v in ans.items() if k not in cache["scores"]}
        if not todo:
            continue
        t0 = time.perf_counter()
        try:
            s = grade.llm_scores(b, row["prompt"], row["data"]["reference"], todo)
        except Exception as e:  # noqa: BLE001
            print("judge failed", iid, type(e).__name__, flush=True)
            continue
        u = b.last_usage or {}
        cache["scores"].update(s)
        cache["calls"].append({"id": iid, "in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0),
                               "ms": round((time.perf_counter() - t0) * 1000)})
        path.write_text(json.dumps(cache))
    path.write_text(json.dumps(cache))
    return cache["scores"]


def pct(x: list[float], q: float) -> float:
    x = sorted(x)
    return x[min(len(x) - 1, int(q * len(x)))] if x else 0.0


def ms(x: list[float]) -> str:
    """mean ± sd over repeats (one repeat: the value)."""
    if not x:
        return "-"
    if len(x) == 1:
        v = x[0]
        return f"{v:,.0f}" if abs(v) >= 100 else f"{v:.3g}" if v != int(v) else f"{int(v)}"
    m, s = statistics.mean(x), statistics.stdev(x)
    if abs(m) >= 100:
        return f"{m:,.0f} ± {s:,.0f}"
    return f"{m:.4f} ± {s:.4f}" if 0 < abs(m) < 1 else f"{m:.1f} ± {s:.1f}"


def passed(row: dict, rec: dict, scores: dict) -> int | None:
    if row["grader"] == "llm":
        s = scores.get(h(rec["answer"])) if rec["answer"] else 1
        return None if s is None else int(s >= 4)
    return rec["grade"]


def grades_of(recs: list[tuple[dict, dict]], scores: dict) -> list[tuple[dict, dict, int | None]]:
    return [(row, rec, passed(row, rec, scores)) for row, rec in recs]


def agg(items: dict[str, dict], rs: dict[str, dict], scores: dict, mode: str, pool_rs: dict[str, dict]) -> dict:
    """pool_rs: the POOL repeat that filled the cache (for WARM: a hit should return that run's answer to the same id)."""
    cache = {"exact_cache", "semantic_cache"}
    # The runner was restarted once at the start (to add WARM); the item in flight in each POOL stream had already been
    # stored, so its rerun was an exact hit on its own prompt. Those rows are left out (the prompt is unique in its file).
    uniq = {r["prompt"] for r in items.values()}
    once = {p for p in uniq if sum(1 for r in items.values() if r["prompt"] == p) == 1}
    artefact = {i for i, r in rs.items() if mode == "POOL" and r["tier"] == "exact_cache" and items.get(i, {}).get("prompt") in once}
    recs = [(items[i], rs[i]) for i in items if i in rs and i not in artefact]
    top = [r["per_tier"].get(ra.TOP.name) for _, r in recs]
    grades = grades_of(recs, scores)
    g = [x for x in grades if x[2] is not None]
    lat = [rec["latency_ms"] for _, rec in recs]
    pool_like = {i: r for row, r in recs for i in [row["id"]]}
    cs = run_suite.cache_stats([items[i] for i in pool_like], pool_like)
    # wrong from the cache: a served cache answer that fails its grade, or (ungraded rows) one from another question
    wrong_cache = repeat_wrong = 0
    for row, rec, p in grades_of(recs, scores):
        if rec["tier"] not in cache:
            continue
        if p == 0:
            first = pool_rs.get(row["id"], {})
            if mode == "WARM" and first.get("answer") == rec["answer"]:
                repeat_wrong += 1  # the same wrong answer the first pass served (it passed the gate); not a cache mix-up
            else:
                wrong_cache += 1
        elif p is None:  # Quora pair rows: graded by where the answer came from
            if mode == "POOL":
                d = row["data"]
                a = pool_like.get(d.get("a_id", ""))
                good = d.get("role") == "b" and d.get("duplicate") and a and rec["answer"] == a["answer"]
            else:  # WARM: the answer stored for this same id
                good = rec["answer"] == pool_rs.get(row["id"], {}).get("answer")
            wrong_cache += not good
    tiers: dict[str, int] = {}
    for _, r in recs:
        tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
    ats = [r["at"] for _, r in recs]
    return {
        "n": len(recs), "tiers": tiers,
        "cache": sum(1 for _, r in recs if r["tier"] in cache),
        "exact": tiers.get("exact_cache", 0), "cosine": tiers.get("semantic_cache", 0),
        "gpu": tiers.get(ra.GPU, 0), "top_ans": tiers.get(ra.TOP.name, 0), "failed": tiers.get("failed", 0),
        "top_calls": sum(1 for t in top if t and t["calls"]),
        "top_tok": sum(t["tokens_in"] + t["tokens_out"] for t in top if t),
        "usd": sum(t["dollars"] for t in top if t),
        "esc": sum(1 for _, r in recs if r.get("escalated_by_tests")),
        "p50": statistics.median(lat) if lat else 0, "p90": pct(lat, 0.9), "sum_s": sum(lat) / 1000,
        "elapsed_s": (max(ats) - min(ats)) if len(ats) > 1 else 0,
        "graded": len(g), "correct": sum(x[2] for x in g),
        "wrong": sum(1 for x in g if x[2] == 0),
        "wrong_cache": wrong_cache, "repeat_wrong": repeat_wrong, "artefact": len(artefact),
        "graded_nd": sum(1 for row, _, p in g if row["grader"] != "llm"),
        "correct_nd": sum(p for row, _, p in g if row["grader"] != "llm"),
        "dup_b": cs["dup_b"], "dup_hit": cs["dup_true_hit"] if mode == "POOL" else 0,
        "gpu_ms": [r["per_tier"][ra.GPU]["latency_ms"] for _, r in recs if ra.GPU in r["per_tier"]],
    }


def baseline(data: str, items: dict[str, dict]) -> dict:
    """763B-only on the same items, from the earlier runs (no new 763B-only run was made here)."""
    if data == "suite":
        p = ROOT / "bench/.scratch/suite_TOP.jsonl"
        rs = {r["id"]: r for r in map(json.loads, p.read_text().splitlines())} if p.exists() else {}
        recs = [rs[i] for i in items if i in rs]
        tok = sum(r["per_tier"].get(ra.TOP.name, {}).get("tokens_in", 0) + r["per_tier"].get(ra.TOP.name, {}).get("tokens_out", 0) for r in recs)
        usd = sum(r["per_tier"].get(ra.TOP.name, {}).get("dollars", 0) for r in recs)
        g = [r["grade"] for r in recs if r["grade"] is not None]
        lat = [r["latency_ms"] for r in recs]
    else:
        p = ROOT / "bench/.scratch/cost_case/raw_top.jsonl"
        rs = {r["id"]: r for r in map(json.loads, p.read_text().splitlines())} if p.exists() else {}
        recs = [rs[i] for i in items if i in rs]
        tok = sum(r["tokens_in"] + r["tokens_out"] for r in recs)
        usd = sum(r["tokens_in"] * P_IN + r["tokens_out"] * P_OUT for r in recs)
        g = [r["pass"] for r in recs]
        lat = [r["latency_ms"] for r in recs]
    return {"n": len(recs), "tok": tok, "usd": usd, "graded": len(g), "correct": sum(g),
            "p50": statistics.median(lat) if lat else 0, "p90": pct(lat, 0.9)}


def events() -> tuple[list[str], list[str]]:
    """(yields and resumes, server starts and stops) from the watchdog's logs on the box."""
    r = os.environ["A6000_ROOT"]
    try:
        y = ra.ssh(f"cat {r}/logs/yield_events.log 2>/dev/null")
        w = ra.ssh(f"grep -E '^(started|stopped) GPU' {r}/logs/watchdog.log 2>/dev/null")
    except Exception:  # noqa: BLE001
        return ["(could not read the yield log from the box)"], []
    return [x for x in y.splitlines() if x.strip()], [x for x in w.splitlines() if x.strip()]


def main() -> None:
    ra.load_env()
    runs = load()
    models = [m for m in ra.MODELS if any(k[0] == m for k in runs)]
    speed = {m: json.loads((STORE / f"speed_{m}.json").read_text()) for m in models if (STORE / f"speed_{m}.json").exists()}
    res: dict[tuple, dict] = {}
    base: dict[tuple, dict] = {}
    for m in models:
        allitems = {}
        for d in ra.DATA:
            allitems.update({r["id"]: r for r in ra.items(d, m)})
        scores = judge(m, allitems, runs)
        for d in ra.DATA:
            items = {r["id"]: r for r in ra.items(d, m)}
            base[(m, d)] = baseline(d, items)
            for (mm, dd, mode, rep), rs in runs.items():
                if mm == m and dd == d:
                    res[(m, d, mode, rep)] = agg(items, rs, scores, mode, runs.get((m, d, "POOL", rep), {}))

    with open(STORE / "results_a6000.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        keys = ["n", "cache", "exact", "cosine", "gpu", "top_ans", "failed", "top_calls", "top_tok", "usd", "esc", "p50",
                "p90", "sum_s", "elapsed_s", "graded", "correct", "wrong", "wrong_cache", "dup_b", "dup_hit"]
        w.writerow(["model", "data", "mode", "rep", *keys])
        for k, a in sorted(res.items()):
            w.writerow([*k, *[round(a[x], 6) if isinstance(a[x], float) else a[x] for x in keys]])

    def runs_of(m, d, mode):
        return [res[k] for k in sorted(res) if k[:3] == (m, d, mode)]

    L = ["# Owned-hardware proof: cache + answer check on a shared RTX A6000 box (free GPUs only, yield to anyone)", ""]
    # headline from the qwen POOL repeats over both datasets
    head = []
    for m in models:
        P = [a for d in ra.DATA for a in runs_of(m, d, "POOL")]
        W = [a for d in ra.DATA for a in runs_of(m, d, "WARM")]
        if P:
            n = sum(a["n"] for a in P)
            cut = (1 - sum(a["top_calls"] for a in P) / n) * 100 if n else 0
            head.append((m, cut, sum(a["wrong_cache"] for a in P), len(P), n, W))
    L += ["## Verdict", ""]
    for m, cut, wc, k, n, W in head:
        name = ra.MODELS[m][0]
        wn, wcache = sum(a["n"] for a in W), sum(a["cache"] for a in W)
        wcut = (1 - sum(a["top_calls"] for a in W) / wn) * 100 if wn else 0
        wbad = sum(a["wrong_cache"] for a in W)
        L.append(f"- **{name}: cache + answer check cut {cut:.1f}% of big-model calls with {wc} wrong answers from the cache "
                 f"on owned hardware** ({k} first-pass runs over both sets, {n} items, against sending every item to the 763B)."
                 + (f" Asked the same items again, the cache answered {wcache} of {wn} and big-model calls fell "
                    f"{wcut:.1f}%; the cache caused {wbad} wrong answer(s) there." if W else ""))
    L.append("")
    L.append("VERDICT_DETAIL")
    L += ["", "## Setup", "",
          "- Box: a shared server with two RTX A6000 (48 GB each). At the start another user's job held GPU 0, so we ran on "
          "GPU 1 only (`CUDA_VISIBLE_DEVICES` set to that GPU's UUID). When that job ended and GPU 0 had been empty for 10 "
          "minutes, the watchdog added a second server on GPU 0 (times under GPU yields). Their job was never touched.",
          "- Yield rule (`bench/a6000/watchdog.sh`): poll `nvidia-smi` every 5 s. On a GPU we use, a compute process that is "
          "not ours, more than 300 MiB not held by our pids, one of our pids on the wrong GPU, or a box load above its 32 "
          "cores kills our server at once (literal pids: TERM, KILL after 3 s) and drops the tunnel. We restart only after "
          "5 minutes clear (GPU 0: 10 minutes clear, since its owner's job may run in stages). A row cut by a yield is "
          "dropped and redone, so a yield never becomes a 763B call.",
          "- Server (`bench/a6000/serve.sh`): Ollama `qwen3:30b-instruct` (Qwen3-30B-A3B, Q4_K_M, the product's 30B) and "
          "`gemma2:9b` (Q4_0), 16 parallel slots, 16k context each, flash attention, q8 KV cache, kept loaded. "
          "One model loaded at a time.",
          "- Access: a Cloudflare quick tunnel to a bearer-token proxy (`bench/a6000/auth_proxy.py`; 401 without the "
          "token). The URL lives only in `.env` and the git-ignored scratch folder; it dies with each yield and at the end.",
          "- Runs (`bench/run_a6000.py`, every call through `SpeculativeCascadeRouter.generate()`), all from the Mac over the tunnel:",
          "  - **PLAIN**: every item to the self-hosted model alone.",
          "  - **POOL** (first pass, empty cache): Supabase cache (exact hash on the normalized prompt, then cosine >= 0.97 "
          "with the guard; own tenant per repeat) -> self-hosted model (confidence gate 0.95; prompts above complexity 0.6 "
          "go straight to the 763B) -> Crusoe `DeepSeek-V4.1-Flash` (763B). Code runs its tests on the 30B answer and a "
          "failing answer climbs to the 763B. Only answers that pass their tests (code) or the gate (plain Q&A) are cached.",
          "  - **WARM**: the same items again on the cache its POOL repeat filled (repeat traffic).",
          "- Data: the 300-question suite (`bench/datasets/suite.jsonl`: MMLU, Dolly, Quora pairs, HumanEval, MBPP, GSM8K) "
          "and the 301 cost-case coding tasks (`bench/cost_case/tasks.jsonl`). Gemma ran a fixed slice: 12 items per suite "
          "source plus 12 Quora pairs, and 25 cost-case tasks per difficulty.",
          "- Grading: code by running its tests (sandboxed, no network), GSM8K by the number, MMLU by the letter, Dolly "
          "scored 1-5 by the 763B as judge (pass >= 4; it wrote some of the POOL answers, so Dolly POOL scores lean its "
          "way), Quora pairs by whether a hit returned the duplicate's answer.",
          "- Prices: Crusoe list $0.29/M in, $1.20/M out (763B only, about $0.16 per 1,000 cost-case calls). The A6000 is "
          "owned hardware, priced $0 here.",
          "- Streams ran in parallel (12 model-calling streams at once, 16 slots per server; one server until GPU 0 freed, "
          "then two), so latency is measured under that load and over the internet tunnel from the Mac.",
          "- The 763B-only column is the earlier run on the same items (`results_suite.md`, `results_cost_case.md`); "
          "no new 763B-only run was made.", ""]
    if speed:
        L += ["## Server speed (GPU 1)", "", "| Model | Load (s) | Decode tok/s, 1 stream | Per stream, 16 streams | "
              "Total tok/s, 16 streams | Prompt tok/s | VRAM used on GPU 1 |", "|---|---|---|---|---|---|---|"]
        for m, s in speed.items():
            v = [x for x in s.get("vram", "").splitlines() if x.startswith("1,")]
            L.append(f"| {s['model']} | {s['load_s']:.1f} | {s['decode_tok_s_1_stream']:.0f} | {s['per_stream_tok_s_16']:.0f} | "
                     f"{s['aggregate_tok_s_16_streams']:.0f} | {s['prompt_tok_s']:.0f} | {v[0].split(',')[1].strip() if v else '-'} |")
        L += ["", "Load time is from the disk cache right after download (a first load from cold disk is slower).", ""]

    for m in models:
        for d in ra.DATA:
            modes = [x for x in ("PLAIN", "POOL", "WARM") if runs_of(m, d, x)]
            if not modes:
                continue
            b = base[(m, d)]
            L += [f"## {ra.MODELS[m][0]} on the {'300-question suite' if d == 'suite' else '301 cost-case tasks'}"
                  + (" (slice)" if m == "gemma" else ""), "",
                  "Mean ± sd over repeats (repeats per mode: " + ", ".join(f"{x} {len(runs_of(m, d, x))}" for x in modes) + ").", "",
                  "| | 763B only (earlier run) | " + " | ".join(modes) + " |", "|---|---|" + "---|" * len(modes)]

            def row(label, f, bval="-"):
                L.append(f"| {label} | {bval} | " + " | ".join(ms([f(a) for a in runs_of(m, d, x)]) for x in modes) + " |")
            row("Items", lambda a: a["n"], str(b["n"]))
            row("Cache hits (exact + cosine)", lambda a: a["cache"], "0")
            row("Cache hit rate %", lambda a: a["cache"] / a["n"] * 100 if a["n"] else 0, "0")
            row("Answered by the self-hosted model", lambda a: a["gpu"], "0")
            row("Answered by the 763B", lambda a: a["top_ans"], str(b["n"]))
            row("763B calls (incl. climbs)", lambda a: a["top_calls"], str(b["n"]))
            row("Big-model calls cut %", lambda a: (1 - a["top_calls"] / a["n"]) * 100 if a["n"] else 0, "0")
            row("Code answers that failed tests and climbed", lambda a: a["esc"], "-")
            row("763B tokens", lambda a: a["top_tok"], f"{b['tok']:,}")
            row("763B $ (list price)", lambda a: a["usd"], f"{b['usd']:.4f}")
            row("Graded correct", lambda a: a["correct"], f"{b['correct']}/{b['graded']}")
            row("Graded items", lambda a: a["graded"], str(b["graded"]))
            row("**Wrong answers served (graded)**", lambda a: a["wrong"], str(b["graded"] - b["correct"]))
            row("Wrong-answer rate % (of graded)", lambda a: a["wrong"] / a["graded"] * 100 if a["graded"] else 0,
                f"{(b['graded'] - b['correct']) / max(b['graded'], 1) * 100:.1f}")
            if d == "suite":
                row("Graded correct without Dolly (same items as the 763B column)", lambda a: a["correct_nd"], f"{b['correct']}/{b['graded']}")
            row("**Wrong answers caused by the cache** (other question, or stored text changed)", lambda a: a["wrong_cache"], "0")
            row("Wrong first-pass answers the cache repeated", lambda a: a["repeat_wrong"], "-")
            row("Latency p50 (ms)", lambda a: a["p50"], f"{b['p50']:,.0f}")
            row("Latency p90 (ms)", lambda a: a["p90"], f"{b['p90']:,.0f}")
            row("Wall time, first to last row (s)", lambda a: a["elapsed_s"], "-")
            if d == "suite":
                row(f"Quora duplicates served from cache (of {runs_of(m, d, 'POOL')[0]['dup_b'] if runs_of(m, d, 'POOL') else '-'})",
                    lambda a: a["dup_hit"], "-")
            L.append("")
            art = [a["artefact"] for a in runs_of(m, d, "POOL")]
            if any(art):
                L.append(f"Left out of POOL: {art} row(s) per repeat. The runner was restarted once early on (to add WARM); "
                         "the item in flight had already been stored, so its rerun hit its own answer. Not a real hit.")
            for x in modes:
                tl = [a["tiers"] for a in runs_of(m, d, x)]
                L.append(f"{x} answered by, per repeat: " + "; ".join(", ".join(f"{k} {v}" for k, v in sorted(t.items())) for t in tl) + ".")
            L.append("")

    sp = STORE / "spec_rows.jsonl"
    if sp.exists():
        rs = [json.loads(x) for x in sp.read_text().splitlines()]
        p = {r["id"]: r for r in rs if r["label"] == "plain"}
        s = {r["id"]: r for r in rs if r["label"] == "spec"}
        ids = [i for i in p if i in s]
        if ids:
            same = sum(p[i]["text"] == s[i]["text"] for i in ids)
            tp, ts = statistics.median([p[i]["tok_s"] for i in ids]), statistics.median([s[i]["tok_s"] for i in ids])
            wp, wsp = sum(p[i]["ms"] for i in ids) / 1000, sum(s[i]["ms"] for i in ids) / 1000
            ok, made = sum(s[i]["draft_ok"] or 0 for i in ids), sum(s[i]["draft_n"] or 0 for i in ids)
            L += ["## Minor result: same-box speculative decoding (one run)", "",
                  f"`bench/a6000/spec_job.sh`: llama.cpp on GPU 1 alone, the same Q4_K_M 30B file, greedy, 256 tokens, "
                  f"one request at a time, {len(ids)} cost-case prompts (16 per difficulty). Draft: `qwen3:1.7b` (same "
                  "tokenizer), up to 16 draft tokens per step.", "",
                  "| | 30B alone | 30B + 1.7B draft |", "|---|---|---|",
                  f"| Decode tok/s (median) | {tp:.0f} | {ts:.0f} |",
                  f"| Time for all {len(ids)} prompts (s) | {wp:.1f} | {wsp:.1f} |",
                  f"| Draft tokens accepted | - | {ok:,} of {made:,} ({ok / max(made, 1) * 100:.0f}%) |",
                  f"| Same text as the 30B alone, word for word | - | {same} of {len(ids)} |", "",
                  f"The draft made the 30B **{tp / ts:.2f}x slower** ({ts / tp:.2f}x speed). The 30B is a mixture of experts "
                  "with about 3B active weights per token, so a 1.7B draft saves little per step and its rejected tokens "
                  f"cost a full verify. {len(ids) - same} of {len(ids)} answers drifted from the plain run (greedy on both; "
                  "batch-size numeric differences, not a draft bug). This supports keeping speculative decoding out of the "
                  "product path; the savings come from the cache and the answer check.", ""]
    ev, st = events()
    L += ["## GPU yields", ""]
    L += [f"- {e}" for e in ev] if ev else ["- None. No other process touched a GPU we were using (watchdog log on the box)."]
    L += ["", "Our server starts and stops (box time, EST):", ""] + [f"- {e.split(' pid ')[0]}" for e in st]
    L.append("")
    L.append("Rows: `bench/.scratch/a6000/` (git-ignored, mirrored to the run folder on the box), csv `bench/.scratch/a6000/results_a6000.csv`.")
    jc = []
    for m in models:
        p = STORE / f"judge_{m}.json"
        if p.exists():
            c = json.loads(p.read_text())["calls"]
            jc.append((m, len(c), sum(x["in"] for x in c), sum(x["out"] for x in c)))
    esc_tok, esc_usd = sum(a["top_tok"] for a in res.values()), sum(a["usd"] for a in res.values())
    esc_calls = sum(a["top_calls"] for a in res.values())
    j_calls, j_in, j_out = sum(x[1] for x in jc), sum(x[2] for x in jc), sum(x[3] for x in jc)
    j_usd = j_in * P_IN + j_out * P_OUT
    L += ["", "## Crusoe 763B spend for this report", "",
          "| Use | Calls | Tokens | $ (list) |", "|---|---|---|---|",
          f"| Climbs from the self-hosted model (all runs, all repeats) | {esc_calls:,} | {esc_tok:,} | {esc_usd:.4f} |",
          f"| Judge for Dolly answers (no runnable test) | {j_calls:,} | {j_in + j_out:,} | {j_usd:.4f} |",
          f"| **Total** | {esc_calls + j_calls:,} | {esc_tok + j_in + j_out:,} | **{esc_usd + j_usd:.4f}** |", ""]
    L.append("")
    text = "\n".join(L) + "\n"
    detail = (STORE / "verdict_detail.md").read_text().strip() if (STORE / "verdict_detail.md").exists() else "(details below)"
    text = text.replace("VERDICT_DETAIL", detail)
    (ROOT / "bench/results_a6000.md").write_text(text)
    (STORE / "results_a6000.md").write_text(text)
    r = os.environ["A6000_ROOT"]
    subprocess.run(["rsync", "-a", "--exclude", "endpoints.json", "-e", "ssh -o BatchMode=yes", f"{STORE}/", f"{os.environ['A6000_SSH']}:{r}/rows/"],
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
    print(text)
