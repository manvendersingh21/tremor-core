"""Swarm: free modules first, then the Assistant (cache, then the Crusoe tiers, cheapest first).

    bot = Swarm(make_assistant(), free=[("rules", rules.match), ("kb_lookup", lookup.match)],
                check=kb.checked, fallback="I don't know. A support agent will reply by email.")
    bot.ask("how do i reset my password")   # kb_lookup: $0, no model, no cache write, one telemetry row
    bot.ask("my parcel is two weeks late")  # Assistant: cache, then crusoe-small, cloud-top, cloud-deepseek

A wrapper like RulesFirst (skeleton/core/rules.py); Assistant.ask is not changed. Order:
1. Free modules (no model, no network). They may run before the cache because they cost nothing and never write to it.
2. Assistant.ask: the shared cache first, then the tiers cheapest first. The first answer that passes the app's check
   is served and cached; one that fails is never served and never cached (the router caches only checked answers).
3. When every tier fails the check, `fallback` is served instead of the failed answer (verified=False).
Free answers skip the router, so each one logs its own Telemetry row (tier_used "local", tier_name = the module).
"""
from __future__ import annotations

import time
from collections import Counter
from typing import Callable

from chimera_core.inference.telemetry import Telemetry

SWARM_LADDER = ["crusoe-small", "cloud-top", "cloud-deepseek"]  # Nemotron Lightning 30B, gpt-oss-120b, DeepSeek 763B
Free = tuple[str, Callable[[str], "str | None"]]


def real_embedder(bot, given=None):
    """The embedder for meaning-based matching: the one given (tests), else the router's when it is a real model.
    Demo mode's word-bag HashEmbedder knows no synonyms, so it is not used: the word-overlap path decides."""
    from .demo import HashEmbedder
    emb = given or getattr(getattr(bot, "router", None), "embedder", None)
    return None if emb is None or isinstance(emb, HashEmbedder) else emb


COVER_PROMPT = """Knowledge base entries:
{entries}

Customer question: {q}

Can a correct reply to this question be given from these entries alone? A reply that says no, or gives the nearest
fact the entries state ("phone support is Monday to Friday", "we ship to the US and Canada only"), counts as YES.
Reply NO when the question is about a different thing than the entries: another product, device, service or action
(a router is not a password, a flight is not an order, pausing is not cancelling). Reply with one word: YES or NO."""
CHECK_PROMPT = """Knowledge base entries:
{entries}

Customer question: {q}
Proposed answer: {a}

Reply YES when every claim in the proposed answer is stated by one of the entries (wording may differ) and the answer
addresses what the question asks; a partial answer or a "no, but we offer X" built from the entries is fine.
Reply NO when the answer is about another product, device, service or action than the question, or when it makes a
claim no single entry states, such as joining "express shipping exists" and "we ship to Canada" into "express
shipping goes to Canada". Reply with one word: YES or NO."""


class Judge:
    """A cheap yes/no model check against the KB entries that match a question (live only; gpt-oss-120b).

    Every call goes through its own Assistant (cache first, then the tier, telemetry), never straight to a backend.
    It only narrows what the structural check allowed: a structural NO is never turned into a YES.
    shortcut: a judge is a model and can be wrong; the wrong-entry matrices in skeleton/RESULTS.md measure it."""

    def __init__(self, bot) -> None:
        self.bot = bot

    def _yes(self, prompt: str) -> bool:
        return self.bot.ask(prompt)["answer"].strip().upper().startswith("YES")

    def covers(self, question: str, entries: list[str]) -> bool:
        return bool(entries) and self._yes(COVER_PROMPT.format(entries="\n".join(entries), q=question))

    def agrees(self, question: str, entries: list[str], answer: str) -> bool:
        return bool(entries) and self._yes(CHECK_PROMPT.format(entries="\n".join(entries), q=question, a=answer))


def make_judge(cfg: dict, namespace: str, tier: str = "cloud-top") -> "Judge | None":
    """Live: a Judge on `tier`. Demo: None (the structural check decides alone; CI never calls a model)."""
    if cfg.get("mode") != "live":
        return None
    from . import Assistant
    return Judge(Assistant({**cfg, "namespace": f"{namespace}:judge", "ladder": [tier], "instructions": "",
                            "max_tokens": 400}))


def need_embedder(bot, given=None):
    """Live: the embedder must be real. A live swarm without one would fall back to word overlap and behave unlike
    other live harnesses (no DSN = no cache embedder), so it builds all-MiniLM-L6-v2 itself or fails loudly."""
    emb = real_embedder(bot, given)
    if emb is None and bot.cfg.mode == "live":
        try:
            from chimera_core.cache.semantic_cache import OnnxMiniLMEmbedder
            emb = OnnxMiniLMEmbedder()
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"live swarm needs the embedder (sentence-transformers): {type(e).__name__}") from e
    return emb


