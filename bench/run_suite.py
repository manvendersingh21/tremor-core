"""Real-dataset suite: TOP-only vs POOL, both through SpeculativeCascadeRouter.generate() with a TierPool.

    TOP : one tier, Crusoe deepseek-ai/DeepSeek-V4.1-Flash (763B, thinking off); no semantic cache.
    POOL: Supabase cache (exact, then cosine 0.97 + guard; tenant TENANT, purged before and after) -> gpu-small
          (Ollama 30B) -> the same 763B. No Mac 3B, no local cache. gpu-large (Modal H200) stays off.

Needs (POOL): CHIMERA_GPU_URL (the local end of an SSH tunnel to your GPU box),
CRUSOE_API_KEY in .env.
    .venv/bin/python bench/run_suite.py TOP | POOL | report
Rows go to bench/.scratch/suite_<mode>.jsonl as they finish; a rerun skips finished ids. The key is never written.
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(ROOT / "bench" / "datasets"))
import conftest  # noqa: E402,F401

import cache_eval_report  # noqa: E402
import evallog  # noqa: E402
import grade  # noqa: E402
from chimera_core import RouterConfig, SpeculativeCascadeRouter  # noqa: E402
from chimera_core.cache.guard import make_guard  # noqa: E402
from chimera_core.cache.pgvector_cache import PgStore, PgVectorCache  # noqa: E402
from chimera_core.cache.semantic_cache import CachedEmbedder, OnnxMiniLMEmbedder  # noqa: E402
from chimera_core.config import product_tier  # noqa: E402
from chimera_core.inference.local_draft import LlamaCppBackend  # noqa: E402
from chimera_core.ladder import TopBackend  # noqa: E402
from chimera_core.tiers import TierCfg, TierPool  # noqa: E402
from run_bench import load_env  # noqa: E402

# in the repo, git-ignored; not $KIROCREW_SCRATCH (lost on a gateway restart). BENCH_STORE: another run's folder
STORE = pathlib.Path(os.environ.get("BENCH_STORE") or ROOT / "bench/.scratch")
SUITE = ROOT / "bench/datasets/suite.jsonl"
TOP_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"
JUDGE = "zai-org/GLM-5.3-Flash"  # cheap GMI model; wrote none of the graded answers; used only for the Dolly rows
GMI = "https://api.gmi-serving.com"
TENANT = "eval-suite"  # own Supabase tenant: nothing else is read or touched; purged before and after the POOL run
PRICE = {TOP_MODEL: (0.29, 1.20), JUDGE: (0.15, 0.50)}  # $/M in, out (Crusoe / GMI list; no cached-token discount)
LICENSE_NOTE = {"humaneval": "MIT", "mbpp": "CC-BY-4.0", "gsm8k": "MIT", "mmlu": "MIT",
                "dolly": "CC-BY-SA-3.0", "qqp": "Quora terms via GLUE (license 'other', research use)"}
REPO = {"humaneval": "openai/openai_humaneval", "mbpp": "google-research-datasets/mbpp (sanitized, test)",
        "gsm8k": "openai/gsm8k (main, test)", "mmlu": "cais/mmlu (6 subjects, test)",
        "dolly": "databricks/databricks-dolly-15k", "qqp": "nyu-mll/glue qqp (validation; stands in for Kaggle Quora pairs)"}

TOP_TIER = TierCfg(name="cloud-deepseek", device="cloud", backend="openai", url="https://api.inference.crusoecloud.com",
                   model=TOP_MODEL, family="deepseek", cost_per_1k_in=0.00029, cost_per_1k_out=0.0012,
                   timeout_s=240, template_kwargs={"thinking": False})


def pool_tiers() -> list[TierCfg]:
    tiers = [
        # shortcut: the Mac 3B tier (127.0.0.1:8080) is removed, the user stopped it; the 30B is the first model tier.
        product_tier("gpu-small"),  # the product's tuned entry (num_thread, keep_alive, timeout)
        TOP_TIER,
    ]
    if os.environ.get("MODAL_VLLM_URL"):  # shortcut: the Modal tier is wired by its own worker; off here
        print("MODAL_VLLM_URL is set but this run keeps gpu-large disabled", flush=True)
    return tiers


def build(mode: str) -> tuple[SpeculativeCascadeRouter, dict]:
    pool = TierPool(pool_tiers() if mode == "POOL" else [TOP_TIER], min_confidence=0.95, max_tokens=1024)
    last: dict = {}
    orig = pool.generate

    def spy(*a, **kw):
        last["r"] = r = orig(*a, **kw)
        return r

    pool.generate = spy
    shared = emb = None
    if mode == "POOL":
        emb = CachedEmbedder(OnnxMiniLMEmbedder())
        emb.embed("warm up")
        dsn = os.environ["CHIMERA_DB_URL"]
        # store_text=True: the guard only judges rows stored with their prompt text. budget 3 s: a lookup is ~110 ms.
        shared = PgVectorCache(emb, lambda: PgStore(dsn), threshold=0.97, tenant=TENANT, store_text=True,
                               guard=make_guard(), budget_s=3.0, cooldown_s=0.0, max_strikes=10**9)
    # the Mac llama.cpp object is only the router's unused local slot; the pool answers (shortcut: no 3B call is made)
    router = SpeculativeCascadeRouter(LlamaCppBackend(), exact=False, shared=shared, embedder=emb,
                                      config=RouterConfig(min_confidence=0.95), pool=pool)
    return router, last


def run(mode: str) -> None:
    load_env()
    rows = [json.loads(x) for x in SUITE.read_text().splitlines()][: int(os.environ.get("SUITE_LIMIT", "100000"))]
    out = STORE / f"suite_{mode}.jsonl"
    done = {json.loads(x)["id"] for x in out.read_text().splitlines()} if out.exists() else set()
    router, last = build(mode)
    if mode == "POOL" and not done:
        print("purged", router.shared.purge(), "old rows in tenant", TENANT, flush=True)
    if mode == "POOL":  # load the models; not timed, not cached
        for t in router.pool.tiers:
            if t.device != "cloud":
                try:
                    router.pool._factory(t).complete("hello", 4)
                except Exception as e:
                    print("warm-up failed", t.name, type(e).__name__, flush=True)
    with out.open("a") as fh:
        for row in rows:
            if row["id"] in done:
                continue
            last.clear()
            t0 = time.perf_counter()
            err = ""
            try:
                check = (lambda a, row=row: bool(grade.grade(row, a))) if row["grader"] == "unit_test" else None
                res = router.generate(row["prompt"], check=check)  # only answers that pass tests are cached
                if router.shared is not None:
                    router.shared.flush()  # the next prompt must see this answer
                text, tier = res.text, res.telemetry.tier_used
                if "r" in last:
                    tier = last["r"].tier
            except Exception as e:  # AllTiersFailed or a tier error that escaped
                text, tier, err = "", "failed", f"{type(e).__name__}: {e}"[:200]
            ms = (time.perf_counter() - t0) * 1000
            r = last.get("r")
            per = {k: v.model_dump() for k, v in r.per_tier.items()} if r else {}
            rec = {"id": row["id"], "mode": mode, "tier": tier, "latency_ms": round(ms), "answer": text,
                   "attempts": r.attempts if r else [], "per_tier": per, "error": err,
                   "grade": grade.grade(row, text) if text else (0 if row["grader"] not in ("pair", "llm") else None)}
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(mode, row["id"], tier, round(ms), rec["grade"], err, flush=True)
    if mode == "POOL" and len({r["id"] for r in rows} - done - {json.loads(x)["id"] for x in out.read_text().splitlines()}) == 0:
        print("stats", router.shared.stats["hits"], "hits", router.shared.stats["fallbacks"], "cache unavailable", flush=True)
        print("purged", router.shared.purge(), "rows from tenant", TENANT, flush=True)


# ---------------------------------------------------------------- report ----
def pct(x: list[float], q: float) -> float:
    x = sorted(x)
    return x[min(len(x) - 1, int(q * len(x)))] if x else 0.0


def top_usage(rec: dict) -> tuple[int, int, float]:
    u = rec["per_tier"].get("cloud-deepseek")
    return (u["tokens_in"], u["tokens_out"], u["dollars"]) if u else (0, 0, 0.0)


def load(mode: str) -> dict[str, dict]:
    p = STORE / f"suite_{mode}.jsonl"
    return {r["id"]: r for r in map(json.loads, p.read_text().splitlines())} if p.exists() else {}


class Judge:
    """GMI JUDGE model behind grade.llm_scores. Every call's usage is kept so the eval log lists each one."""

    def __init__(self) -> None:
        self.b = TopBackend(JUDGE, {}, api_key=os.environ["GMI_API_KEY"], base_url=GMI, timeout=120)

    def complete(self, q: str, n: int) -> str:
        return self.b.complete(q, max(n, 3000))  # GLM Flash reasons first; 300 tokens ran out before the JSON


