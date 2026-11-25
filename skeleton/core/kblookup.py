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


KEY_DF = 3  # a word in at most this many entries names a specific thing ("express", "canada", "paypal")
# Everyday words that are rare in a small KB but name no thing: function words, plain verbs, time words.
NOT_THINGS = frozenset(
    "one two if with without from into by as or and but not no never only still also just again instead even "
    "take go use send add edit change forgot arrived end need want put come back new same other every first "
    "until once after before during while today now tonight tomorrow yesterday usually always".split())


def key_things(texts: list[str], text: str, max_df: int = KEY_DF) -> set[str]:
    """Words of `text` that name a specific thing in the knowledge base: found in 1 to `max_df` entries.
    Numbers are left to facts(); common words ("order", "shipping") are in too many entries to name one thing."""
    df: dict[str, int] = {}
    for t in texts:
        for w in content(t):
            df[w] = df.get(w, 0) + 1
    return {w for w in content(text) - NOT_THINGS if not w.isdigit() and 0 < df.get(w, 0) <= max_df}


def joins_entries(texts: list[str], question: str, answer: str = "") -> bool:
    """True when the question and answer name two or more specific KB things that no single entry states together
    ("express shipping" in the cost entry, "Canada" in the international entry). Such an answer joins entries: it is
    never backed, whatever a judge says. Every check path calls this first (`one_entry` below)."""
    key = key_things(texts, question)
    if len(key) >= 2 and not any(key <= content(t) for t in texts):
        return True  # the question asks about things no one entry states together
    return bool(answer) and not one_source(texts, answer, question)


SENTENCE = re.compile(r"(?<=[.!?;])\s+|\s+(?:but|however)\s+", re.I)


def one_source(texts: list[str], answer: str, question: str = "", min_frac: float = 0.6, min_words: int = 3) -> bool:
    """One entry backs every sentence of the answer: at least `min_frac` of each sentence's content words are in that
    entry or in the question (a sentence may restate or deny what was asked: "Germany is not available"). A sentence
    with fewer than `min_words` content words ("Yes.") is skipped. An answer whose sentences need two entries ("edit
    until it ships" from one, "after it ships, return it for a refund" from another) is a join."""
    parts = [p for p in (content(s) for s in SENTENCE.split(answer)) if len(p) >= min_words]
    if not parts:
        return True
    asked = content(question)
    # each sentence needs a word of the entry itself: question words alone back nothing
    return any(all(p & e and len(p & (e | asked)) >= min_frac * len(p) for p in parts)
               for e in (content(t) for t in texts))


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
        if joins_entries([f"{k} {a}" for k, a in self.raw], question):
            return None  # the question names things from two entries: no single FAQ answer is right
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
    if not q or not a or joins_entries(lines, question, answer):
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

    def candidates(self, question: str, q_sim: float = 0.40, q_margin: float = 0.15, k: int = 4) -> list[int]:
        """Entries the question may be about: cosine >= q_sim and within q_margin of the best, at most k, plus the
        parts of any combined entry among them. Agreement is not required here: the judge reads them all."""
        try:
            vs = self._vecs()[0]
            q = _unit(self.embedder.embed(question))
        except Exception as e:  # noqa: BLE001
            raise Unavailable from e
        sims = sorted(((sum(a * b for a, b in zip(q, v)), i) for i, v in enumerate(vs)), reverse=True)
        if not sims or sims[0][0] < q_sim:
            return []
        out = [i for s, i in sims[:k] if sims[0][0] - s < q_margin]
        return out + [m for i in out for m in self.members.get(i, []) if m not in out]

    def nearest(self, text: str, k: int = 2) -> list[int]:
        """The k entries whose full text is closest to `text` (the answer's likely sources)."""
        try:
            vs = self._vecs()[1]
            a = _unit(self.embedder.embed(text))
        except Exception as e:  # noqa: BLE001
            raise Unavailable from e
        return [i for _, i in sorted(((sum(x * y for x, y in zip(a, v)), i) for i, v in enumerate(vs)), reverse=True)[:k]]

    def backed_loose(self, question: str, answer: str, a_sim: float = 0.50) -> bool:
        """The answer's closest entry is one the question may be about, and ONE entry in the cluster covers all its
        facts (no joined-entry claims). Entries that share facts with a candidate are added to the cluster first."""
        if joins_entries(self.texts, question, answer):
            return False
        try:
            qc = self.candidates(question)
            if not qc:
                return False
            # an entry that states the same facts as a candidate is a source too ("5 to 7 days" in a policy and an FAQ)
            qc = qc + [i for i in range(len(self.texts)) if i not in qc and any(agree(self._facts[i], self._facts[c])
                                                                                  for c in qc)]
            vs = self._vecs()[1]
            a = _unit(self.embedder.embed(answer))
        except Exception:  # noqa: BLE001
            return False
        sim, best = max((sum(x * y for x, y in zip(a, v)), i) for i, v in enumerate(vs))
        if sim < a_sim or best not in qc:
            return False
        return self._one_entry_covers(qc, facts(answer))

    def _one_entry_covers(self, qc: list[int], mine: dict) -> bool:
        """ONE entry in the cluster states every fact in `mine`. Prevents joined-entry claims like
        'express shipping goes to Canada' built from two entries that each state only part of it.
        When the answer has no facts (num, day), the check passes (content words guard it elsewhere)."""
        if not any(mine[k] for k in mine):
            return True
        return any(all(mine[k] <= self._facts[i][k] for k in mine) for i in qc)

    def backed(self, question: str, answer: str, *, q_sim: float = 0.40, q_margin: float = 0.15,
               a_sim: float = 0.50, a_margin: float = 0.05) -> bool | None:
        """The question picks a cluster of agreeing entries, the answer is closest to one of them, its numbers and
        weekdays are all in the cluster, AND one single entry covers every fact (no joined-entry claims).
        None when the embedder is unavailable: the caller uses word overlap."""
        if joins_entries(self.texts, question, answer):
            return False
        try:
            qc = self._cluster(question, 0, q_sim, q_margin)
            ac = self._cluster(answer, 1, a_sim, a_margin) if qc else []
        except Unavailable:
            return None
        if qc:
            qc = qc + [m for i in qc for m in self.members.get(i, [])]
        if not qc or not ac or ac[0] not in qc:
            return False
        mine = facts(answer)
        return self._one_entry_covers(qc, mine)


