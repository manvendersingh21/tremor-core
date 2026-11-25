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
FUNCTION_WORDS = frozenset(
    "one two if with without from into by as or and but not no never only still also just again instead even "
    "until once after before during while today now tonight tomorrow yesterday usually always "
    "under over within about than more less very full must should could would may might will".split())
NOT_THINGS = FUNCTION_WORDS | frozenset(
    "take go use send forgot arrived end need want put come back new same other every first "
    "used".split())  # plain actions: they name no thing, but they do change a claim (coverage keeps them)


def key_things(texts: list[str], text: str, max_df: int = KEY_DF) -> set[str]:
    """Words of `text` that name a specific thing in the knowledge base: found in 1 to `max_df` entries.
    Numbers are left to facts(); common words ("order", "shipping") are in too many entries to name one thing."""
    df: dict[str, int] = {}
    for t in texts:
        for w in content(t):
            df[w] = df.get(w, 0) + 1
    return {w for w in content(text) - NOT_THINGS if not w.isdigit() and 0 < df.get(w, 0) <= max_df}


def joins_entries(texts: list[str], question: str, answer: str = "", groups: dict[int, list[int]] | None = None,
                  near=None) -> bool:
    """True when an answer is not backed by ONE entry. The single guard every serving path calls first, so no judge
    YES can let such an answer through:
    - the question names a thing no entry names ("my router": `foreign_thing`);
    - the question names two specific KB things no single entry states together ("express shipping" + "Canada");
    - the answer is not backed sentence by sentence by one entry (`one_source`).
    groups: combined entry -> its parts (all hours, all policies): their parts may back the sentences of one answer
    together, and the combined text itself never backs anything. near(word) -> bool: a word no entry has is close in
    meaning to one that some entry has (the embedder); None (demo, CI) means not close."""
    groups = groups or {}
    if foreign_thing(texts, question, near):
        return True
    base = [t for i, t in enumerate(texts) if i not in groups]
    key = key_things(base, question)
    if len(key) >= 2 and not any(key <= content(t) for t in base):
        return True  # the question asks about things no one entry states together
    if not answer:
        return False
    return not one_source(texts, answer, question, groups)


_CLOCK = re.compile(r"\b\d{1,2}(:\d\d)?\s*(am|pm|a\.m\.|p\.m\.)|\b\d{1,2}:\d\d\b|\b(right now|now|currently|tonight)\b", re.I)
_VERDICT = re.compile(r"^\W*(yes|no|nope|yep)\b", re.I)


def time_verdict(question: str, answer: str) -> bool:
    """The question asks about a clock time or "now" and the answer opens with yes or no. No entry states that verdict
    (the bot does not know the time, and "open at 10 pm" when it closes at 22:00 is a judgement call): only the hours
    themselves may be served."""
    return bool(_CLOCK.search(question) and _VERDICT.search(answer))


SENTENCE = re.compile(r"(?<=[.!?;])\s+|\s+(?:but|however)\s+", re.I)


VERDICT_WORDS = frozenset("yes no yep nope sure".split())
NEGATIONS = frozenset("not never without".split())
GROUP_FRAC = 0.8  # a sentence backed by one part of a combined entry, when the answer uses several parts
IMPORT_DF = 6  # a KB word in at most this many entries is a term of those entries ("phone", "vegan", "canada")
# a thing the customer owns or asks about: "my router", "your packaging" ("the process", "a while" name no thing)
_DET = re.compile(r"\b(?:my|your|our)\s+([a-z][a-z'-]*(?:\s+[a-z][a-z'-]*){0,2})", re.I)
NEAR_SIM = 0.47  # all-MiniLM-L6-v2 word cosine: "router" 0.36 to its nearest KB word, "package" 0.56 ("delivery")


def foreign_thing(texts: list[str], question: str, near=None) -> bool:
    """The question names a thing no entry names: a phrase after my/your/our whose every content word is in no
    entry and (with an embedder) close to no KB word. "reset my router" -> True; "track my package" -> False live
    ("package" is near "delivery"), True in demo (no embedder: no synonyms, a miss, never a wrong answer)."""
    vocab = set().union(*(content(t) for t in texts)) if texts else set()
    for m in _DET.finditer(question):
        phrase = []
        for w in m.group(1).lower().split():
            ws = content(w) - NOT_THINGS
            if not ws:
                break  # a stop word ends the phrase
            phrase += ws
        if phrase and all(w not in vocab and not w.isdigit() and not (near and near(w)) for w in phrase):
            return True
    return False


_THING_AT = re.compile(r"\b(?:a|an|the|your|my|our|each|every|any|no)\s+([a-z][a-z-]*)|(?<=[a-z,;] )([A-Z][A-Za-z]+)")


