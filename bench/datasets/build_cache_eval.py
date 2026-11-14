"""Build bench/datasets/cache_eval.jsonl: ~1000 real Quora questions in arrival order, with duplicate labels.

    build_cache_eval.py kaggle   # bench/.scratch/kaggle/train.csv (Kaggle 'Quora Question Pairs': qid1,qid2,question1,question2,is_duplicate)
    build_cache_eval.py hf       # same Quora data through GLUE QQP train (nyu-mll/glue), when the Kaggle file is not there

Each pair gives two queries: question1 arrives first, question2 later (random gap). A query's `cluster` links every
question joined by is_duplicate=1 edges (or identical text). A cache hit is true only when the cached question is in
the query's cluster. Output is derived from Quora data (Quora terms, non-commercial); it is git-ignored, not committed.
"""
from __future__ import annotations

import csv
import json
import os
import pathlib
import random
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
STORE = pathlib.Path(os.environ.get("KIROCREW_SCRATCH") or HERE.parent / ".scratch")
OUT = HERE / "cache_eval.jsonl"
PAIRS = 500  # 1000 queries


def kaggle_pairs() -> list[tuple[str, str, int]]:
    with open(STORE / "kaggle" / "train.csv", newline="", encoding="utf-8") as f:
        rows = [(r["question1"], r["question2"], int(r["is_duplicate"])) for r in csv.DictReader(f)]
    return rows


def hf_pairs() -> list[tuple[str, str, int]]:
    import fetch

    n = fetch.total("nyu-mll/glue", "qqp", "train")
    offs = random.Random(11).sample(range(0, n - 100, 100), 12)  # 12 random 100-row pages
    return [(r["question1"], r["question2"], int(r["label"]))
            for off in offs for r in fetch.rows("nyu-mll/glue", "qqp", "train", off)]


def norm(t: str) -> str:
    return " ".join(t.lower().split())


def main(src: str) -> None:
    pairs = [p for p in (kaggle_pairs() if src == "kaggle" else hf_pairs()) if p[0].strip() and p[1].strip()]
    rng = random.Random(7)
    pairs = rng.sample(pairs, min(PAIRS, len(pairs)))
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for q1, q2, dup in pairs:
        find(norm(q1)), find(norm(q2))
        if dup:
            parent[find(norm(q1))] = find(norm(q2))
    events = []
    for i, (q1, q2, dup) in enumerate(pairs):
        t1 = rng.random()
        events += [(t1, q1, i, "a", dup), (t1 + rng.random() * (1 - t1) * 0.8 + 1e-6, q2, i, "b", dup)]
    events.sort(key=lambda e: e[0])
    with open(OUT, "w") as f:
        for k, (_, q, pid, role, dup) in enumerate(events):
            f.write(json.dumps({"idx": k, "pair": pid, "role": role, "pair_dup": dup, "text": q,
                                "cluster": find(norm(q)), "src": src}) + "\n")
    print(f"{src}: {len(events)} queries from {len(pairs)} pairs ({sum(p[2] for p in pairs)} duplicate pairs) -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "kaggle")
