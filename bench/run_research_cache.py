"""Semantic-cache false-hit measurement: cosine only vs cosine + guard (cache/guard.py).

Data: 800 QQP validation pairs (rows 1000-1799 of nyu-mll/glue qqp, label 1 = duplicate), fetched by hand into
$KIROCREW_SCRATCH/hf/qqp_validation.json (datasets-server rows API). A hit on a label-0 pair means the cache
would serve the wrong answer. Embedder: all-MiniLM-L6-v2, same as the product.
    .venv/bin/python bench/run_research_cache.py        # writes bench/results_research_cache.md
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT)]
import conftest  # noqa: E402,F401

from chimera_core.cache.guard import consistent  # noqa: E402
from chimera_core.cache.semantic_cache import OnnxMiniLMEmbedder  # noqa: E402

DATA = pathlib.Path(os.environ["KIROCREW_SCRATCH"]) / "hf" / "qqp_validation.json"


def main() -> None:
    rows = json.loads(DATA.read_text())
    emb = OnnxMiniLMEmbedder()
    a = emb._model.encode([r["question1"] for r in rows], normalize_embeddings=True)
    b = emb._model.encode([r["question2"] for r in rows], normalize_embeddings=True)
    sims = (a * b).sum(1)
    dup = [r["label"] == 1 for r in rows]
    ok = [consistent(r["question1"], r["question2"]) for r in rows]
    n_dup, n_neg = sum(dup), len(rows) - sum(dup)
    lines = ["| threshold | guard | hits | correct hits | wrong hits (false hits) | false-hit rate | recall of duplicates |",
             "|---|---|---|---|---|---|---|"]
    res = {}
    for th in (0.85, 0.90, 0.94, 0.97):
        for guard in (False, True):
            hit = [s >= th and (ok[i] or not guard) for i, s in enumerate(sims)]
            h = sum(hit)
            good = sum(1 for i in range(len(rows)) if hit[i] and dup[i])
            bad = h - good
            res[(th, guard)] = (h, good, bad)
            lines.append(f"| {th} | {'on' if guard else 'off'} | {h} | {good} | {bad} | "
                         f"{(bad / h if h else 0):.1%} | {good / n_dup:.1%} |")
    pathlib.Path(ROOT / "bench/results_research_cache.md").write_text(
        "# Semantic cache false-hit guard (MeanCache idea, arXiv 2403.02694)\n\n"
        f"Data: {len(rows)} real QQP validation pairs ({n_dup} duplicates, {n_neg} non-duplicates), MiniLM cosine.\n"
        "A hit on a non-duplicate pair is a wrong answer served from cache. Single run, no repeats.\n"
        "QQP labels are noisy: some 'duplicates' would not share an answer, so true precision is lower than shown.\n\n"
        + "\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