def things(texts: list[str]) -> set[str]:
    """Words that name things in these entries (nouns, not verbs): an entry's label (before ":" or the FAQ question),
    a word after a/the/your/each, or a capitalised word inside a sentence ("Canada", "PayPal")."""
    out: set[str] = set()
    for t in texts:
        label = (t.split(" A: ", 1)[0] if t.startswith("Q: ") else t.split("?", 1)[0] if "?" in t[:120]
                 else t.split(":", 1)[0] if ":" in t[:60] else "")
        out |= content(label)
        for m in _THING_AT.finditer(t):
            out |= content(m.group(1) or m.group(2))
    return out - NOT_THINGS


_VERB_CUE = re.compile(r"\b(?:can|cannot|can't|will|we|you|they|must|may|then|please|be|been|not|i|it)\s+([a-z]+)", re.I)


def verbish(texts: list[str]) -> set[str]:
    """Words used as verbs in these texts: after to/can/will/we/you/must..., or ending in -ed/-ing. They name an
    action, not a thing, so a sentence may use them without the entry ("arrive", "choose", "returned")."""
    out: set[str] = set()
    for t in texts:
        out |= {w for m in _VERB_CUE.finditer(t) for w in content(m.group(1))}
        out |= {w for w in content(t) if w.endswith(("ed", "ing")) and len(w) > 4}
    return out


def _label(text: str) -> set[str]:
    """The words before the first ":" (an hours line's service, an item's name, a policy's topic)."""
    return content(text.split(":", 1)[0]) if ":" in text else set()


def _bigrams(text: str) -> set[tuple[str, str]]:
    """Adjacent content words, both orders ("express shipping", "shipping express")."""
    ws = [w for w in words(text) if w not in QWORDS]
    return {(a, b) for a, b in zip(ws, ws[1:])} | {(b, a) for a, b in zip(ws, ws[1:])}


def _units(text: str) -> list[tuple[set[str], dict, str]]:
    """An entry's sentences and adjacent sentence pairs: (content words, facts, text)."""
    ss = [s for s in SENTENCE.split(text) if s.strip()]
    out = [s for s in ss] + [f"{a} {b}" for a, b in zip(ss, ss[1:])]
    return [(content(s), facts(s), s) for s in out]


def one_source(texts: list[str], answer: str, question: str = "", groups: dict[int, list[int]] | None = None,
               min_frac: float = 0.5, min_words: int = 3) -> bool:
    """One entry backs every sentence of the answer. A sentence is backed by an entry when one sentence of the entry
    (or two adjacent ones) holds at least `min_frac` of its content words (question words no entry has may stand in:
    "Germany is not available") and at least one of its own, and states every number and day of it; and the entry
    names every specific thing the sentence names (`things` in at most KEY_DF entries: "Canada", "PayPal", "tofu")
    and every KB term the question asks about ("phone" is not in the chat-hours line). A sentence that says "free"
    about a thing whose sentence gives a price contradicts it.
    All sentences must come from one entry, or from the parts of one combined entry (`groups`: all hours, all
    policies, a diet tag's items). A combined entry backs a sentence itself only when each of its numbers and days
    sits in a part the sentence names by its label ("oat milk ... $3.49, almond milk ... $3.29" from the vegan list;
    not "phone support ... 10:00 to 16:00 Saturday", which are the chat hours). A sentence with fewer than
    `min_words` content words, no facts and no thing ("Yes.") is skipped."""
    groups = groups or {}
    base = [i for i in range(len(texts)) if i not in groups]
    df: dict[str, int] = {}
    for i in base:
        for w in content(texts[i]):
            df[w] = df.get(w, 0) + 1
    # question words may stand in a sentence's coverage ("Used items are not eligible"); the things it names may not:
    # those must be in the entry (key, terms, compounds below)
    asked = content(question)
    named = things([texts[i] for i in base])
    acts = verbish([texts[i] for i in base] + [answer]) - named
    pairs = {i: _bigrams(texts[i]) for i in base}
    kb_pairs = set().union(*pairs.values()) if pairs else set()  # compounds the KB itself uses
    units = {i: _units(texts[i]) for i in base}
    ents = {i: content(texts[i]) for i in range(len(texts))}
    own = {c: {j: _label(texts[j]) - set().union(*(_label(texts[k]) for k in parts if k != j)) for j in parts}
           for c, parts in groups.items()}
    q = content(question)
    sources = []
    for s in SENTENCE.split(answer):
        # function words do not count toward coverage; negations do ("not", "no", "never" change the claim)
        p, fs = content(s) - VERDICT_WORDS - (FUNCTION_WORDS - NEGATIONS), facts(s)
        key = {w for w in p - NOT_THINGS - acts if not w.isdigit() and 0 < df.get(w, 0) <= KEY_DF}
        # a compound thing ("express shipping") must be in the entry as a compound: "American Express" is not it
        comp = {b for b in _bigrams(s) & kb_pairs if b[0] in named and b[1] in named and (set(b) & key)}
        # (specific actions too: an answer may not swap the question's "edit" into "cancel until it ships")
        terms = {w for w in (p & q) - NOT_THINGS if not w.isdigit() and 0 < df.get(w, 0) <= IMPORT_DF}
        if len(p) < min_words and not any(fs.values()) and not terms and not key:
            continue  # "Yes." names nothing; "That includes PayPal." names a thing: checked
        ok, strong = set(), set()
        for i in base:
            # "used" is stated by "unused" (its negation): the entry names the same thing
            if not all(w in ents[i] or "un" + w in ents[i] for w in terms | key) or not comp <= pairs[i]:
                continue
            for u, uf, ut in units[i]:
                if (p & u and len(p & (u | asked)) >= min_frac * len(p)
                        and all(fs[k] <= uf[k] for k in fs) and not _free_vs_price(s, key, units[i])):
                    ok.add(i)
                    if len(p & u) >= GROUP_FRAC * len(p):
                        strong.add(i)
        for c, parts in groups.items():  # a list drawn from a combined entry's parts, each fact by its part's label
            if (not (terms | key) <= ents[c] or not comp <= _bigrams(texts[c])
                    or len(p & (ents[c] | asked)) < min_frac * len(p)):
                continue
            pf = {j: facts(texts[j]) for j in parts}
            if all(any(x in pf[j][k] and own[c][j] & p for j in parts) for k in fs for x in fs[k]) and any(fs.values()):
                ok.add(c)
                strong.add(c)
        if not ok:
            return False
        sources.append((ok, strong))
    if not sources:
        return True
    if set.intersection(*(ok for ok, _ in sources)):
        return True
    # parts of one combined entry (each hours line) may back one sentence each, when each sentence is its part nearly
    # word for word: "That includes phone support" after the chat hours is a join, not a list of parts
    return any(all(strong & (set(parts) | {c}) for _, strong in sources) for c, parts in groups.items())