def judge_dolly(suite: list[dict], data: dict[str, dict[str, dict]]) -> tuple[dict, dict]:
    """1-5 score for every Dolly answer, both modes in one blind call per prompt. Cached in the scratch dir."""
    path = STORE / "suite_judge.json"
    cache = json.loads(path.read_text()) if path.exists() else {"scores": {}, "calls": {}}
    j = Judge()
    for row in suite:
        if row["grader"] != "llm" or row["id"] in cache["scores"]:
            continue
        ans = {m: data[m][row["id"]]["answer"] for m in data if row["id"] in data[m] and data[m][row["id"]]["answer"]}
        if len(ans) < 2:
            continue
        t0 = time.perf_counter()
        s = grade.llm_scores(j, row["prompt"], row["data"]["reference"], ans)
        u = j.b.last_usage
        cache["scores"][row["id"]] = s
        cache["calls"][row["id"]] = {"in": u["prompt_tokens"], "out": u["completion_tokens"],
                                     "ms": round((time.perf_counter() - t0) * 1000)}
        print("judge", row["id"], s, flush=True)
        path.write_text(json.dumps(cache))
    path.write_text(json.dumps(cache))
    c = cache["calls"].values()
    return cache["scores"], {"in": sum(x["in"] for x in c), "out": sum(x["out"] for x in c), "calls": cache["calls"]}


