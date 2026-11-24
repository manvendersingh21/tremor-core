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


class Swarm:
    def __init__(self, bot, free: list[Free] | None = None, check: Callable[[str, str], bool] | None = None,
                 fallback: str | None = None) -> None:
        """check(question, answer) -> bool is the app's answer check; a per-call verify= (the coder's tests) wins."""
        self.bot, self.free, self.check, self.fallback = bot, list(free or []), check, fallback
        self.reset_stats()

    def ask(self, prompt: str, context: str = "", verify=None):
        t0 = time.perf_counter()
        if not context:  # a question with attached text (files) is never answered from the knowledge base
            for name, fn in self.free:
                text = fn(prompt)
                if text:
                    return self._free(name, prompt, text, t0)
        chk = verify or ((lambda ans: self.check(prompt, ans)) if self.check else None)
        a = self.bot.ask(prompt, context=context, verify=chk)
        if a["verified"] is False and self.fallback is not None:
            a = {**a, "answer": self.fallback}  # the failed answer is not served
        return a

    def _free(self, name: str, prompt: str, text: str, t0: float):
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
                "dollars_saved": round(saved, 6), "cache_hit": False, "latency_ms": ms, "verified": None, "tried": [],
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
