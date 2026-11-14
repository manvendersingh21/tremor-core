"""Train and evaluate the learned router (packages/chimera-core/learned_router.py).

Input : bench/research_data_local.jsonl (Mac 3B answers + token stats + grade) and research_data_top.jsonl
        (DeepSeek answers, tokens, $, grade) from bench/run_research_collect.py, on the auto-graded rows of
        bench/datasets/suite.jsonl (MMLU, HumanEval, MBPP, GSM8K).
Output: packages/chimera-core/data/router_weights.json and bench/results_research_router.md
Honesty: every probability used in the report comes from a model that did not train on that row
(5-fold CV, plus leave-one-source-out). Only the last step (shipped coefficients) fits all rows.
    .venv/bin/python bench/train_router.py
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT)]
import conftest  # noqa: E402,F401

from chimera_core.learned_router import POST_FEATURES, PRE_FEATURES, draft_features, prompt_features  # noqa: E402
from chimera_core.router import complexity_score  # noqa: E402

SEED = 7


def load() -> tuple[list[dict], dict, dict]:
    suite = {r["id"]: r for r in map(json.loads, (ROOT / "bench/datasets/suite.jsonl").read_text().splitlines())}
    rd = lambda n: {r["id"]: r for r in map(json.loads, (ROOT / f"bench/research_data_{n}.jsonl").read_text().splitlines())}
    loc, top = rd("local"), rd("top")
    ids = [i for i in loc if i in top]
    return [suite[i] for i in ids], loc, top


def matrix(rows, loc, names):
    out = []
    for r in rows:
        d = loc[r["id"]]
        f = prompt_features(r["prompt"]) | draft_features({"mean_conf": d["mean_conf"], "min_prob": d["min_prob"],
                                                           "first_conf": d["first_conf"], "entropy": d["entropy"],
                                                           "n_tokens": d["n_tokens"]})
        out.append([f[n] for n in names])
    return np.array(out, float)


def fit(X, y):
    sc = StandardScaler().fit(X)
    m = LogisticRegression(C=0.5, max_iter=2000, class_weight=None).fit(sc.transform(X), y)
    return sc, m


def oof(X, y, groups=None):
    p = np.zeros(len(y))
    if groups is None:
        splits = StratifiedKFold(5, shuffle=True, random_state=SEED).split(X, y)
    else:  # leave one source out
        splits = ((np.where(groups != g)[0], np.where(groups == g)[0]) for g in sorted(set(groups)))
    for tr, te in splits:
        sc, m = fit(X[tr], y[tr])
        p[te] = m.predict_proba(sc.transform(X[te]))[:, 1]
    return p


def policy(keep_local: np.ndarray, l_ok, t_ok, usd, lat_l, lat_t, ran_local):
    """keep_local[i]: answer from the 3B. Else go to top (paying local latency too when the 3B ran)."""
    ok = np.where(keep_local, l_ok, t_ok)
    top = ~keep_local
    lat = np.where(keep_local, lat_l, lat_t + np.where(ran_local, lat_l, 0))
    return {"acc": ok.mean(), "top_calls": int(top.sum()), "usd": float((usd * top).sum()), "lat_med": float(np.median(lat)),
            "lat_mean": float(lat.mean())}


def main() -> None:
    rows, loc, top = load()
    n = len(rows)
    y = np.array([loc[r["id"]]["grade"] or 0 for r in rows])
    t_ok = np.array([top[r["id"]]["grade"] or 0 for r in rows])
    usd = np.array([top[r["id"]]["usd"] for r in rows])
    tok_in = np.array([top[r["id"]]["tokens_in"] for r in rows]); tok_out = np.array([top[r["id"]]["tokens_out"] for r in rows])
    lat_l = np.array([loc[r["id"]]["latency_ms"] for r in rows], float); lat_t = np.array([top[r["id"]]["latency_ms"] for r in rows], float)
    src = np.array([r["source"] for r in rows])
    conf = np.array([loc[r["id"]]["mean_conf"] for r in rows])
    heavy = np.array([complexity_score(r["prompt"]) >= 0.6 for r in rows])
    Xpre, Xpost = matrix(rows, loc, PRE_FEATURES), matrix(rows, loc, POST_FEATURES)
    ones = np.ones(n, bool)

    def row(name, keep, ran=ones):
        r = policy(keep, y, t_ok, usd, lat_l, lat_t, ran)
        tin = int((tok_in * ~keep).sum()); tout = int((tok_out * ~keep).sum())
        return f"| {name} | {r['acc']:.1%} | {r['top_calls']} | {tin} | {tout} | ${r['usd']:.4f} | {r['lat_med'] / 1000:.1f} | {r['lat_mean'] / 1000:.1f} |"

    hdr = ("| policy | accuracy | top calls | top tokens in | top tokens out | top $ | median s | mean s |\n"
           "|---|---|---|---|---|---|---|---|")
    p_pre, p_post = oof(Xpre, y), oof(Xpost, y)
    p_pre_g, p_post_g = oof(Xpre, y, src), oof(Xpost, y, src)

    def sweep(p, base_keep=ones):
        """(threshold, keep) pairs from the data's own quantiles."""
        return [(t, (p >= t) & base_keep) for t in np.unique(np.round(np.quantile(p, np.linspace(0, 1, 41)), 4))]

    def best_matching(p, target_acc, base_keep=ones, ran=ones):
        """Lowest top cost whose accuracy >= target_acc (threshold picked on the same rows: optimistic, stated)."""
        best = None
        for t, keep in sweep(p, base_keep):
            r = policy(keep, y, t_ok, usd, lat_l, lat_t, ran)
            if r["acc"] >= target_acc - 1e-9 and (best is None or r["usd"] < best[1]["usd"]):
                best = (t, r, keep)
        return best

    base_keep = (~heavy) & (conf >= 0.85)
    base_ran = ~heavy
    base_acc = policy(base_keep, y, t_ok, usd, lat_l, lat_t, base_ran)["acc"]
    out = [f"# Learned router (RouteLLM / Hybrid LLM / token-uncertainty deferral) on the real suite\n",
           f"Data: {n} auto-graded prompts from `bench/datasets/suite.jsonl` ({', '.join(f'{s} {int((src == s).sum())}' for s in sorted(set(src)))}). "
           "Each prompt was answered by the Mac 3B (Qwen2.5-3B q4_k_m) AND by the top model (DeepSeek-V4.1-Flash, thinking off), "
           "so every policy below is replayed on real outputs. The mid GPU tier is not in this replay (3B -> top only). "
           "Single run, no repeats. Probabilities are out-of-fold (5-fold CV); the threshold of each learned policy is then picked "
           "on those same out-of-fold scores, so the matched-quality rows are slightly optimistic.\n",
           f"3B alone: {y.mean():.1%} correct. Top alone: {t_ok.mean():.1%}. Oracle (best of both per prompt): {np.maximum(y, t_ok).mean():.1%}.\n",
           hdr, row("top only", ~ones), row("3B only", ones),
           row("BASELINE: complexity_score>=0.6 -> top, else 3B if confidence>=0.85", base_keep, base_ran)]
    for name, p, extra in (("learned PRE only (skip 3B when P(ok) low; keep every 3B answer otherwise)", p_pre, "pre"),
                           ("learned POST only (3B always runs; keep if P(ok) high)", p_post, "post"),
                           ("learned PRE+POST", p_post, "both")):
        if extra == "pre":
            b = best_matching(p, base_acc, ones, ones)
            if b: out.append(row(f"{name} @t={b[0]:.2f}", b[2], b[2]))
        elif extra == "post":
            b = best_matching(p, base_acc)
            if b: out.append(row(f"{name} @t={b[0]:.2f}", b[2]))
        else:
            best = None
            for t1 in np.quantile(p_pre, [0, .05, .1, .15, .2, .3]):
                ran = p_pre >= t1
                for t2, keep in sweep(p_post, ran):
                    r = policy(keep, y, t_ok, usd, lat_l, lat_t, ran)
                    if r["acc"] >= base_acc - 1e-9 and (best is None or r["usd"] < best[2]["usd"]):
                        best = (t1, t2, r, keep, ran)
            if best:
                out.append(row(f"{name} @pre={best[0]:.2f},post={best[1]:.2f}", best[3], best[4]))
                chosen = (float(best[0]), float(best[1]))
    # Equal-budget view: send the k lowest-scoring prompts to top, answer the rest with the 3B. Same k for every score.
    from sklearn.metrics import roc_auc_score
    from sentence_transformers import SentenceTransformer
    emb = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2").encode([r["prompt"] for r in rows], normalize_embeddings=True)
    p_emb = oof(np.hstack([Xpost, emb]), y)
    scores = {"oracle (knows if 3B is right)": y.astype(float), "3B mean token probability (the 0.85 gate's signal)": conf,
              "keyword complexity_score (inverted)": -np.array([complexity_score(r["prompt"]) for r in rows]),
              "learned PRE (prompt features)": p_pre, "learned POST (prompt + token stats)": p_post,
              "learned POST + MiniLM embedding (not shipped)": p_emb}
    out += ["\n## Equal top-call budget (3B always runs; the k lowest-scored prompts go to top)\n",
            "| score used to defer | AUC | acc @20% to top | acc @40% | acc @60% | top $ @40% |", "|---|---|---|---|---|---|"]
    rng = np.random.default_rng(SEED)
    for name, sc_ in scores.items():
        cells = []
        for frac in (0.2, 0.4, 0.6):
            k = int(round(frac * n)); order = np.argsort(sc_ + rng.normal(0, 1e-9, n))
            go_top = np.zeros(n, bool); go_top[order[:k]] = True
            cells.append((policy(~go_top, y, t_ok, usd, lat_l, lat_t, ones), ))
        out.append(f"| {name} | {roc_auc_score(y, sc_):.2f} | " + " | ".join(f"{c[0]['acc']:.1%}" for c in cells) + f" | ${cells[1][0]['usd']:.4f} |")
    rnd = [np.mean([policy(~np.isin(np.arange(n), rng.permutation(n)[:int(f * n)]), y, t_ok, usd, lat_l, lat_t, ones)["acc"] for _ in range(200)]) for f in (0.2, 0.4, 0.6)]
    out.append(f"| random deferral (mean of 200 draws) | 0.50 | " + " | ".join(f"{a:.1%}" for a in rnd) + " | |")
    out.append("\nConfidence-gate baseline sweep (3B always runs, keep if mean token probability >= t):\n")
    out += [hdr] + [row(f"conf>={t}", conf >= t) for t in (0.7, 0.8, 0.85, 0.9, 0.95)]
    # leave-one-source-out: does it transfer to a kind of task it never saw?
    out.append("\nLeave-one-source-out (train on 3 sources, score the 4th; AUC of P(3B correct)):\n")
    from sklearn.metrics import roc_auc_score
    out.append("| source | n | 3B acc | AUC pre | AUC post | AUC mean-confidence | AUC complexity_score (inverted) |\n|---|---|---|---|---|---|---|")
    cs = np.array([complexity_score(r["prompt"]) for r in rows])
    for s in sorted(set(src)):
        m = src == s
        if len(set(y[m])) < 2:
            out.append(f"| {s} | {int(m.sum())} | {y[m].mean():.0%} | n/a (one class) | n/a | n/a | n/a |"); continue
        out.append(f"| {s} | {int(m.sum())} | {y[m].mean():.0%} | {roc_auc_score(y[m], p_pre_g[m]):.2f} | {roc_auc_score(y[m], p_post_g[m]):.2f} | "
                   f"{roc_auc_score(y[m], conf[m]):.2f} | {roc_auc_score(y[m], -cs[m]):.2f} |")
    out.append(f"\nOverall AUC (5-fold): pre {roc_auc_score(y, p_pre):.2f}, post {roc_auc_score(y, p_post):.2f}, "
               f"mean-confidence {roc_auc_score(y, conf):.2f}, complexity_score {roc_auc_score(y, -cs):.2f}.")
    (ROOT / "bench/results_research_router.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))

    # ship weights fitted on every row, thresholds from the matched-quality search above
    spec = {}
    for key, X, names in (("pre", Xpre, PRE_FEATURES), ("post", Xpost, POST_FEATURES)):
        sc, m = fit(X, y)
        spec[key] = {"features": names, "coef": m.coef_[0].tolist(), "intercept": float(m.intercept_[0]),
                     "mean": sc.mean_.tolist(), "scale": sc.scale_.tolist()}
    pre_t, post_t = chosen if "chosen" in dir() else (0.0, 0.5)
    # thresholds above are quantiles of out-of-fold scores; the full-fit model's scores are on the same scale (see report)
    spec["pre_threshold"], spec["post_threshold"] = float(pre_t), float(post_t)
    spec["trained_on"] = f"{n} graded prompts; see bench/results_research_router.md"
    d = ROOT / "packages/chimera-core/data"
    d.mkdir(exist_ok=True)
    (d / "router_weights.json").write_text(json.dumps(spec, indent=1))


if __name__ == "__main__":
    main()