def write_eval_log(data: dict, scores: dict, jtok: dict) -> int:
    """Rebuild $STORE/eval_log.jsonl (EvalRows) from both runs plus one row per judge call, so the Evals tab shows all."""
    out = []
    for m in ("TOP", "POOL"):
        for r in evallog.import_suite(STORE / f"suite_{m}.jsonl"):
            if r.dataset == "dolly" and (s := scores.get(r.item_id, {}).get(m)) is not None:
                r.passed, r.grader = s >= 4, f"judge {JUDGE} score {s}/5 (pass >= 4)"
            r.run_id = "suite-v2"
            r.mode = f"suite-{m}"
            out.append(r)
    for rid, c in jtok["calls"].items():
        out.append(evallog.EvalRow(run_id="suite-v2", dataset="dolly", item_id=rid, mode="suite-judge", tier="cloud", model=JUDGE,
                                   tokens_in=c["in"], tokens_out=c["out"], latency_ms=c["ms"],
                                   dollars=(c["in"] * PRICE[JUDGE][0] + c["out"] * PRICE[JUDGE][1]) / 1e6,
                                   grader="judge call (scores both modes' answers)"))
    (STORE / "eval_log.jsonl").write_text("".join(r.model_dump_json() + "\n" for r in out))
    return len(out)


def passed(row: dict, rec: dict, scores: dict, mode: str):
    if row["grader"] == "llm":
        s = scores.get(row["id"], {}).get(mode)
        return None if s is None else int(s >= 4)
    return rec["grade"]