class Swarm:
    def __init__(self, bot, free: list[Free] | None = None, check: Callable[[str, str], bool] | None = None,
                 fallback: str | None = None, covered: Callable[[str], bool] | None = None) -> None:
        """check(question, answer) -> bool is the app's answer check; a per-call verify= (the coder's tests) wins.
        covered(question) -> bool: does the knowledge base hold a fact for it? Asked after a cache miss and before any
        tier; False serves the fallback with no tier call, because a bigger model cannot pass the check either."""
        self.bot, self.free, self.check, self.fallback, self.covered = bot, list(free or []), check, fallback, covered
        self.reset_stats()

    def ask(self, prompt: str, context: str = "", verify=None):
        t0 = time.perf_counter()
        if not context:  # a question with attached text (files) is never answered from the knowledge base
            for name, fn in self.free:
                text = fn(prompt)
                if text:
                    return self._free(name, prompt, text, t0)
            if self.covered is not None and self.fallback is not None and not self._cached(prompt):
                if not self.covered(prompt):  # after the cache lookup (a miss); no tier is called
                    return self._free("no_fact", prompt, self.fallback, t0, verified=False)
        chk = verify or ((lambda ans: self.check(prompt, ans)) if self.check else None)
        a = self.bot.ask(prompt, context=context, verify=chk)
        if a["verified"] is False and self.fallback is not None:
            a = {**a, "answer": self.fallback}  # the failed answer is not served
        return a

    def _cached(self, prompt: str) -> bool:
        """Read-only cache lookup in the namespace Assistant.ask uses. True on a hit (exact or cosine)."""
        shared = getattr(self.bot.router, "shared", None)
        if shared is None:
            return False
        facts = self.bot.knowledge(prompt) if self.bot.knowledge else ""
        try:
            return shared.lookup(prompt, self.bot._namespace(facts, "")).hit is not None
        except Exception:  # noqa: BLE001  cache down: a miss
            return False

    def _free(self, name: str, prompt: str, text: str, t0: float, verified: bool | None = None):
        ms = round((time.perf_counter() - t0) * 1000, 3)
        tin = (len(getattr(self.bot, "cfg").instructions) + len(self.bot.knowledge(prompt) if self.bot.knowledge else "")
               + len(prompt)) // 4 + 1  # the prompt a model call would have sent
        tout = len(text) // 4 + 1
        top = self.bot._pools[0].top
        saved = (tin * top.cost_per_1k_in + tout * top.cost_per_1k_out) / 1000 if top else 0.0
        self.bot.router.tracker.emit(Telemetry(
            tier_used="local", tier_name=name, tokens_saved=tin + tout, acceptance_rate_alpha=None, latency_ms=ms,
            dollars_saved=saved, dollars_spent=0.0, tokens_in=0, tokens_out=0, ts=time.time(),
            events=[{"step": "final", "tier": name, "model": name, "tokens_in": 0, "tokens_out": 0, "ms": ms,
                     "dollars": 0.0, "dollars_saved": round(saved, 6), "tokens_kept_off_big": tin + tout, "cache": None}]))
        with self.bot._lock:
            self._free_stats["by"][name] += 1
            self._free_stats["tokens_saved"] += tin + tout
            self._free_stats["dollars_saved"] += saved
        return {"answer": text, "tier": name, "model": name, "tokens": 0, "tokens_saved": tin + tout, "dollars": 0.0,
                "dollars_saved": round(saved, 6), "cache_hit": False, "latency_ms": ms, "verified": verified, "tried": [],
                "steps": [{"tier": name, "model": name, "cache": False, "tokens": 0, "dollars": 0.0,
                           "dollars_saved": round(saved, 6), "ms": ms, "tokens_saved": tin + tout, "verified": None,
                           "tried": []}]}

    def reset_stats(self) -> None:
        self.bot.reset_stats()
        self._free_stats = {"by": Counter(), "tokens_saved": 0, "dollars_saved": 0.0}

    def stats(self) -> dict:
        s, f = self.bot.stats(), self._free_stats
        n = sum(f["by"].values())
        s["questions"] += n
        s["free_answers"] = n
        s["tokens_saved"] += f["tokens_saved"]
        s["dollars_saved"] += f["dollars_saved"]
        s["by_tier"] = {**s["by_tier"], **f["by"]}
        s["hit_rate"] = round(s["cache_hits"] / s["questions"], 4) if s["questions"] else 0.0
        return s

    def __getattr__(self, name):
        return getattr(self.bot, name)