def swarm_check(lines: list[str], sem: "Semantic | None", judge, question: str, answer: str) -> bool:
    """The swarm's answer check (after the app's own number check).

    - No embedder (demo, CI): word overlap only.
    - Embedder, no judge: meaning (strict cluster rule) or word overlap.
    - Embedder and judge (live): the answer must pass a structural test (strict meaning, word overlap, or the loose
      rule: closest to an entry the question may be about, with its facts) AND the judge's yes/no against those
      entries. The judge closes the near-miss class ("reset my router" vs the password entry), which shares words and
      meaning with an entry but asks about another thing; the loose rule lets new wordings of a fact through.
    """
    # one entry must state every specific thing asked and answered: checked first, so no judge YES can override it
    if joins_entries(sem.texts if sem is not None else lines, question, answer):
        return False
    if sem is None:
        return backed(lines, question, answer)
    strict = sem.backed(question, answer)
    if strict is None:  # embedder failed: words decide
        return backed(lines, question, answer)
    if judge is None:
        return strict or backed(lines, question, answer)
    if not (strict or backed(lines, question, answer) or sem.backed_loose(question, answer)):
        return False
    # the judge reads the entries the question may be about AND the entries the answer is closest to (its sources)
    ids = list(dict.fromkeys(sem.candidates(question) + sem.nearest(answer)))
    return judge.agrees(question, [sem.texts[i] for i in ids] or matched_lines(lines, question), answer)


def swarm_covered(sem: "Semantic | None", judge, question: str) -> bool:
    """Is there a KB fact a model could use? No embedder: assume yes (old behaviour). No entry close enough: no.
    With a judge: it reads the candidate entries and says whether they answer this exact question."""
    if sem is None:
        return True
    if joins_entries(sem.texts, question):
        return False  # no single entry states it: no tier could pass the check, so none is asked
    try:
        c = sem.candidates(question)
    except Unavailable:
        return True
    # an entry that names a specific thing the question names is a candidate too, when meaning missed it
    # ("track my package" -> the order entry's "click Track")
    key = key_things(sem.texts, question)
    c += [i for i, t in enumerate(sem.texts) if i not in c and key & content(t)][:4]
    if not c:
        return False
    return True if judge is None else judge.covers(question, [sem.texts[i] for i in c])