def cache_stats(suite: list[dict], pool: dict[str, dict]) -> dict:
    """Hits on duplicate B rows (true = returned A's answer), false hits (wrong source or non-duplicate)."""
    by_id = {r["id"]: r for r in suite}
    s = {"dup_b": 0, "dup_true_hit": 0, "dup_wrong_hit": 0, "neg_b": 0, "neg_hit": 0, "other_rows": 0, "other_hit": 0}
    wrong_answers = []
    for rid, rec in pool.items():
        row, hit = by_id[rid], rec["tier"] in ("exact_cache", "semantic_cache")
        d = row["data"]
        if row["grader"] == "pair" and d["role"] == "b":
            a = pool.get(d["a_id"])
            if d["duplicate"]:
                s["dup_b"] += 1
                if hit and a and rec["answer"] == a["answer"]:
                    s["dup_true_hit"] += 1
                elif hit:
                    s["dup_wrong_hit"] += 1
            else:
                s["neg_b"] += 1
                s["neg_hit"] += hit
        else:  # an A row or a stand-alone prompt: no earlier duplicate exists, any hit is wrong
            s["other_rows"] += 1
            if hit:
                s["other_hit"] += 1
                wrong_answers.append(rid)
    s["false_hit_ids"] = wrong_answers
    return s


