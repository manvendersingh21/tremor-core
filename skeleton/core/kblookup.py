"""KB lookup: find the knowledge-base entries that match a question. $0, no model, no network.

    lookup = KBLookup([(key, answer), ...])
    lookup.match("how do i reset my password")   # the entry's answer when the match is strong, else None

An entry matches strongly when the question's content words and the entry key's content words cover each other
(both at least `q_cov` and `k_cov`) and no other entry comes close (`margin`). Anything else returns None, so the
question goes on to the cache and the models. `backed()` is the answer check for help-desk-like apps: an answer is
backed when most of its content words appear in the entries that match the question (word overlap, no model).
shortcut: word overlap knows no synonyms ("talk to a human" does not match "contact a person"); such a question
falls through to the cache and the models. Upgrade to embeddings when the knowledge base passes ~200 entries.
"""
from __future__ import annotations

from skeleton.core.demo import words

QWORDS = frozenset({"where", "when", "what", "how", "much", "which", "who", "why", "long"})


def content(text: str, drop: frozenset[str] = QWORDS) -> set[str]:
    return set(words(text)) - drop


class KBLookup:
    def __init__(self, entries: list[tuple[str, str]], *, drop: frozenset[str] = QWORDS, q_cov: float = 0.8,
                 k_cov: float = 0.8, margin: float = 0.2) -> None:
        self.drop, self.q_cov, self.k_cov, self.margin = drop, q_cov, k_cov, margin
        self.entries = [(content(k, drop), a) for k, a in entries]

    def match(self, question: str) -> str | None:
        q = content(question, self.drop)
        if not q:
            return None
        scored = []
        for k, a in self.entries:
            both = len(q & k)
            if k and both:
                scored.append((both / len(q), both / len(k), a))
        scored.sort(key=lambda s: -(s[0] + s[1]))
        if not scored or scored[0][0] < self.q_cov or scored[0][1] < self.k_cov:
            return None
        if len(scored) > 1 and scored[0][0] + scored[0][1] - (scored[1][0] + scored[1][1]) < self.margin:
            return None  # two entries fit about equally: not sure which one is meant
        return scored[0][2]


def matched_lines(lines: list[str], question: str, n: int = 3, drop: frozenset[str] = QWORDS) -> list[str]:
    """The (at most n) lines that share the most content words with the question; none when nothing is shared."""
    q = content(question, drop)
    scored = sorted(((len(q & content(x, drop)), x) for x in lines), key=lambda s: -s[0])
    best = scored[0][0] if scored else 0
    return [x for s, x in scored[:n] if s > 0 and s >= best - 1]  # near-best lines only


def backed(lines: list[str], question: str, answer: str, *, min_frac: float = 0.6,
           drop: frozenset[str] = QWORDS) -> bool:
    """True when at least `min_frac` of the answer's content words are in the lines that match the question."""
    support = matched_lines(lines, question, drop=drop)
    a = content(answer, drop)
    if not support or not a:
        return False
    have = set().union(*(content(x, drop) for x in support))
    return len(a & have) / len(a) >= min_frac
