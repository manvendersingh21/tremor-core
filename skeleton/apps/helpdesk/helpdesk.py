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


def make_assistant(live: bool = False, kb: KnowledgeBase | None = None, no_gpu: bool = False) -> Assistant:
    import tomllib
    kb = kb or KnowledgeBase()
    cfg = {**tomllib.loads(CONFIG.read_text()), **({"mode": "live"} if live else {})}
    if no_gpu:
        cfg["ladder"] = ["cloud-deepseek"]
    return Assistant(cfg, knowledge=kb, verify=kb.grounded, demo_models=DEMO_MODELS)


def seed(bot: Assistant, questions: list[str] | None = None) -> dict:
    """Ask the common questions once so customers get cache hits. Returns the warm-up totals; stats restart at 0."""
    for q in questions or json.loads(QUESTIONS.read_text())["seed"]:
        bot.ask(q)
    done = bot.stats()
    bot.reset_stats()
    return done
