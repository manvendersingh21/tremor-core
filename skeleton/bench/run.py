"""One skeleton, three apps: the help desk and the store on a repeat-heavy question mix, the coder, and a class.

    .venv/bin/python skeleton/bench/run.py            # demo: stub models, in-memory cache (labelled demo)
    .venv/bin/python skeleton/bench/run.py --live     # 30B on your GPU box, 763B, Supabase cache

Help desk and store (the same runner): warm the cache with the app's 30 seed questions, then N questions (default
200, seed 7): 70% seed questions (a few are asked far more than others), 18% other wording of a seed question,
12% new questions. Cost per question (model tokens, $) is recorded at 1, 5, 10, 20, 30, 50, 100, 200, warm-up
included.
A served cache answer is wrong when it differs from the first answer the same question got (or, the first time
other wording is asked, its seed question's answer). Coder: three small bug-fix tasks, each asked twice; tests decide.
Class: 150 student questions (3 assignments, a paper, a chapter; 70% pasted as given, 20% reworded, 10% really
different), no warm-up, so the first student of each question pays (skeleton/apps/coder/classroom.py).
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

from skeleton.apps.coder import classroom  # noqa: E402
from skeleton.apps.coder import demo as coder_demo  # noqa: E402
from skeleton.apps.helpdesk import helpdesk as helpdesk_app  # noqa: E402
from skeleton.apps.store import store as store_app  # noqa: E402

OUT = ROOT / "bench/.scratch/skeleton"
CHAT = {"helpdesk": (helpdesk_app, "Help desk", "support tickets"), "store": (store_app, "Store", "shopper questions")}


def ticket_mix(n: int, rng: random.Random, questions: pathlib.Path = helpdesk_app.QUESTIONS) -> list[tuple[str, str]]:
    """(question, the question it means). Seed questions follow a Zipf-like pull: rank r has weight 1 / r."""
    q = json.loads(questions.read_text())
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


MARKS = (1, 5, 10, 20, 30, 50, 100, 200, 500, 1000)


def helpdesk(live: bool, n: int, seed_n: int) -> dict:
    return chat("helpdesk", live, n, seed_n)


def chat(app: str, live: bool, n: int, seed_n: int) -> dict:
    mod = CHAT[app][0]
    bot = mod.make_assistant(live)
    rng = random.Random(seed_n)
    seeds = json.loads(mod.QUESTIONS.read_text())["seed"]
    first: dict[str, str] = {}
    curve, tot = [], {"tickets": 0, "tokens": 0, "dollars": 0.0, "big": 0.0}

    def count(a: dict) -> None:  # cost per ticket so far, warm-up tickets included
        tot["tickets"] += 1
        tot["tokens"] += a["tokens"]
        tot["dollars"] += a["dollars"]
        tot["big"] += a["dollars"] + a["dollars_saved"]
        if tot["tickets"] in MARKS:
            k = tot["tickets"]
            curve.append({"tickets": k, "tokens": round(tot["tokens"] / k, 1), "dollars": tot["dollars"] / k,
                          "big_only_dollars": tot["big"] / k})

    t0 = time.perf_counter()
    for s in seeds:  # warm-up, as the server does at start; first answers are the reference
        a = bot.ask(s)
        first[s] = a["answer"]
        count(a)
    warm = bot.stats()
    warm["wall_s"] = round(time.perf_counter() - t0, 1)
    bot.reset_stats()
    rows, wrong = [], 0
    for q, means in ticket_mix(n, rng, mod.QUESTIONS):
        a = bot.ask(q)
        count(a)
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
    s.update(warmup=warm, wrong_hits=wrong, curve=curve, p50_hit_ms=_p50(hits), p50_miss_ms=_p50(miss),
             distinct=len({r["q"] for r in rows}), big_only_dollars=round(s["dollars"] + s["dollars_saved"], 6))
    _write(f"{app}_{_mode(live)}.jsonl", rows)
    return s


def students(live: bool, n: int, seed_n: int) -> dict:
    """A class: n student questions over 3 assignments, a paper and a chapter. No warm-up: each item's first
    student pays the model. Same wrong-answer rule as the help desk."""
    room = classroom.Classroom(live)
    first: dict[tuple, str] = {}
    rows, wrong = [], 0
    try:
        for item, q, kind, means in classroom.class_mix(n, random.Random(seed_n)):
            a = room.ask(item, q)
            ref = first.get((item, q)) or first.get((item, means))
            bad = bool(a["cache_hit"] and ref is not None and a["answer"] != ref)
            wrong += bad
            first.setdefault((item, q), a["answer"])
            rows.append({"item": item, "q": q, "kind": kind, "tier": a["tier"], "cache_hit": a["cache_hit"],
                         "tokens": a["tokens"], "tokens_saved": a["tokens_saved"], "dollars": a["dollars"],
                         "dollars_saved": a["dollars_saved"], "ms": a["latency_ms"], "verified": a["verified"],
                         "tried": a["tried"], "wrong_hit": bad})
        s = room.stats()
    finally:
        room.close()
    by_item = {}
    for r in rows:
        b = by_item.setdefault(r["item"], {"asked": 0, "hits": 0, "model": 0})
        b["asked"] += 1
        b["hits"] += r["cache_hit"]
        b["model"] += not r["cache_hit"]
    by_kind = {k: (sum(r["cache_hit"] for r in rows if r["kind"] == k), sum(r["kind"] == k for r in rows))
               for k in classroom.KIND}
    s.update(wrong_hits=wrong, by_item=by_item, by_kind=by_kind, distinct=len({(r["item"], r["q"]) for r in rows}),
             big_only_dollars=round(s["dollars"] + s["dollars_saved"], 6),
             p50_hit_ms=_p50([r["ms"] for r in rows if r["cache_hit"]]),
             p50_miss_ms=_p50([r["ms"] for r in rows if not r["cache_hit"]]))
    _write(f"students_{_mode(live)}.jsonl", rows)
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


def chat_markdown(app: str, s: dict, live: bool, n: int) -> str:
    _, title, what = CHAT[app]
    w = s["warmup"]
    by = ", ".join(f"{k} {v}" for k, v in sorted(s["by_tier"].items(), key=lambda kv: -kv[1]))
    lines = [f"### {title} ({_mode(live)}): {n} {what} after a 30-question warm-up", "",
             "| | Value |", "|---|---|",
             f"| Warm-up | {w['questions']} questions, {w['model_calls']} model calls, {w['tokens']:,} tokens, {w['wall_s']} s |",
             f"| Distinct questions in the mix | {s['distinct']} |",
             f"| Cache hit rate | **{s['hit_rate'] * 100:.1f}%** ({s['cache_hits']} of {s['questions']}: exact {s['exact']}, cosine {s['cosine']}) |",
             f"| Wrong cache answers | {s['wrong_hits']} |",
             f"| Model calls | {s['model_calls']} (climbs {s['climbs']}) |",
             f"| Answered by | {by} |",
             f"| Answers that failed the app's check (left to a person) | {s['unverified']} |",
             f"| Tokens used / kept off the 763B | {s['tokens']:,} / {s['tokens_saved']:,} |",
             f"| $ spent (list price) | ${s['dollars']:.6f} |",
             f"| $ if every question went to the 763B (estimate) | ${s['big_only_dollars']:.6f} |",
             f"| Median latency: cache hit / model | {s['p50_hit_ms']} ms / {s['p50_miss_ms']} ms |", "",
             "Cost per question as volume rises (warm-up included):", "",
             "| Questions | Model tokens per question | $ per question | $ per question, 763B only (estimate) |", "|---|---|---|---|",
             *[f"| {c['tickets']} | {c['tokens']:,.0f} | ${c['dollars']:.6f} | ${c['big_only_dollars']:.6f} |" for c in s["curve"]]]
    return "\n".join(lines)


def coder_markdown(rows: list[dict], live: bool) -> str:
    lines = [f"### Coder ({_mode(live)}): 3 bug-fix tasks, each asked twice", "",
             "| Task | Pass | Answered by | Tiers called | Tests | Tokens | $ spent | ms |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['task']} | {r['pass']} | {r['tier']} | {' -> '.join(r['tried']) or '(cache)'} | "
                     f"{'pass' if r['verified'] else 'FAIL'} | {r['tokens']} | ${r['dollars']:.6f} | {r['ms']:.0f} |")
    return "\n".join(lines)


def students_markdown(s: dict, live: bool, n: int) -> str:
    k = s["by_kind"]
    lines = [f"### Class ({_mode(live)}): {n} student questions, no warm-up", "",
             "| | Value |", "|---|---|",
             f"| Distinct questions | {s['distinct']} |",
             f"| Cache hit rate | **{s['hit_rate'] * 100:.1f}%** ({s['cache_hits']} of {s['questions']}: exact {s['exact']}, cosine {s['cosine']}) |",
             f"| Hits by wording | same {k['same'][0]}/{k['same'][1]}, reworded {k['reworded'][0]}/{k['reworded'][1]}, "
             f"different {k['different'][0]}/{k['different'][1]} |",
             f"| Wrong cache answers | {s['wrong_hits']} |",
             f"| Model calls | {s['model_calls']} (climbs {s['climbs']}) |",
             f"| Answers that failed their check | {s['unverified']} |",
             f"| Tokens used / kept off the 763B | {s['tokens']:,} / {s['tokens_saved']:,} |",
             f"| $ spent / if every question went to the 763B (estimate) | ${s['dollars']:.6f} / ${s['big_only_dollars']:.6f} |",
             "", "| Item | Asked | From the cache | Model answers |", "|---|---|---|---|"]
    for item, b in s["by_item"].items():
        lines.append(f"| {item} | {b['asked']} | {b['hits']} | {b['model']} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--students", type=int, default=150)
    ap.add_argument("--only", default="helpdesk,store,coder,class", help="comma list of sections to run")
    args = ap.parse_args(argv)
    parts = []
    for app in CHAT:
        if app in args.only.split(","):
            parts.append(chat_markdown(app, chat(app, args.live, args.n, args.seed), args.live, args.n))
    if "coder" in args.only.split(","):
        parts.append(coder_markdown(coder(args.live), args.live))
    if "class" in args.only.split(","):
        parts.append(students_markdown(students(args.live, args.students, args.seed), args.live, args.students))
    md = "\n\n".join(parts)
    (OUT / f"results_{_mode(args.live)}.md").write_text(md + "\n")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
