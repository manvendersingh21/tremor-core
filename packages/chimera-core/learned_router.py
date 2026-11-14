"""Learned router: logistic regression that predicts "the local 3B will answer this correctly".

Ideas from RouteLLM (arXiv 2406.18665) and Hybrid LLM (2404.14618): learn the route from outcomes instead of
keywords. The post-draft model adds token-confidence features, the deferral signal studied in
"Language Model Cascades: Token-level uncertainty and beyond" (2404.10136) and speculative cascades (2405.19261).

Two models, both read from one JSON file written by bench/train_router.py:
  pre  : prompt features only. Decides before any model runs whether to skip the 3B.
  post : prompt features + the 3B's token probabilities. Decides whether to keep the 3B answer.
Pure Python at run time (no numpy / sklearn). Off by default (`LadderConfig.learned_router = ""`).
shortcut: trained on ~180 graded prompts of 4 benchmark kinds; retrain with bench/train_router.py on your own
traffic before turning it on for anything else.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

HEAVY = re.compile(r"\b(refactor|architecture|migrate|redesign|implement|debug|optimi[sz]e|concurrency|design)\b", re.I)
PRE_FEATURES = ["log_chars", "fences", "heavy_hints", "digit_frac", "has_def", "has_choices", "code_words",
                "math_words", "lines", "question_marks"]
POST_FEATURES = PRE_FEATURES + ["mean_conf", "min_prob", "first_conf", "entropy", "log_tokens"]


def prompt_features(p: str) -> dict[str, float]:
    n = max(len(p), 1)
    return {
        "log_chars": math.log1p(len(p)), "fences": min(p.count("```") // 2, 3), "heavy_hints": min(len(HEAVY.findall(p)), 3),
        "digit_frac": sum(c.isdigit() for c in p) / n, "has_def": float("def " in p),
        "has_choices": float(bool(re.search(r"^\s*[A-D][.)] ", p, re.M))),
        "code_words": len(re.findall(r"\b(function|return|python|class|import|array|list|string|test)\b", p, re.I)),
        "math_words": len(re.findall(r"\b(how many|total|each|per|cost|sum|average|percent|times|more than)\b", p, re.I)),
        "lines": min(p.count("\n"), 60), "question_marks": min(p.count("?"), 5),
    }


def draft_features(d: dict) -> dict[str, float]:
    """d: mean_conf, min_prob, first_conf, entropy, n_tokens."""
    return {"mean_conf": d["mean_conf"], "min_prob": d["min_prob"], "first_conf": d["first_conf"],
            "entropy": d["entropy"], "log_tokens": math.log1p(d["n_tokens"])}


def draft_stats(logprobs: list[float], mean_conf: float, entropy: float) -> dict:
    probs = [math.exp(x) for x in logprobs] or [0.0]
    return {"mean_conf": mean_conf, "min_prob": min(probs), "first_conf": probs[0], "entropy": entropy,
            "n_tokens": len(logprobs)}


class LinearModel:
    def __init__(self, spec: dict) -> None:
        self.names, self.w, self.b = spec["features"], spec["coef"], spec["intercept"]
        self.mu, self.sd = spec["mean"], spec["scale"]

    def prob(self, feats: dict[str, float]) -> float:
        z = self.b + sum(w * (feats[n] - m) / (s or 1.0) for n, w, m, s in zip(self.names, self.w, self.mu, self.sd))
        return 1 / (1 + math.exp(-max(min(z, 30), -30)))


class LearnedRouter:
    def __init__(self, spec: dict) -> None:
        self.pre, self.post = LinearModel(spec["pre"]), LinearModel(spec["post"])
        self.pre_threshold, self.post_threshold = spec["pre_threshold"], spec["post_threshold"]

    @classmethod
    def load(cls, path: str | Path) -> "LearnedRouter":
        return cls(json.loads(Path(path).expanduser().read_text()))

    def skip_local(self, prompt: str) -> bool:
        """True: the 3B probably fails this prompt, go straight up the ladder."""
        return self.pre.prob(prompt_features(prompt)) < self.pre_threshold

    def keep_local(self, prompt: str, logprobs: list[float], mean_conf: float, entropy: float) -> bool:
        f = prompt_features(prompt) | draft_features(draft_stats(logprobs, mean_conf, entropy))
        return self.post.prob(f) >= self.post_threshold
