"""False-hit guard for the semantic cache (MeanCache, arXiv 2403.02694: cosine alone gives false hits).

A cosine hit is accepted only if the two prompts also agree on the things embeddings blur:
numbers, negation, and named entities / identifiers. No model, no training, microseconds per check.
shortcut: rule list, so a paraphrase that changes a rare word ("sum" vs "product") still passes;
upgrade to a trained pair classifier (see docs/research.md) if the measured false-hit rate is too high.
"""
from __future__ import annotations

import re

NEG = {"not", "no", "never", "without", "cannot", "cant", "dont", "doesnt", "isnt", "wont", "none", "neither", "nor",
       "avoid", "except", "unless"}
NUM = re.compile(r"\d+(?:[.,]\d+)*")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_']*")
# Antonym-like swaps that flip the answer while keeping the cosine high.
OPPOSITES = [{"min", "max"}, {"minimum", "maximum"}, {"smallest", "largest"}, {"lowest", "highest"},
             {"first", "last"}, {"before", "after"}, {"increase", "decrease"}, {"ascending", "descending"},
             {"encode", "decode"}, {"true", "false"}, {"odd", "even"}, {"add", "subtract"}, {"sum", "product"}]


def _signature(text: str) -> tuple[frozenset, bool, frozenset, frozenset, frozenset]:
    nums = frozenset(n.replace(",", "") for n in NUM.findall(text))
    words = WORD.findall(text)
    low = {w.lower().replace("'", "") for w in words}
    neg = bool(low & NEG) or "n't" in text.lower()
    # Entities: capitalised words not at a sentence start, plus identifiers (snake_case, camelCase, ALLCAPS).
    ents = set()
    for i, w in enumerate(words):
        if (w[0].isupper() and i > 0) or "_" in w or (len(w) > 1 and w.isupper()) or re.search(r"[a-z][A-Z]", w):
            ents.add(w.lower().replace("'", ""))  # same apostrophe rule as `low`
    opp = frozenset(w for pair in OPPOSITES for w in pair if w in low)
    return nums, neg, frozenset(ents), opp, frozenset(low)


def consistent(a: str, b: str) -> bool:
    """True when the two prompts agree on numbers, negation, entities and opposite-word choice."""
    na, ga, ea, oa, la = _signature(a)
    nb, gb, eb, ob, lb = _signature(b)
    # An entity only counts as missing if the other prompt does not mention it at all (any case).
    return na == nb and ga == gb and oa == ob and ea <= lb and eb <= la


def make_guard():
    """A callable for SemanticCache(guard=...): (query, cached_prompt, similarity) -> accept?"""
    return lambda query, cached, sim: consistent(query, cached)
