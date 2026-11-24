"""Help-desk assistant built only on the skeleton API.

knowledge = KnowledgeBase (kb.json as short lines; its version is the file hash, so an edited answer never
meets an old cached one). verify = KnowledgeBase.grounded: an answer may only quote numbers (days, prices, phone
numbers, hours) that are in the knowledge base, and "I don't know" climbs to the 763B.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re

from skeleton.core import Assistant
from skeleton.core.demo import words
from skeleton.core.kblookup import KBLookup, Semantic, backed

HERE = pathlib.Path(__file__).resolve().parent
CONFIG, KB, QUESTIONS = HERE / "helpdesk.toml", HERE / "kb.json", HERE / "questions.json"
UNSURE = re.compile(r"\b(i don'?t know|i do not know|not sure|no information)\b", re.I)
NUM = re.compile(r"\d[\d,.:\-]*\d|\d")
QWORDS = {"where", "when", "what", "how", "much", "which", "who", "why", "long"}


class KnowledgeBase:
    """shortcut: the whole knowledge base goes in every model prompt (about 1,100 tokens); retrieve only the
    matching entries once it passes ~100 entries."""

    def __init__(self, path: pathlib.Path = KB) -> None:
        raw = path.read_text()
        self.data = json.loads(raw)
        self.version = hashlib.sha256(raw.encode()).hexdigest()[:12]
        self.text = "\n".join(self.lines())
        self.numbers = set(NUM.findall(self.text))
        self.embedder, self._sem = None, None

    def attach(self, embedder) -> "KnowledgeBase":
        """Use meaning as well as shared words (the cache's embedder). None: word overlap only."""
        self.embedder, self._sem = embedder, None
        return self

    def semantic(self) -> "Semantic | None":
        if self.embedder is None:
            return None
        if self._sem is None:
            d = self.data
            ents = [(f"Hours, {k}: {v}.",) * 2 for k, v in d["hours"].items()] + [(c, c) for c in d["contact"]]
            ents += [(e["q"], f"{e['q']} {e['a']}") for e in d["faq"]] + [(f"Policy. {p}",) * 2 for p in d["policies"]]
            # structured facts as whole entries, built from the data: all hours together, all policies together
            hours = "Support hours. " + " ".join(f"Hours, {k}: {v}." for k, v in d["hours"].items())
            ents += [("What are your hours? Are you open on a weekday, Saturday or Sunday?", hours),
                     ("What are your policies? Returns, refunds, subscriptions, privacy.", "Policies. " + " ".join(d["policies"]))]
            texts = [t for _, t in ents]
            n_hours, n_pol = len(d["hours"]), len(d["policies"])
            hours_at = list(range(n_hours))  # the hours lines come first
            pol_at = [texts.index(f"Policy. {p}") for p in d["policies"]]
            self._sem = Semantic(self.embedder, [k for k, _ in ents], texts,
                                 members={texts.index(hours): hours_at, len(texts) - 1: pol_at})
        return self._sem

    def lines(self) -> list[str]:
        d = self.data
        out = [f"Knowledge base for {d['company']} support."]
        out += [f"Hours, {k}: {v}." for k, v in d["hours"].items()]
        out += d["contact"]
        out += [f"Q: {e['q']} A: {e['a']}" for e in d["faq"]]
        return out + [f"Policy. {p}" for p in d["policies"]]

    def __call__(self, question: str) -> str:
        return self.text

    def grounded(self, answer: str) -> bool:
        """Non-empty, sure, and every number in it is in the knowledge base."""
        if not answer.strip() or UNSURE.search(answer):
            return False
        return all(n in self.numbers for n in NUM.findall(re.sub(r"(?m)^\s*\d+[.)]\s+", "", answer)))


    def checked(self, question: str, answer: str) -> bool:
        """The swarm's check: grounded (numbers) AND backed by the entries that match the question (word overlap, no
        model). An answer with no numbers that talks about another entry fails. shortcut: overlap knows no synonyms;
        a good paraphrase of the right entry can fail at 0.6 and climbs, the cost is a call, never a wrong answer."""
        if not self.grounded(answer):
            return False
        sem = self.semantic()
        return backed(self.lines(), question, answer) or bool(sem and sem.backed(question, answer))

    def lookup(self) -> KBLookup:
        """$0 FAQ lookup: answers straight from an entry when the question and the entry's question match strongly."""
        from chimera_core.cache.guard import consistent  # numbers, negation, names must agree with the entry's question
        faq = [(e["q"], e["a"]) for e in self.data["faq"]]
        sem = Semantic(self.embedder, [q for q, _ in faq]) if self.embedder is not None else None
        return KBLookup(faq, semantic=sem, guard=consistent)


FALLBACK = "I don't know. A support agent will reply by email."


def _match(prompt: str, need: float) -> str:
    """Demo model: the knowledge-base line that covers at least `need` of the ticket's words, else ""."""
    kb, _, q = prompt.rpartition("Question:")
    kb = kb[kb.find("Knowledge base for"):]
    want = set(words(q)) - QWORDS
    if not want:
        return ""
    scored = []
    for x in (x for x in kb.splitlines() if x.strip()):
        faq = x.startswith("Q: ")
        key = x.split(" A: ", 1)[0] if faq else x  # an FAQ entry is matched on its question
        scored.append((len(want & set(words(key))), faq, -len(key), x))
    if not scored:
        return ""
    best = max(scored)
    if best[0] < need * len(want):
        return ""
    if best[1]:
        return best[3].split(" A: ", 1)[1]
    tied = [s[3].removeprefix("Policy. ") for s in sorted(scored, reverse=True) if s[:2] == best[:2]]
    return " ".join(tied)[:600]  # tied facts (the hours lines)


DEMO_MODELS = {"gpu-small": lambda p: _match(p, 0.6),  # the 30B stand-in: a close match
               "cloud-deepseek": lambda p: _match(p, 0.4) or "I don't know: a support agent will reply by email."}


SWARM_DEMO_MODELS = {"crusoe-small": DEMO_MODELS["gpu-small"], "cloud-top": lambda p: _match(p, 0.5),
                     "cloud-deepseek": DEMO_MODELS["cloud-deepseek"]}


def make_assistant(live: bool = False, kb: KnowledgeBase | None = None, no_gpu: bool = False,
                   rules: bool = False, swarm: bool = False, namespace: str | None = None, embedder=None):
    """swarm=True: rules and KB lookup at $0, then the cache, then crusoe-small, cloud-top, cloud-deepseek (no GPU)."""
    import tomllib
    kb = kb or KnowledgeBase()
    cfg = {**tomllib.loads(CONFIG.read_text()), **({"mode": "live"} if live else {}),
           **({"namespace": namespace} if namespace else {})}
    if no_gpu:
        cfg["ladder"] = ["cloud-deepseek"]
    if swarm:
        from skeleton.core.rules import Rules
        from skeleton.core.swarm import SWARM_LADDER, Swarm, real_embedder
        bot = Assistant({**cfg, "ladder": SWARM_LADDER}, knowledge=kb, verify=kb.grounded, demo_models=SWARM_DEMO_MODELS)
        kb.attach(real_embedder(bot, embedder))  # live: all-MiniLM-L6-v2 from the cache; demo/CI: word overlap
        return Swarm(bot, free=[("rules", Rules.for_faq(kb.data).match), ("kb_lookup", kb.lookup().match)],
                     check=kb.checked, fallback=FALLBACK)
    bot = Assistant(cfg, knowledge=kb, verify=kb.grounded, demo_models=DEMO_MODELS)
    if rules:  # regex fast path before the cache (skeleton/core/rules.py); off by default
        from skeleton.core.rules import Rules, RulesFirst
        return RulesFirst(bot, Rules.for_faq(kb.data))
    return bot


def seed(bot: Assistant, questions: list[str] | None = None) -> dict:
    """Ask the common questions once so customers get cache hits. Returns the warm-up totals; stats restart at 0."""
    for q in questions or json.loads(QUESTIONS.read_text())["seed"]:
        bot.ask(q)
    done = bot.stats()
    bot.reset_stats()
    return done
