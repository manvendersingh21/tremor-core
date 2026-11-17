"""False-hit guard for the semantic cache (MeanCache, arXiv 2403.02694: cosine alone gives false hits).

A cosine hit is accepted only if the two prompts also agree on the things embeddings blur:
numbers, negation, and named entities / identifiers. No model, no training, microseconds per check.
shortcut: rule list, so a paraphrase that changes a rare word ("sum" vs "product") still passes;
upgrade to a trained pair classifier (see docs/research.md) if the measured false-hit rate is too high.
"""
from __future__ import annotations

import re

NEG = {"not", "no", "never", "without", "cannot", "cant", "dont", "doesnt", "isnt", "wont", "none", "neither", "nor",
       "avoid", "except", "unless", "non"}  # "non": "romantic" vs "non-romantic" (bench/results_paraphrase_cache.md)
NUM = re.compile(r"\d+(?:[.,]\d+)*")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_']*")
# Antonym-like swaps that flip the answer while keeping the cosine high.
OPPOSITES = [{"min", "max"}, {"minimum", "maximum"}, {"smallest", "largest"}, {"lowest", "highest"},
             {"first", "last"}, {"before", "after"}, {"increase", "decrease"}, {"ascending", "descending"},
             {"encode", "decode"}, {"true", "false"}, {"odd", "even"}, {"add", "subtract"}, {"sum", "product"}]


def _signature(text: str) -> tuple[frozenset, bool, tuple, frozenset, frozenset]:
    nums = frozenset(n.replace(",", "") for n in NUM.findall(text))
    words = WORD.findall(text)
    key = lambda w: re.sub(r"'s$", "", w.lower()).replace("'", "")  # noqa: E731  "Japan's" -> "japan"
    low = {key(w) for w in words}
    neg = bool(low & NEG) or "n't" in text.lower()
    # Entities: capitalised words not at a sentence start (but not the pronoun "I"), plus identifiers
    # (snake_case, camelCase, ALLCAPS).
    ents: dict[str, None] = {}  # insertion order = order of first appearance
    for i, w in enumerate(words):
        if w != "I" and ((w[0].isupper() and i > 0) or "_" in w or (len(w) > 1 and w.isupper())
                         or re.search(r"[a-z][A-Z]", w)):
            ents.setdefault(key(w))  # same rule as `low`
    opp = frozenset(w for pair in OPPOSITES for w in pair if w in low)
    return nums, neg, tuple(ents), opp, frozenset(low)


def consistent(a: str, b: str) -> bool:
    """True when the two prompts agree on numbers, negation, entities (and their order) and opposite-word choice."""
    na, ga, oa_ents, oa, la = _signature(a)
    nb, gb, ob_ents, ob, lb = _signature(b)
    ea, eb = frozenset(oa_ents), frozenset(ob_ents)
    # Same entities in another order flip the question: "Celsius to Fahrenheit" vs "Fahrenheit to Celsius".
    # shortcut: also rejects "Python vs Java" / "Java vs Python", which would share an answer (safe direction).
    if ea == eb and oa_ents != ob_ents:
        return False
    # An entity only counts as missing if the other prompt does not mention it at all (any case).
    return na == nb and ga == gb and oa == ob and ea <= lb and eb <= la


def make_guard():
    """A callable for SemanticCache(guard=...): (query, cached_prompt, similarity) -> accept?"""
    return lambda query, cached, sim: consistent(query, cached)