def _free_vs_price(sentence: str, key: set[str], units) -> bool:
    """The sentence says a thing is free, while the entry's sentence about that thing gives a price, not "free"."""
    key = key - {"free"}
    if not re.search(r"\bfree\b", sentence, re.I) or not key:
        return False
    return any(key <= u and "$" in ut and not re.search(r"\bfree\b", ut, re.I) for u, _, ut in units)


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
        near = self.semantic.near if self.semantic is not None else None
        if joins_entries([f"{k} {a}" for k, a in self.raw], question, near=near):
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
_DAY = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|every day|daily|weekend|weekday)s?\b", re.I)


def facts(text: str) -> dict[str, frozenset[str]]:
    """The checkable facts in a text: every number (prices, aisles, hours, durations, phone numbers) and weekday."""
    days = {"daily": "every day"}  # one spelling per day claim
    return {"num": frozenset(_NUM.findall(text)),
            "day": frozenset(days.get(d.lower(), d.lower()) for d in _DAY.findall(text))}


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
        self._wv: dict[str, list[float]] = {}  # word vectors for near()

    def _word(self, w: str) -> list[float]:
        if w not in self._wv:
            self._wv[w] = _unit(self.embedder.embed(w))
        return self._wv[w]

    def near(self, word: str) -> bool:
        """A word no entry has is close in meaning to a word some entry has (cosine >= NEAR_SIM)."""
        try:
            v = self._word(word)
            vocab = set().union(*(content(t) for t in self.texts))
            return any(sum(a * b for a, b in zip(v, self._word(x))) >= NEAR_SIM for x in vocab if not x.isdigit())
        except Exception:  # noqa: BLE001  no embedder: no synonyms
            return False

    def joins(self, question: str, answer: str = "") -> bool:
        """joins_entries over this knowledge base, with its combined entries and its embedder."""
        return joins_entries(self.texts, question, answer, self.members, self.near)

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
        if self.joins(question, answer):
            return False
        try:
            qc = self.candidates(question)
            if not qc:
                return False
            # shortcut: an entry that only shares facts with a candidate is not a source (it let "delete my account"
            # back a refund question); the judge-free path now uses this rule too, so it must stay this narrow
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
        if self.joins(question, answer):
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
    joined = sem.joins(question, answer) if sem is not None else joins_entries(lines, question, answer)
    if joined or time_verdict(question, answer):
        return False
    if sem is None:
        return backed(lines, question, answer)
    strict = sem.backed(question, answer)
    if strict is None:  # embedder failed: words decide
        return backed(lines, question, answer)
    # the same structural test with or without a judge: a judge only narrows it, never widens it
    if not (strict or backed(lines, question, answer) or sem.backed_loose(question, answer)):
        return False
    if judge is None:
        return True
    # the judge reads the entries the question may be about AND the entries the answer is closest to (its sources)
    ids = list(dict.fromkeys(sem.candidates(question) + sem.nearest(answer)))
    return judge.agrees(question, [sem.texts[i] for i in ids] or matched_lines(lines, question), answer)


def swarm_covered(sem: "Semantic | None", judge, question: str) -> bool:
    """Is there a KB fact a model could use? No embedder: assume yes (old behaviour). No entry close enough: no.
    With a judge: it reads the candidate entries and says whether they answer this exact question."""
    if sem is None:
        return True
    if sem.joins(question):
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
