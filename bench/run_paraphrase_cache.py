"""Paraphrase cache: hits, correct hits, wrong hits, recall and added time for 5 cache settings.

Each pair stores `old` (with its answer) in a fresh cache and looks up `new` through the real PgVectorCache code
(an in-memory store stands in for Supabase, so the DB round trip of about 121 ms is the same for every setting and
left out). Embedder: all-MiniLM-L6-v2, as in the product. The yes/no checker is the self-hosted 30B (`gpu-small`
from chimera.toml, the tuned Akash V100) over its SSH tunnel. No Modal, no paid API.

Data: bench/paraphrase_pairs.jsonl (46 hand-made pairs: 20 paraphrases, 24 tricky non-matches, 2 wrong stored
answers) and the 500 Quora pairs of bench/datasets/cache_eval.jsonl (QQP train, git-ignored; build_cache_eval.py).
QQP has no answers: for a pair that reaches the 30B check, the 30B first writes a short answer to `old` (saved).

    .venv/bin/python bench/run_paraphrase_cache.py          # writes bench/results_paraphrase_cache.md
Resumable: 30B answers and verdicts are appended to bench/.scratch/paraphrase/*.jsonl and reused.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT)]
import conftest  # noqa: E402,F401

from chimera_core.cache.band import make_checker  # noqa: E402
from chimera_core.cache.exact_cache import prompt_hash  # noqa: E402
from chimera_core.cache.guard import make_guard  # noqa: E402
from chimera_core.cache.pgvector_cache import PgVectorCache  # noqa: E402
from chimera_core.cache.semantic_cache import CachedEmbedder, OnnxMiniLMEmbedder, _norm  # noqa: E402
from chimera_core.config import checker_tier, product_tier  # noqa: E402
from chimera_core.tiers import build_backend  # noqa: E402

SCR = ROOT / "bench/.scratch/paraphrase"
HAND = ROOT / "bench/paraphrase_pairs.jsonl"
QQP = ROOT / "bench/datasets/cache_eval.jsonl"
OUT = ROOT / "bench/results_paraphrase_cache.md"
BAND = 0.88
SETTINGS = [  # name, normalize, band_low, guard, check
    ("A. cosine >= 0.97 only (no guard)", False, 0.0, False, False),
    ("B. cosine >= 0.97 + guard (the product until now, guard with the 2 new rules)", False, 0.0, True, False),
    ("C. normalize + 0.97 + guard", True, 0.0, True, False),
    (f"D. normalize + band {BAND}-0.97 + guard", True, BAND, True, False),
    (f"E. normalize + band {BAND}-0.97 + guard + 30B yes/no", True, BAND, True, True),
    ("F. normalize + band 0.85-0.97 + guard + 30B yes/no (wider band)", True, 0.85, True, True),
]


class MemStore:
    """One-tenant in-memory stand-in for PgStore (same lookup contract, brute-force cosine)."""

    def __init__(self):
        self.rows = []

    def lookup(self, tenant, ns, h, emb, k):
        ex = next(((r["id"], r["answer"]) for r in self.rows if r["h"] == h), None)
        near = sorted(((r["id"], r["answer"], sum(a * b for a, b in zip(emb, r["emb"])), True, r["text"])
                       for r in self.rows), key=lambda x: -x[2])[:k]
        return ex, near

    def insert(self, tenant, ns, h, text, emb, answer, meta):
        self.rows.append({"id": len(self.rows) + 1, "h": h, "text": text, "emb": emb, "answer": answer})
        return len(self.rows)

    def touch(self, *a):
        pass

    def event(self, *a):
        pass


class Saved:
    """Append-only jsonl memo: key -> value. Resumable runs."""

    def __init__(self, path: pathlib.Path):
        self.path, self.d = path, {}
        if path.exists():
            for line in path.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    self.d[r["k"]] = r["v"]

    def get(self, k, make):
        if k not in self.d:
            self.d[k] = make()
            with self.path.open("a") as fh:
                fh.write(json.dumps({"k": k, "v": self.d[k]}) + "\n")
        return self.d[k]


def load_pairs():
    hand = [json.loads(x) for x in HAND.read_text().splitlines() if x.strip()]
    rows = [json.loads(x) for x in QQP.read_text().splitlines() if x.strip()]
    by = {}
    for r in rows:
        by.setdefault(r["pair"], {})[r["role"]] = r
    qqp = [{"id": f"q{p}", "set": "qqp", "old": d["a"]["text"], "answer": None, "new": d["b"]["text"],
            "same": bool(d["a"]["pair_dup"])} for p, d in sorted(by.items()) if "a" in d and "b" in d]
    return hand, qqp


def main() -> None:
    SCR.mkdir(parents=True, exist_ok=True)
    hand, qqp = load_pairs()
    emb = CachedEmbedder(OnnxMiniLMEmbedder(), size=8192)
    tier = checker_tier(product_tier("gpu-small"), 30.0)  # as the product builds it: temperature 0
    raw = build_backend(tier).raw
    answers, verdicts = Saved(SCR / "answers.jsonl"), Saved(SCR / "verdicts.jsonl")
    live = make_checker(raw.complete, usage=lambda: dict(raw.last_usage), cooldown_s=0.0)

    def answer_for(p):
        if p["answer"] is not None:
            return p["answer"]
        return answers.get(p["old"], lambda: raw.complete(
            "Answer in at most two short sentences.\n\n" + p["old"], 80))

    ran = {"live": False}

    def checker(new, old, answer):
        def call():
            ran["live"] = True
            return live(new, old, answer)[1]
        v = verdicts.get(json.dumps([new, old, answer]), call)
        return v["verdict"] == "yes", v

    results = {s[0]: [] for s in SETTINGS}
    pairs = hand + qqp
    for i, p in enumerate(pairs):
        for name, norm, band, guard, check in SETTINGS:
            store = MemStore()
            # QQP answers are written lazily: only a pair that reaches the 30B check needs one
            ans = p["answer"] if p["answer"] is not None else "(answer pending)"
            chk = None
            if check:
                def chk(new, old, a, _p=p):  # noqa: E306
                    return checker(new, old, answer_for(_p))
            c = PgVectorCache(emb, store, threshold=0.97, store_text=True, guard=make_guard() if guard else None,
                              normalize=norm, band_low=band, checker=chk, budget_s=30.0)
            store.insert("default", "", prompt_hash(p["old"], ""), p["old"], _norm(emb.embed(p["old"])), ans, {})
            emb.embed(p["new"])  # embed outside the timer: every setting pays the same query embedding
            ran["live"] = False
            t0 = time.perf_counter()
            lk = c.lookup(p["new"])
            ms = (time.perf_counter() - t0) * 1000
            ck = lk.check or {}
            if ck.get("ms") and not ran["live"]:  # a saved verdict: add the time the 30B took when it was asked
                ms += ck["ms"]
            results[name].append({"id": p["id"], "set": p["set"], "same": p["same"], "hit": lk.hit is not None,
                                  "score": lk.best_sim, "via": lk.via, "check": ck.get("verdict"),
                                  "check_ms": ck.get("ms"), "ms": ms})  # includes the 30B check when one ran
            c._pool.shutdown(wait=False)
            c._wpool.shutdown(wait=False)
        if i % 50 == 0:
            print(f"{i}/{len(pairs)}", flush=True)
    # the 30B check alone (no cosine, no guard) on every hand-made pair: does it ever say YES to a non-match?
    alone = {p["id"]: checker(p["new"], p["old"], p["answer"])[0] for p in hand}
    (SCR / "rows.json").write_text(json.dumps(results, indent=0))
    write(results, hand, qqp, alone)


def stats(rows):
    hits = [r for r in rows if r["hit"]]
    good = [r for r in hits if r["same"]]
    dup = sum(r["same"] for r in rows)
    return len(hits), len(good), len(hits) - len(good), (len(good) / dup if dup else 0.0)


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(int(q * len(xs)), len(xs) - 1)] if xs else 0.0


# My own reading of the QQP pairs the band served against their label (judged by hand, not by a model).
HAND_READ = {"q67": "same question (label noise)", "q104": "same question (label noise)", "q276": "same question (label noise)",
             "q145": "B is narrower than A; A's answer covers B (borderline)", "q360": "places vs ways: really different"}


def verdict(results, hand, qqp):
    names = [s[0] for s in SETTINGS]
    by = {n: {r["id"]: r for r in results[n]} for n in names}
    tricky = [p["id"] for p in hand if p["set"] == "tricky"]
    wrong = {n[:1]: sum(by[n][i]["hit"] for i in tricky) for n in names}
    fr = {n[:1]: by[n]["h01"]["hit"] for n in names}
    e_wrong = [r for r in results[names[4]] if r["set"] == "qqp" and r["hit"] and not r["same"]]
    text = {p["id"]: p for p in qqp}
    out = ["## Verdict", "",
           f"- The France pair ('What is the capital of France?' then 'Tell me the capital of France'): "
           f"hits in settings {', '.join(k for k in 'ABCDEF' if fr[k]) or 'none'}; "
           f"raw cosine is 0.955, under 0.97. Normalized, both prompts are 'capital of france'.",
           f"- Tricky non-matches served (of {len(tricky)}): " + ", ".join(f"{k} {v}" for k, v in wrong.items()) + ". "
           "The guard (cache/guard.py) changed during this run. Two rules are stricter: entities in another order "
           "('Celsius to Fahrenheit' vs 'Fahrenheit to Celsius', t10) and 'non-' as negation ('romantic' vs "
           "'non-romantic', a QQP pair); before them, setting B served t10 and that QQP pair (first run of this file). "
           "Two fixes only stop false rejects: a possessive 's ('Japan's', h20) and the pronoun 'I' (h19) are no "
           "longer read as entities the other prompt lacks.",
           f"- QQP: the band without the 30B (D) served {sum(r['hit'] and not r['same'] for r in results[names[3]] if r['set'] == 'qqp')} "
           f"pairs against their label; the 30B check (E) cut that to {len(e_wrong)}:"]
    for r in e_wrong:
        p = text[r["id"]]
        out.append(f"  - {r['id']} ({r['score']:.3f}): '{p['old']}' -> '{p['new']}': {HAND_READ.get(r['id'], 'not read by hand')}")
    out += ["- Failures, said plainly: the band with the 30B check is NOT at 0 wrong hits on QQP (above). A wrong "
            "stored answer is served when the prompts are equal after normalizing (w02, score 1.0): only band "
            "candidates are checked, as with an exact-hash hit. The 30B check costs about half a second per band "
            "candidate and needs the GPU tunnel; on an error or a timeout the lookup is a miss. Recall stays low on "
            "paraphrases with other words (h13 'largest' vs 'biggest one', h18 'speed of light' vs 'how fast').",
            "- Defaults: `normalize = true` (it added no wrong hit in any set). The band stays off (`band_low = 0.0`) "
            "because it is not shown safe on QQP; turn it on with `band_low = 0.88` and `band_check = \"gpu-small\"`. "
            "The checker uses the stricter of two prompt wordings: the first one said YES to 'raw chicken' vs "
            "'cooked chicken' (t24) when asked without the cosine and guard (side run, `bench/.scratch/paraphrase/prompt_ab.py`).", ""]
    return out


def write(results, hand, qqp, alone):
    lines = ["# Paraphrase cache: normalize, a cosine band, the guard and a 30B yes/no check", "",
             f"Date: {time.strftime('%Y-%m-%d')}. Single run, no repeats. Code: `packages/chimera-core/cache/band.py`, "
             "`pgvector_cache.py` (`_choose`). Runner: `bench/run_paraphrase_cache.py`.", "",
             "Setup: each pair stores `old` with its answer in a fresh cache, then looks up `new` through the real "
             "`PgVectorCache` code. An in-memory store stands in for Supabase, so the DB round trip (about 121 ms, "
             "`docs/vector-store.md`) is the same for every setting and is left out of the times. Embedder: "
             "all-MiniLM-L6-v2. Checker: the self-hosted 30B (`gpu-small`, qwen3:30b-instruct on the tuned V100, "
             "over an SSH tunnel to your GPU box), at most one check per lookup, max 3 output tokens, temperature 0. No Modal, no paid API.",
             "", f"Data: `bench/paraphrase_pairs.jsonl` ({len(hand)} hand-made pairs: "
             f"{sum(p['set'] == 'match' for p in hand)} paraphrases, {sum(p['set'] == 'tricky' for p in hand)} tricky "
             f"non-matches, {sum(p['set'] == 'bad_answer' for p in hand)} with a wrong stored answer) and "
             f"{len(qqp)} Quora pairs from `bench/datasets/cache_eval.jsonl` ({sum(p['same'] for p in qqp)} duplicates). "
             "A hit on a non-matching pair is a wrong hit: the cache would serve the wrong answer. QQP labels are "
             "noisy, so some QQP 'wrong hits' may be fine and some 'duplicates' would not share an answer.", ""]
    lines += verdict(results, hand, qqp)
    for title, keep in (("Hand-made pairs (paraphrases + tricky non-matches)", ("match", "tricky")),
                        ("Quora (QQP) pairs", ("qqp",))):
        lines += [f"## {title}", "", "| Setting | Hits | Correct hits | Wrong hits | Recall | Lookup p50 / p90 (ms) | 30B checks |",
                  "|---|---|---|---|---|---|---|"]
        for name, rows in results.items():
            rs = [r for r in rows if r["set"] in keep]
            h, g, w, rec = stats(rs)
            ms = [r["ms"] for r in rs]
            n_chk = sum(r["check"] in ("yes", "no", "error") for r in rs)
            lines.append(f"| {name} | {h} | {g} | {w} | {rec:.1%} | {pct(ms, .5):.1f} / {pct(ms, .9):.1f} | {n_chk} |")
        lines.append("")
    e_name, d_name, b_name = SETTINGS[4][0], SETTINGS[3][0], SETTINGS[1][0]
    E = {r["id"]: r for r in results[e_name]}
    D = {r["id"]: r for r in results[d_name]}
    B = {r["id"]: r for r in results[b_name]}
    chk_ms = [r["check_ms"] for r in results[e_name] if r["check_ms"]]
    lines += ["## The France pair and every hand-made pair under E", "",
              "| Pair | Old -> new | Should match | Best score | B hit | D hit | E hit | How (E) | 30B said |",
              "|---|---|---|---|---|---|---|---|---|"]
    for p in hand:
        e = E[p["id"]]
        lines.append(f"| {p['id']} | {p['old']} -> {p['new']} | {'yes' if p['same'] else 'no'} | "
                     f"{(e['score'] or 0):.3f} | {'HIT' if B[p['id']]['hit'] else '-'} | {'HIT' if D[p['id']]['hit'] else '-'} | "
                     f"{'HIT' if e['hit'] else '-'} | {e['via'] or '-'} | {e['check'] or '-'} |")
    lines += ["", "## The 30B check alone on the hand-made pairs (no cosine, no guard)", "",
              "| Set | Pairs | 30B said YES |", "|---|---|---|"]
    for s in ("match", "tricky", "bad_answer"):
        ids = [p["id"] for p in hand if p["set"] == s]
        lines.append(f"| {s} | {len(ids)} | {sum(alone[i] for i in ids)} |")
    lines += ["", f"30B check time: p50 {pct(chk_ms, .5):.0f} ms, p90 {pct(chk_ms, .9):.0f} ms over {len(chk_ms)} live checks "
              "(saved verdicts reused on a rerun keep their first time).", ""]
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