def report() -> None:
    load_env()
    suite = [json.loads(x) for x in SUITE.read_text().splitlines()]
    data = {m: load(m) for m in ("TOP", "POOL")}
    done = [r for r in suite if r["id"] in data["TOP"] and r["id"] in data["POOL"]]
    scores, jtok = judge_dolly(done, data)
    keys = sorted({(r["source"], r["type"]) for r in done})

    def agg(rows: list[dict], mode: str) -> dict:
        recs = [data[mode][r["id"]] for r in rows]
        gs = [p for r, rec in zip(rows, recs) if (p := passed(r, rec, scores, mode)) is not None]
        tu = [top_usage(x) for x in recs]
        lat = [x["latency_ms"] for x in recs]
        tiers: dict[str, int] = {}
        for x in recs:
            tiers[x["tier"]] = tiers.get(x["tier"], 0) + 1
        return {"n": len(rows), "graded": len(gs), "passes": sum(gs), "top_calls": sum(1 for t in tu if t[0] or t[1]),
                "top_in": sum(t[0] for t in tu), "top_out": sum(t[1] for t in tu), "usd": sum(t[2] for t in tu),
                "med_ms": statistics.median(lat) if lat else 0, "p90_ms": pct(lat, 0.9), "tiers": tiers,
                "wall_s": sum(lat) / 1000}

    def rate(a: dict) -> str:
        return f"{a['passes']}/{a['graded']} ({a['passes'] / a['graded'] * 100:.0f}%)" if a["graded"] else "n/a"

    groups = {f"{s}/{t}": [r for r in done if (r["source"], r["type"]) == (s, t)] for s, t in keys}
    groups["ALL"] = done
    res = {g: {m: agg(rs, m) for m in data} for g, rs in groups.items()}
    A = res["ALL"]
    top_tok = lambda a: a["top_in"] + a["top_out"]  # noqa: E731
    saved_tok = (1 - top_tok(A["POOL"]) / top_tok(A["TOP"])) * 100 if top_tok(A["TOP"]) else 0
    saved_usd = (1 - A["POOL"]["usd"] / A["TOP"]["usd"]) * 100 if A["TOP"]["usd"] else 0

    with open(ROOT / "bench/results_suite.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["group", "mode", "n", "graded", "passes", "top_calls", "top_tokens_in", "top_tokens_out",
                    "usd", "median_ms", "p90_ms", "tiers"])
        for g, ms in res.items():
            for m, a in ms.items():
                w.writerow([g, m, a["n"], a["graded"], a["passes"], a["top_calls"], a["top_in"], a["top_out"],
                            f"{a['usd']:.6f}", round(a["med_ms"]), round(a["p90_ms"]), json.dumps(a["tiers"])])

    cs = cache_stats(done, data["POOL"])
    lost = [(r, data["POOL"][r["id"]]) for r in done if r["grader"] not in ("pair", "llm")
            and data["TOP"][r["id"]]["grade"] == 1 and data["POOL"][r["id"]]["grade"] == 0]
    won = [r for r in done if r["grader"] not in ("pair", "llm")
           and data["TOP"][r["id"]]["grade"] == 0 and data["POOL"][r["id"]]["grade"] == 1]
    lost_by = {}
    for r, rec in lost:
        k = (r["source"], rec["tier"])
        lost_by[k] = lost_by.get(k, 0) + 1
    slower = sum(1 for r in done if data["POOL"][r["id"]]["latency_ms"] > data["TOP"][r["id"]]["latency_ms"])
    errs = {m: sum(1 for r in done if data[m][r["id"]]["error"]) for m in data}
    ct = {m: sum(top_tok(a) for a in [agg([r for r in done], m)]) for m in data}
    crusoe_total = ct["TOP"] + ct["POOL"]
    n_log = write_eval_log(data, scores, jtok)
    n = len(done)
    free = sum(1 for r in done if not (top_usage(data["POOL"][r["id"]])[0] or top_usage(data["POOL"][r["id"]])[1]))
    free_top = sum(1 for r in done if not (top_usage(data["TOP"][r["id"]])[0] or top_usage(data["TOP"][r["id"]])[1]))
    bad_hits = cs["neg_hit"] + cs["dup_wrong_hit"] + cs["other_hit"]

    L = ["# Real-dataset suite: TOP-only vs POOL", "",
         (ROOT / "bench/akash_correction_note.md").read_text().strip(), "",
         "Single run, no repeats. Items: %d of %d in suite.jsonl. Quality is graded by tests, exact match or choice letter; "
         "Dolly rows (open QA) are scored 1-5 by the cheap GMI model `%s` (blind, both answers in one call), pass = score >= 4. Pair rows are "
         "not graded for quality; they feed the cache table." % (len(done), len(suite), JUDGE), "",
         "## Setup", "",
         "- TOP: every item to Crusoe `%s` (763B, thinking off), through `SpeculativeCascadeRouter.generate()` with a one-tier pool, no semantic cache." % TOP_MODEL,
         "- POOL: Supabase cache (exact hash, then cosine >= 0.97, guard on; own tenant `eval-suite`, purged before and after) -> "
         "GPU `qwen3:30b-instruct` (Ollama on a V100, SSH tunnel to your GPU box, confidence gate 0.95) -> the same 763B. "
         "No Mac 3B (stopped by the owner) and no local cache. `gpu-large` (Modal H200) off. "
         "The earlier 116-row POOL run that had the 3B tier is not used; it is kept only as a reference file.",
         "- Pool routing by `complexity_score` (gpu-small <= 0.6, top = all); a low-confidence or failed tier climbs. max_tokens 1024 on both. "
         "Prices are Crusoe list: $0.29/M in, $1.20/M out, no cached-token discount, owned hardware $0.",
         "- Mac and GPU were shared with other workers during the run, so latency is indicative only.", "",
         "## Datasets", "", "| Source | Dataset | License | Rows used | Type | Grader |", "|---|---|---|---|---|---|"]
    for src in ("mmlu", "dolly", "qqp", "humaneval", "mbpp", "gsm8k"):
        rs = [r for r in done if r["source"] == src]
        if not rs:
            continue
        L.append(f"| {src} | {REPO[src]} | {LICENSE_NOTE[src]} | {len(rs)} | "
                 f"{', '.join(sorted({r['type'] for r in rs}))} | {', '.join(sorted({r['grader'] for r in rs}))} |")
    L += ["", "Kaggle was skipped (no credentials). GLUE QQP from Hugging Face stands in for the Quora pairs, here and in the cache eval.", "",
          "## Totals", "", "| | TOP | POOL |", "|---|---|---|",
          f"| 763B calls | {A['TOP']['top_calls']} | {A['POOL']['top_calls']} |",
          f"| 763B tokens in / out | {A['TOP']['top_in']:,} / {A['TOP']['top_out']:,} | {A['POOL']['top_in']:,} / {A['POOL']['top_out']:,} |",
          f"| $ (list price) | {A['TOP']['usd']:.4f} | {A['POOL']['usd']:.4f} |",
          f"| Pass rate (graded items) | {rate(A['TOP'])} | {rate(A['POOL'])} |",
          f"| Latency median / p90 (ms) | {A['TOP']['med_ms']:.0f} / {A['TOP']['p90_ms']:.0f} | {A['POOL']['med_ms']:.0f} / {A['POOL']['p90_ms']:.0f} |",
          f"| Sum of latencies (s) | {A['TOP']['wall_s']:.0f} | {A['POOL']['wall_s']:.0f} |",
          f"| Calls that errored | {errs['TOP']} | {errs['POOL']} |", "",
          f"**Top-model tokens saved: {saved_tok:.1f}%. Dollars saved: {saved_usd:.1f}%.** "
          f"POOL answered by tier: {json.dumps(A['POOL']['tiers'])}.", "",
          "## Per source and type", "",
          "| Group | n | Pass TOP | Pass POOL | Delta (pts) | 763B calls TOP/POOL | 763B tokens TOP/POOL | $ TOP/POOL | Median ms TOP/POOL | p90 ms TOP/POOL | POOL answered by |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for g, ms in res.items():
        t, p = ms["TOP"], ms["POOL"]
        d = f"{(p['passes'] / p['graded'] - t['passes'] / t['graded']) * 100:+.0f}" if t["graded"] and p["graded"] else "n/a"
        L.append(f"| {g} | {t['n']} | {rate(t)} | {rate(p)} | {d} | {t['top_calls']}/{p['top_calls']} | "
                 f"{top_tok(t):,}/{top_tok(p):,} | {t['usd']:.4f}/{p['usd']:.4f} | {t['med_ms']:.0f}/{p['med_ms']:.0f} | "
                 f"{t['p90_ms']:.0f}/{p['p90_ms']:.0f} | {json.dumps(p['tiers'])} |")
    L += ["", "## Semantic cache on real Quora pairs", "",
          f"- Duplicate pairs: {cs['dup_b']}. Correct hits (B returned A's answer): {cs['dup_true_hit']} "
          f"({cs['dup_true_hit'] / max(cs['dup_b'], 1) * 100:.0f}%). Hits that returned some other answer: {cs['dup_wrong_hit']}.",
          f"- Non-duplicate pairs: {cs['neg_b']}. False hits: {cs['neg_hit']}.",
          f"- Other rows (no real duplicate exists): {cs['other_rows']}. False hits: {cs['other_hit']}"
          + (f" ({', '.join(cs['false_hit_ids'])})." if cs["false_hit_ids"] else "."), "",
          "## Where the pool lost", "",
          f"- Graded items TOP passed and POOL failed: {len(lost)}. The reverse: {len(won)}.",
          "- Losses by (source, answering tier): " + (", ".join(f"{k[0]} via {k[1]}: {v}" for k, v in sorted(lost_by.items())) or "none") + ".",
          f"- Items where POOL was slower than TOP: {slower} of {len(done)}.",
          f"- Escalated items pay for the failed lower-tier attempt in time: median POOL latency on items answered by the 763B was "
          f"{statistics.median([data['POOL'][r['id']]['latency_ms'] for r in done if data['POOL'][r['id']]['tier'] == 'cloud-deepseek'] or [0]):.0f} ms, "
          f"against {statistics.median([data['TOP'][r['id']]['latency_ms'] for r in done if data['POOL'][r['id']]['tier'] == 'cloud-deepseek'] or [0]):.0f} ms for TOP on the same items.",
          "", "## Verdict", ""]
    qd = (A["POOL"]["passes"] / max(A["POOL"]["graded"], 1) - A["TOP"]["passes"] / max(A["TOP"]["graded"], 1)) * 100
    L.append(f"POOL cut 763B tokens by {saved_tok:.1f}% and list-price dollars by {saved_usd:.1f}% against TOP-only on this "
             f"{len(done)}-item mix, and its pass rate moved by {qd:+.1f} points. "
             f"Median latency went from {A['TOP']['med_ms']:.0f} ms to {A['POOL']['med_ms']:.0f} ms and p90 from "
             f"{A['TOP']['p90_ms']:.0f} ms to {A['POOL']['p90_ms']:.0f} ms. "
             f"The cache served {cs['dup_true_hit']} of {cs['dup_b']} real duplicate questions and gave {cs['neg_hit'] + cs['dup_wrong_hit'] + cs['other_hit']} wrong-source hits.")
    hh = res.get("humaneval/hard", {}).get("POOL", {})
    L += ["", "Failures and losses, by name:",
          f"- Quality: POOL lost {len(lost)} graded items that TOP passed (code: humaneval and mbpp via the 30B; one MMLU) "
          f"and won {len(won)}. On the 15 hard HumanEval items POOL passed {hh.get('passes', 0)}/{hh.get('graded', 0)}. "
          "The 30B's confidence gate does not catch wrong code: those answers passed the gate and were served.",
          f"- Latency is much worse: {slower} of {n} items were slower than TOP. The Akash GPU was shared with other chats and "
          "queued, so the 30B calls took 40 to 140 s each (median 86 s). This number says the shared box was slow, not what a free GPU does; "
          "it was not re-measured on an idle GPU.",
          "- Open chat does not stay on the 30B: most Dolly answers had low confidence and climbed to the 763B (54 of 60), so Dolly saved "
          "almost nothing. The savings come from MMLU, GSM8K and code.",
          f"- The cache barely mattered here: {cs['dup_true_hit']} hits in {n} items, because this mix has only 24 repeated questions. "
          "The 1,000-question Quora replay below is the real cache test. Its best safe setting (guard on, 0.97) still missed most paraphrases.",
          "- Judge: GLM-5.3-Flash scored Dolly. Two Dolly items got no score (judge reply not parseable) and are left out of the pass rate. "
          "A cheap judge is a weaker grader than tests; the 52/58 versus 52/58 tie on Dolly is not strong evidence.",
          "- One run, no repeats, 300 items. Differences of a few points (MMLU -2, MBPP -6) are within noise.",
          "- Kaggle Quora data was not used; GLUE QQP from Hugging Face stands in."]
    L += ["", "## Per 1,000 requests (this mix)", "",
          "This mix is 300 items, not real traffic: 1/5 of it is MMLU, 1/5 Dolly, 1/5 Quora pairs, the rest code and math. "
          "Numbers are the run's totals scaled by 1000/%d." % n, "",
          "| Per 1,000 requests | TOP only | POOL |", "|---|---|---|",
          f"| Answered without a 763B call | {free_top * 1000 / n:.0f} | {free * 1000 / n:.0f} |",
          f"| 763B tokens (in + out) | {top_tok(A['TOP']) * 1000 / n:,.0f} | {top_tok(A['POOL']) * 1000 / n:,.0f} |",
          f"| 763B dollars at list price | ${A['TOP']['usd'] * 1000 / n:.3f} | ${A['POOL']['usd'] * 1000 / n:.3f} |",
          f"| Wrong cache hits | 0 | {bad_hits * 1000 / n:.1f} |",
          f"| Items TOP passed and POOL failed | 0 | {len(lost) * 1000 / n:.1f} |", "",
          f"Eval log: {n_log} rows (both runs and every judge call) in `bench/.scratch/eval_log.jsonl`, imported with `bin/chimera evals import`.", ""]
    L += cache_eval_report.section()
    L.append(f"Crusoe tokens used for this report: {crusoe_total:,} (TOP run {ct['TOP']:,}, POOL run {ct['POOL']:,}, "
             f"warm-up and retried calls excluded). Judge (GMI {JUDGE}): {len(jtok['calls'])} calls, {jtok['in'] + jtok['out']:,} tokens.")
    (ROOT / "bench/results_suite.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[-14:]))


if __name__ == "__main__":
    {"TOP": lambda: run("TOP"), "POOL": lambda: run("POOL"), "report": report}[sys.argv[1]]()
