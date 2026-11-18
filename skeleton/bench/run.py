"""One skeleton, two apps: the store's cache hit rate on a shopper mix, and the coder's climbs.

    .venv/bin/python skeleton/bench/run.py            # demo: stub models, in-memory cache (labelled demo)
    .venv/bin/python skeleton/bench/run.py --live     # 30B on your GPU box, 763B, Supabase cache

Store: warm the cache with the 30 seed questions, then ask N shopper questions (default 200, seed 7): 70% seed
questions (a few are asked far more than others), 18% other wording of a seed question, 12% new questions.
A served cache answer is wrong when it differs from the first answer the same question got (or, the first time
other wording is asked, its seed question's answer). Coder: three small bug-fix tasks, each asked twice; tests decide.
Rows go to bench/.scratch/skeleton/ (git-ignored); the tables print as markdown.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from skeleton.apps.coder import demo as coder_demo  # noqa: E402
from skeleton.apps.store.store import QUESTIONS, make_assistant, seed  # noqa: E402

OUT = ROOT / "bench/.scratch/skeleton"


def shopper_mix(n: int, rng: random.Random) -> list[tuple[str, str]]:
    """(question, the question it means). Seed questions follow a Zipf-like pull: rank r has weight 1 / r."""
    q = json.loads(QUESTIONS.read_text())
    seeds, paras, novel = q["seed"], q["paraphrases"], q["novel"]
    weights = [1 / (r + 1) for r in range(len(seeds))]
    out = []
    for _ in range(n):
        x = rng.random()
        if x < 0.70:
            s = rng.choices(seeds, weights)[0]
            out.append((s, s))
        elif x < 0.88:
            p, s = rng.choice(paras)
            out.append((p, s))
        else:
            s = rng.choice(novel)
            out.append((s, s))
    return out


def store(live: bool, n: int, seed_n: int) -> dict:
    bot = make_assistant(live)
    rng = random.Random(seed_n)
    seeds = json.loads(QUESTIONS.read_text())["seed"]
    first: dict[str, str] = {}
    t0 = time.perf_counter()
    for s in seeds:  # warm-up, as the server does at start; first answers are the reference
        first[s] = bot.ask(s)["answer"]
    warm = bot.stats()
    warm["wall_s"] = round(time.perf_counter() - t0, 1)
    bot.reset_stats()
    rows, wrong = [], 0
    for q, means in shopper_mix(n, rng):
        a = bot.ask(q)
        ref = first.get(q) or first.get(means)  # this question's first answer, else its seed question's
        bad = bool(a["cache_hit"] and ref is not None and a["answer"] != ref)
        first.setdefault(q, a["answer"])
        wrong += bad
        rows.append({"q": q, "means": means, "tier": a["tier"], "cache_hit": a["cache_hit"], "tokens": a["tokens"],
                     "tokens_saved": a["tokens_saved"], "dollars": a["dollars"], "dollars_saved": a["dollars_saved"],
                     "ms": a["latency_ms"], "verified": a["verified"], "tried": a["tried"], "wrong_hit": bad})
    s = bot.stats()
    hits = [r["ms"] for r in rows if r["cache_hit"]]
    miss = [r["ms"] for r in rows if not r["cache_hit"]]
    s.update(warmup=warm, wrong_hits=wrong, p50_hit_ms=_p50(hits), p50_miss_ms=_p50(miss),
             distinct=len({r["q"] for r in rows}), big_only_dollars=round(s["dollars"] + s["dollars_saved"], 6))
    _write(f"store_{_mode(live)}.jsonl", rows)
    return s


def coder(live: bool) -> list[dict]:
    rows = coder_demo.run(live=live)
    _write(f"coder_{_mode(live)}.jsonl", rows)
    return rows


def _p50(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 1) if xs else None


def _mode(live: bool) -> str:
    return "live" if live else "demo"


def _write(name: str, rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / name, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def markdown(s: dict, rows: list[dict], live: bool, n: int) -> str:
    w = s["warmup"]
    by = ", ".join(f"{k} {v}" for k, v in sorted(s["by_tier"].items(), key=lambda kv: -kv[1]))
    lines = [f"### Store ({_mode(live)}): {n} shopper questions after a 30-question warm-up", "",
             "| | Value |", "|---|---|",
             f"| Warm-up | {w['questions']} questions, {w['model_calls']} model calls, {w['tokens']:,} tokens, {w['wall_s']} s |",
             f"| Distinct questions in the mix | {s['distinct']} |",
             f"| Cache hit rate | **{s['hit_rate'] * 100:.1f}%** ({s['cache_hits']} of {s['questions']}: exact {s['exact']}, cosine {s['cosine']}) |",
             f"| Wrong cache answers | {s['wrong_hits']} |",
             f"| Model calls | {s['model_calls']} (climbs {s['climbs']}) |",
             f"| Answered by | {by} |",
             f"| Answers that failed the catalog check (served as \"ask at the desk\") | {s['unverified']} |",
             f"| Tokens used / kept off the 763B | {s['tokens']:,} / {s['tokens_saved']:,} |",
             f"| $ spent (list price) | ${s['dollars']:.6f} |",
             f"| $ if every question went to the 763B (estimate) | ${s['big_only_dollars']:.6f} |",
             f"| Median latency: cache hit / model | {s['p50_hit_ms']} ms / {s['p50_miss_ms']} ms |", "",
             f"### Coder ({_mode(live)}): 3 bug-fix tasks, each asked twice", "",
             "| Task | Pass | Answered by | Tiers called | Tests | Tokens | $ spent | ms |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['task']} | {r['pass']} | {r['tier']} | {' -> '.join(r['tried']) or '(cache)'} | "
                     f"{'pass' if r['verified'] else 'FAIL'} | {r['tokens']} | ${r['dollars']:.6f} | {r['ms']:.0f} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args(argv)
    s = store(args.live, args.n, args.seed)
    rows = coder(args.live)
    md = markdown(s, rows, args.live, args.n)
    (OUT / f"results_{_mode(args.live)}.md").write_text(md + "\n")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
