"""Markdown section 'Token savings: what this means for users', built from bench/results_cache_eval.json."""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAMES = {"kaggle": "Kaggle Quora Question Pairs (train.csv)", "hf": "Quora Question Pairs via GLUE QQP train (Hugging Face)"}


def section() -> list[str]:
    p = ROOT / "bench/results_cache_eval.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text())
    rows = d["rows"]
    src = json.loads(next(open(ROOT / "bench/datasets/cache_eval.jsonl"))).get("src", "hf")  # build_cache_eval.py (HF path) writes no src
    n, poss, ans = rows[0]["queries"], rows[0]["possible_hits"], d["answer_tokens"]
    k = 1000 / n
    L = ["## Token savings: what this means for users", "",
         f"Dataset: {NAMES.get(src, src)}. {n} real Quora questions replayed in arrival order, {poss} of them repeat a question "
         f"(same meaning) that came before, so {poss / n * 100:.0f}% is the most any cache could serve. Duplicate labels come from the dataset. "
         "A hit is **wrong** when the cached question is not a labelled duplicate of the new one.", "",
         f"Money is priced at DeepSeek-V4.1-Flash list ($0.29/M in, $1.20/M out). Prompt tokens are counted with the real DeepSeek-V4.1-Flash tokenizer; "
         f"each avoided answer counts {ans} tokens (the median answer in the TOP run). Only correct hits count as savings. "
         "Every cache hit also skips the Mac, GPU and cloud tiers, so those numbers are questions answered without any GPU.", "",
         f"### {NAMES.get(src, src)}: per 1,000 questions", "",
         "| Cache | Guard | Threshold | Answered without a GPU | Of those, wrong | Wrong answers | Tokens saved | $ saved |",
         "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        be = "SQLite local" if r["backend"] == "sqlite" else "Supabase pgvector (shared)"
        wrong = f"{r['false_hits'] / r['hits'] * 100:.0f}%" if r["hits"] else "n/a"
        L.append(f"| {be} | {'on' if r['guard'] else 'off'} | {r['threshold']} | {r['hits'] * k:.0f} | {wrong} | "
                 f"{r['false_hits'] * k:.0f} | {(r['tokens_in_saved'] + r['tokens_out_saved']) * k:,.0f} | ${r['dollars_saved'] * k:.4f} |")
    best = [r for r in rows if r["guard"] and r["threshold"] == 0.97]
    if best:
        b = best[0]
        L += ["", f"In plain words: with the guard on and threshold 0.97 the cache answers about {b['hits'] * k:.0f} of every 1,000 questions "
              f"without any GPU or cloud call and gets {b['false_hits'] * k:.0f} of them wrong. It saves about "
              f"{(b['tokens_in_saved'] + b['tokens_out_saved']) * k:,.0f} tokens and ${b['dollars_saved'] * k:.4f} per 1,000 questions. "
              f"The ceiling for this data is {poss * k:.0f} per 1,000, so most real paraphrases are still missed. "
              "Hit rate depends on how often users repeat themselves; a Quora stream is a modest case."]
        if any(r["backend"] == "pg" for r in rows) and any(r["backend"] == "sqlite" for r in rows):
            same = all(a[x] == c[x] for a, c in zip([r for r in rows if r["backend"] == "sqlite"],
                                                    [r for r in rows if r["backend"] == "pg"]) for x in ("hits", "true_hits"))
            L.append("SQLite and pgvector " + ("gave identical hits in every setting." if same else "differ in some settings (see table)."))
    return L + [""]
