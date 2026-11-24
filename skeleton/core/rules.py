"""Rules first: a regex fast path in front of the cache and the models (an idea taken from huggingface/pybot).

    bot = RulesFirst(make_assistant(), Rules.for_faq(kb.data))
    bot.ask("hi!")                  # tier "rules", 0 tokens, no cache, no model
    bot.ask("what are your hours")  # tier "rules": the knowledge base's own hours lines
    bot.ask("my order is late")     # no rule matches: the normal cache -> models path

Only two kinds of rule exist: small talk (greeting, thanks, goodbye) and a few help-desk intents whose answer is
copied from the knowledge base, so a rule can never say something the knowledge base does not. A rule matches
only a short message that is nothing else. Anything with extra words falls through to the cache and the models.
shortcut: the intents are hand-written for the demo knowledge base; a real deployment writes its own list
(docs/research/pybot_compare.md says which rules paid off). Off unless the app is built with rules=True.
"""
from __future__ import annotations

import re
import time
from typing import Callable

SMALL_TALK = [
    (re.compile(r"^(hi|hello|hey|hiya|good (morning|afternoon|evening))( there)?( team)?$"),
     "Hello! Ask me about your order, a refund, shipping or your account."),
    (re.compile(r"^(thanks|thank you|thanks a lot|thank you so much|thx|cheers)( (a lot|so much))?$"),
     "You're welcome! Anything else I can help with?"),
    (re.compile(r"^(bye|goodbye|see you|see ya|that is all|that's all|nothing else)$"),
     "Goodbye! Write again any time."),
]
_FILLER = re.compile(r"^(please|pls|can you|could you|tell me|i want to know|i need to know)\s+")


def norm(text: str) -> str:
    t = re.sub(r"[^\w\s']", " ", text.lower())
    t = " ".join(t.split())
    while m := _FILLER.match(t):
        t = t[m.end():]
    return t


# Small talk with a short tail ("thanks, that helped!", "great, that worked, bye"): every word is a social word.
# A message with any other word ("hi, my order arrived broken") is a real question and goes on.
_THANKS = {"thanks", "thank", "thx", "cheers", "appreciate", "appreciated", "helped", "worked", "works", "solved",
           "fixed", "sorted", "perfect", "great", "awesome", "brilliant", "excellent", "wonderful", "lovely", "super", "nice"}
_BYE = {"bye", "goodbye", "later", "cya", "ciao"}
_HELLO = {"hello", "hi", "hey", "hiya", "morning", "afternoon", "evening"}
_GLUE = {"that", "it", "this", "you", "your", "youre", "for", "the", "help", "all", "again", "team", "there", "guys",
         "everyone", "now", "so", "much", "very", "a", "lot", "bunch", "really", "good", "best", "ok", "okay", "got", "i",
         "will", "be", "back", "no", "more", "questions", "see", "have", "day", "take", "care", "was", "is", "thats",
         "what", "needed", "exactly", "and", "to", "of", "in", "one", "quick", "answer", "answers", "support", "assistance",
         # greetings that are questions only in form: "hey, how are you?", "hi, is anyone there?"
         "how", "are", "doing", "anyone", "someone", "anybody", "here", "been", "youve", "nice", "great", "today"}
_SOCIAL = _THANKS | _BYE | _HELLO | _GLUE


def _social(t: str) -> str | None:
    """The small-talk reply when `t` (normalised) is only social words, at most 8, else None."""
    toks = t.replace("'", "").split()
    if not 0 < len(toks) <= 8 or not set(toks) <= _SOCIAL or "what" in toks[:1] or "i" in toks[:1]:
        return None
    key = set(toks)
    for words, reply in ((_THANKS, SMALL_TALK[1][1]), (_BYE, SMALL_TALK[2][1]), (_HELLO, SMALL_TALK[0][1])):
        if key & words:
            return reply
    return None


class Rules:
    def __init__(self, table: list[tuple[re.Pattern, Callable[[], str] | str]]) -> None:
        self.table = table

    @classmethod
    def for_faq(cls, kb: dict) -> "Rules":
        """kb: the help-desk kb.json dict. Intent answers are read from it on every hit."""
        faq = {e["q"]: e["a"] for e in kb["faq"]}

        def hours() -> str:
            return " ".join(f"Hours, {k}: {v}." for k, v in kb["hours"].items())

        def phone() -> str:
            return " ".join(kb["contact"])

        table: list[tuple[re.Pattern, Callable[[], str] | str]] = list(SMALL_TALK)
        table += [
            (re.compile(r"^(what are your |what is your |what're your )?(opening |support |business )?hours$|"
                        r"^what are your (opening |support |business )?hours( of operation)?$|"
                        r"^when are you open$|^what time do you (open|close)$"), hours),
            (re.compile(r"^(what is your |what's your |your )?(phone|telephone|contact) (number|details)$|"
                        r"^(how do i |how can i )?(contact|call|reach) (you|support|a person|someone)$"), phone),
            (re.compile(r"^(how (do|can) i )?(reset|change|recover) (my |the )?password$|"
                        r"^i forgot my password( how do i reset it)?$|^forgot (my )?password$"),
             faq["How do I reset my password?"]),
            (re.compile(r"^(how (do|can) i )?track (my |an )?order$|^where is my order$|^where's my order$"),
             faq["Where is my order?"]),
        ]
        return cls(table)

    def match(self, text: str) -> str | None:
        t = norm(text)
        if not t or len(t) > 60:
            return None
        for pat, ans in self.table:
            if pat.match(t):
                return ans() if callable(ans) else ans
        return _social(t)


class RulesFirst:
    """Wraps an Assistant: same ask(), same Answer dict; a rule hit skips the cache and the models."""

    def __init__(self, bot, rules: Rules) -> None:
        self.bot, self.rules, self.rule_hits = bot, rules, 0

    def ask(self, prompt: str, context: str = "", verify=None):
        t0 = time.perf_counter()
        text = None if context else self.rules.match(prompt)
        if text is None:
            return self.bot.ask(prompt, context=context, verify=verify)
        self.rule_hits += 1
        ms = round((time.perf_counter() - t0) * 1000, 3)
        # dollars_saved is 0 on purpose: a rule hit is not measured against any model call.
        return {"answer": text, "tier": "rules", "model": "rules", "tokens": 0, "tokens_saved": 0, "dollars": 0.0,
                "dollars_saved": 0.0, "cache_hit": False, "latency_ms": ms, "verified": None, "tried": [],
                "steps": [{"tier": "rules", "model": "rules", "cache": False, "tokens": 0, "dollars": 0.0,
                           "dollars_saved": 0.0, "ms": ms, "tokens_saved": 0, "verified": None, "tried": []}]}

    def __getattr__(self, name):
        return getattr(self.bot, name)

    def stats(self) -> dict:
        return {**self.bot.stats(), "rule_hits": self.rule_hits}
