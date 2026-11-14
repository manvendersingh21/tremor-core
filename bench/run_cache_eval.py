"""Replay bench/datasets/cache_eval.jsonl through the semantic cache in arrival order.

    .venv/bin/python bench/run_cache_eval.py [sqlite|pg ...]      # default: sqlite pg
Configs: backend (SQLite SemanticCache, shared PgVectorCache tenant eval-kaggle) x guard on/off x threshold 0.94/0.97.
On a miss the 'top model' answers: we store the token "A<idx>", so a hit names the cached question and is true only when
that question is in the query's duplicate cluster (labels from the dataset). Embeds in batches of 64, one process.
Writes bench/results_cache_eval.json (read by bench/results_suite.md's section builder). Never prints the DSN.
Pg + guard: PgVectorCache has no guard hook, so the guard runs on the top-1 hit afterwards (a rejected hit is a miss).
Price: DeepSeek-V4.1-Flash list, $0.29/M in, $1.20/M out. Answer length = median TOP-run answer tokens.
"""
from __future__ import annotations

import json
import os
import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))
import conftest  # noqa: E402,F401

from chimera_core.cache.guard import make_guard  # noqa: E402
from chimera_core.cache.pgvector_cache import PgStore, PgVectorCache  # noqa: E402
from chimera_core.cache.semantic_cache import SemanticCache  # noqa: E402
from run_bench import load_env  # noqa: E402

STORE = pathlib.Path(os.environ.get("KIROCREW_SCRATCH") or ROOT / "bench/.scratch")
EVAL = ROOT / "bench/datasets/cache_eval.jsonl"
OUT = ROOT / "bench/results_cache_eval.json"
TENANT = "eval-kaggle"
P_IN, P_OUT = 0.29 / 1e6, 1.20 / 1e6


class BatchEmbedder:
    """Embeds every query once, in batches of 64; embed() then looks the vector up."""

    def __init__(self, texts: list[str]) -> None:
        from sentence_transformers import SentenceTransformer

        m = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        vecs = m.encode(texts, batch_size=64, normalize_embeddings=True)
        self.v = {t: [float(x) for x in e] for t, e in zip(texts, vecs)}
        del m

    def embed(self, text: str) -> list[float]:
        return self.v[text]


def answer_tokens() -> int:
    rows = [json.loads(l) for l in open(STORE / "suite_TOP.jsonl")]
    return int(statistics.median(r["per_tier"]["cloud-deepseek"]["tokens_out"]
                                 for r in rows if r["per_tier"].get("cloud-deepseek")))


def count_tokens(texts: list[str]) -> list[int]:
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(str(STORE / "tok_DeepSeek-V4.1-Flash.json"))  # real DeepSeek-V4.1-Flash vocabulary
    return [len(tok.encode(t).ids) for t in texts]


def replay(rows, emb, kind: str, guard_on: bool, thr: float) -> dict:
    guard = make_guard()
    if kind == "sqlite":
        cache = SemanticCache(emb, threshold=thr, path=":memory:", guard=guard if guard_on else None)
    else:
        cache = PgVectorCache(emb, lambda: PgStore(os.environ["CHIMERA_DB_URL"]), threshold=thr, tenant=TENANT,
                              budget_s=10.0, cooldown_s=0.0, max_strikes=10**9)
        cache.purge()
    hits = true_hits = false_hits = 0
    saved_in, ms = [], []
    for r in rows:
        t0 = time.perf_counter()
        got = cache.get(r["text"])
        ms.append((time.perf_counter() - t0) * 1000)
        if got is not None and kind == "pg" and guard_on and not guard(r["text"], rows[int(got[0][1:])]["text"], got[1]):
            got = None
        if got is None:
            cache.put(r["text"], f"A{r['idx']}")
            if kind == "pg":
                cache.flush()
            continue
        hits += 1
        if rows[int(got[0][1:])]["cluster"] == r["cluster"]:
            true_hits += 1
            saved_in.append(r["idx"])
        else:
            false_hits += 1
    if kind == "pg":
        cache.purge()
    return {"backend": kind, "guard": guard_on, "threshold": thr, "queries": len(rows), "hits": hits,
            "true_hits": true_hits, "false_hits": false_hits, "saved_idx": saved_in,
            "lookup_ms_median": round(statistics.median(ms), 2)}


def main() -> None:
    load_env()
    kinds = sys.argv[1:] or ["sqlite", "pg"]
    rows = [json.loads(l) for l in open(EVAL)]
    emb = BatchEmbedder([r["text"] for r in rows])
    ptok = count_tokens([r["text"] for r in rows])
    ans = answer_tokens()
    first_seen: dict[str, int] = {}
    possible = 0  # queries whose cluster already appeared: the most any cache could serve
    for r in rows:
        possible += r["cluster"] in first_seen
        first_seen.setdefault(r["cluster"], r["idx"])
    res = []
    for kind in kinds:
        for guard_on in (False, True):
            for thr in (0.94, 0.97):
                o = replay(rows, emb, kind, guard_on, thr)
                tin = sum(ptok[i] for i in o.pop("saved_idx"))
                tout = o["true_hits"] * ans
                o.update(tokens_in_saved=tin, tokens_out_saved=tout, dollars_saved=round(tin * P_IN + tout * P_OUT, 6),
                         answer_tokens=ans, possible_hits=possible)
                res.append(o)
                print(json.dumps(o), flush=True)
    OUT.write_text(json.dumps({"rows": res, "total_prompt_tokens": sum(ptok), "answer_tokens": ans}, indent=1))


if __name__ == "__main__":
    main()
