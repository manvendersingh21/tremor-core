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

import re

from skeleton.core.demo import words

QWORDS = frozenset({"where", "when", "what", "how", "much", "which", "who", "why", "long"})


def content(text: str, drop: frozenset[str] = QWORDS) -> set[str]:
    return set(words(text)) - drop


class KBLookup:
    def __init__(self, entries: list[tuple[str, str]], *, drop: frozenset[str] = QWORDS, q_cov: float = 0.8,
                 k_cov: float = 0.8, margin: float = 0.2, semantic: "Semantic | None" = None, sem_sim: float = 0.84,
                 sem_margin: float = 0.2, guard=None) -> None:
        """semantic: a Semantic over the entries' keys, same order. It answers only when word overlap did not, and only
        at cosine >= sem_sim with sem_margin over the second entry; guard(question, key) can still refuse."""
        self.drop, self.q_cov, self.k_cov, self.margin = drop, q_cov, k_cov, margin
        self.raw, self.semantic, self.sem_sim, self.sem_margin, self.guard = entries, semantic, sem_sim, sem_margin, guard
        self.entries = [(content(k, drop), a) for k, a in entries]

    def match(self, question: str) -> str | None:
        if (hit := self._words(question)) is not None:
            return hit
        if self.semantic is not None:
            i = self.semantic.entry_for_question(question, self.sem_sim, self.sem_margin)
            if i is not None and (self.guard is None or self.guard(question, self.raw[i][0])):
                return self.raw[i][1]
        return None

    def _words(self, question: str) -> str | None:
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
    """Word overlap: the question has ONE best line, at least `min_frac` of the answer's content words are in that
    line, and no other line holds more of them. An answer drawn from another entry therefore fails.
    shortcut: two lines that match the question equally are a miss (safe, it climbs); no synonyms."""
    q, a = content(question, drop), content(answer, drop)
    if not q or not a:
        return False
    qs = sorted(((len(q & content(x, drop)), i) for i, x in enumerate(lines)), reverse=True)
    if qs[0][0] == 0 or (len(qs) > 1 and qs[0][0] == qs[1][0]):
        return False  # nothing matches the question, or two lines match it equally
    best = content(lines[qs[0][1]], drop)
    here = len(a & best)
    return here / len(a) >= min_frac and all(len(a & content(x, drop)) <= here for x in lines)


# ---- meaning: the repo's embedder (all-MiniLM-L6-v2 in live mode) ---------------------------------------------------
def _unit(v: list[float]) -> list[float]:
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / n for x in v]


_NUM = re.compile(r"\d[\d,.:\-]*\d|\d")
_DAY = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b", re.I)


def facts(text: str) -> dict[str, frozenset[str]]:
    """The checkable facts in a text: every number (prices, aisles, hours, durations, phone numbers) and weekday."""
    return {"num": frozenset(_NUM.findall(text)), "day": frozenset(d.lower() for d in _DAY.findall(text))}


def agree(a: dict, b: dict) -> bool:
    """Two entries agree when they share at least one kind of fact and, for each shared kind, one fact set holds the
    other. Entries with no facts at all, or with different prices, aisles or hours, do not agree."""
    shared = [k for k in a if a[k] and b[k]]
    return bool(shared) and all(a[k] <= b[k] or b[k] <= a[k] for k in shared)


class Unavailable(Exception):
    """The embedder failed (model not installed): meaning cannot decide."""


class Semantic:
    """Entries ranked by cosine to a question (or an answer), with a margin over the second-best entry.

    `embedder.embed(text) -> list[float]` is the cache's embedder. Entry vectors are built on the first use. An
    embedder error (model not installed) means "no match" for lookup and None for backed(), so word overlap decides.
    The margin protects against two entries that could be meant. A runner-up inside the margin is not a problem when its
    facts agree with the best entry's (same aisle, same hours, a price list that contains the other): then both are
    the cluster the answer may come from. A runner-up that disagrees on a price, aisle, hours or days, or states no
    facts at all, still means "not sure": no match. Agreement is decided from the facts, never from the cosine.
    An answer is backed when it is closest to an entry of the question's cluster and every number and weekday in it
    appears in that cluster.
    """

    def __init__(self, embedder, keys: list[str], texts: list[str] | None = None,
                 members: dict[int, list[int]] | None = None) -> None:
        """members: entry index -> entries it is made of (an "all hours" entry holds each hours line). When the
        question's cluster contains the whole entry, an answer from one of its parts is backed too."""
        self.embedder, self.keys, self.texts, self.members = embedder, keys, texts or keys, members or {}
        self._facts = [facts(t) for t in self.texts]
        self._kv: list[list[float]] | None = None
        self._tv: list[list[float]] | None = None

    def _vecs(self):
        if self._kv is None:
            self._kv = [_unit(self.embedder.embed(k)) for k in self.keys]
            self._tv = [_unit(self.embedder.embed(t)) for t in self.texts]
        return self._kv, self._tv

    def _cluster(self, text: str, which: int, min_sim: float, min_margin: float) -> list[int]:
        """[best, agreeing runners-up within the margin], or [] when unsure."""
        try:
            vs = self._vecs()[which]
            q = _unit(self.embedder.embed(text))
        except Exception as e:  # noqa: BLE001  no embedder available: the caller falls back to word overlap
            raise Unavailable from e
        sims = sorted(((sum(a * b for a, b in zip(q, v)), i) for i, v in enumerate(vs)), reverse=True)
        if not sims or sims[0][0] < min_sim:
            return []
        best = sims[0][1]
        out = [best]
        for sim, i in sims[1:]:
            if sims[0][0] - sim >= min_margin:
                break
            if not agree(self._facts[best], self._facts[i]):
                return []
            out.append(i)
        return out

    def entry_for_question(self, question: str, min_sim: float, min_margin: float) -> int | None:
        """One entry only (an answer served straight): any entry inside the margin refuses, agreeing or not."""
        try:
            c = self._cluster(question, 0, min_sim, min_margin)
        except Unavailable:
            return None
        return c[0] if len(c) == 1 else None

    def backed(self, question: str, answer: str, *, q_sim: float = 0.40, q_margin: float = 0.15,
               a_sim: float = 0.50, a_margin: float = 0.05) -> bool | None:
        """The question picks a cluster of agreeing entries, the answer is closest to one of them, and its numbers and
        weekdays are all in the cluster. None when the embedder is unavailable: the caller uses word overlap."""
        try:
            qc = self._cluster(question, 0, q_sim, q_margin)
            ac = self._cluster(answer, 1, a_sim, a_margin) if qc else []
        except Unavailable:
            return None
        if qc:
            qc = qc + [m for i in qc for m in self.members.get(i, [])]
        if not qc or not ac or ac[0] not in qc:
            return False
        have = {k: frozenset().union(*(self._facts[i][k] for i in qc)) for k in ("num", "day")}
        mine = facts(answer)
        return all(mine[k] <= have[k] for k in have)
