"""Assistant: the whole skeleton API. One class, one method.

    bot = Assistant("my_app.toml", knowledge=facts, verify=check)
    a = bot.ask("where is the oat milk?")
    a["answer"], a["tier"], a["tokens"], a["dollars_saved"], a["cache_hit"], a["latency_ms"]

Under it runs packages/chimera-core, unchanged. SpeculativeCascadeRouter.generate() looks in the Supabase cache
(exact hash, then cosine 0.97) before any model is called. On a miss the tier pool tries the ladder in order
(self-hosted 30B, then the 763B) with its confidence gate. Each generate() emits the standard Telemetry
(tier_used, tokens_saved, acceptance_rate_alpha, latency_ms, dollars_saved).

Two hooks make an app:
- knowledge(prompt) -> str: facts the models need (a catalog, files). A `version` attribute, when present, keys
  the cache, so new facts never get old answers. The cache key is the question alone, never the facts.
- verify(answer) -> bool: the app's answer check (unit tests, a grounding rule). A failing answer is never cached
  and the question climbs one tier.
"""
from __future__ import annotations

import copy
import hashlib
import os
import pathlib
import threading
import time
import tomllib
from collections import Counter
from typing import Callable, Literal, TypedDict

from pydantic import BaseModel

from chimera_core.cache.semantic_cache import Lookup
from chimera_core.router import complexity_score
from chimera_core.tiers import TierCfg, TierPool

ROOT = pathlib.Path(__file__).resolve().parents[2]
Knowledge = Callable[[str], str]
Verify = Callable[[str], bool]


class Config(BaseModel):
    mode: Literal["demo", "live"] = "demo"  # demo: stub models + in-memory cache, no keys. live: real tiers + Supabase
    namespace: str = "app"                  # cache rows of one app never answer another app
    ladder: list[str] = ["gpu-small", "cloud-deepseek"]  # [[tiers]] names after the cache: 30B, then 763B
    chimera_config: str = ""                # live: path to chimera.toml ("" = $CHIMERA_CONFIG or the repo's)
    instructions: str = ""                  # put before the facts and the question in every model prompt
    max_tokens: int = 1024

    @classmethod
    def load(cls, src: "Config | dict | str | os.PathLike | None") -> "Config":
        if src is None or isinstance(src, Config):
            return src or cls()
        if isinstance(src, dict):
            return cls.model_validate(src)
        return cls.model_validate(tomllib.loads(pathlib.Path(src).read_text()))


class Answer(TypedDict):
    answer: str
    tier: str             # who answered: exact_cache, semantic_cache, gpu-small, cloud-deepseek, ...
    model: str
    tokens: int           # tokens the models used for this question, climbs included (0 on a cache hit)
    tokens_saved: int     # tokens that never reached the biggest tier (a cache hit: the whole call it avoided)
    dollars: float        # what it cost at list price
    dollars_saved: float  # what it did not cost against the biggest tier
    cache_hit: bool
    latency_ms: float
    verified: bool | None  # verify() result; None when the app has no verify hook
    tried: list[str]      # model tiers called, in order (a climb shows as two)
    steps: list[dict]     # one row per router call: tier, tokens, dollars, ms, verified


class Assistant:
    def __init__(self, config: "Config | dict | str | os.PathLike | None" = None, *, knowledge: Knowledge | None = None,
                 verify: Verify | None = None, demo_models: dict[str, Callable[[str], str]] | None = None,
                 router=None) -> None:
        """demo_models: tier name -> fn(prompt) -> answer, used in demo mode ("" = I don't know: climb).
        router: a ready SpeculativeCascadeRouter (tests); else built from the config."""
        self.cfg = Config.load(config)
        self.knowledge, self.verify = knowledge, verify
        tiers, pool_kw = _tiers(self.cfg), {}
        if self.cfg.mode == "demo":
            from .demo import demo_router, stub_factory
            router = router or demo_router()
            pool_kw = {"probe": lambda t: True, "backend_factory": stub_factory(demo_models or {})}
        elif router is None:
            router = _live_router(self.cfg, tiers)
        self.router = router
        full = TierPool(tiers, **pool_kw)  # cheapest first; climbing = dropping the tiers below
        self.ladder = [t.name for t in full.tiers]
        self._pools = [TierPool(full.tiers[i:], min_confidence=router.cfg.min_confidence,
                                max_tokens=self.cfg.max_tokens, **pool_kw) for i in range(len(full.tiers))]
        self._lock = threading.Lock()
        self.reset_stats()

    def ask(self, prompt: str, context: str = "", verify: Verify | None = None) -> Answer:
        """context: extra text for this question (e.g. file contents); it is part of the cache key."""
        check = verify or self.verify
        facts = self.knowledge(prompt) if self.knowledge else ""
        brief = "\n\n".join(x for x in (self.cfg.instructions, facts, context) if x)
        ns = self._namespace(facts, context)
        t0, steps, floor, skip_cache = time.perf_counter(), [], 0, False
        while True:
            seen: dict[str, bool] = {}

            def chk(text: str) -> bool:  # the router calls it on model answers; remember so tests run once
                seen[text] = bool(check(text))
                return seen[text]

            r = copy.copy(self.router)
            r.cfg = r.cfg.model_copy(update={"namespace": ns})
            r.pool = _WithBrief(self._pools[floor], brief)
            if skip_cache and r.shared is not None:
                r.shared = _SkipLookup(r.shared)
            try:
                res = r.generate(prompt, check=chk if check else None)
            except Exception:  # noqa: BLE001  all tiers failed: serve the last (failed) answer if there is one
                if not steps:
                    raise
                break
            if getattr(self.router.shared, "flush", None) and self.cfg.mode == "demo":
                self.router.shared.flush()  # demo: the in-memory row is written before the next question
            final = next(e for e in reversed(res.telemetry.events) if e["step"] == "final")
            ok = None if check is None else seen.get(res.text, None)
            if ok is None and check is not None:
                ok = bool(check(res.text))  # a cache hit: check it too (the files or tests may have changed)
            steps.append({"tier": final["tier"], "model": final["model"], "text": res.text, "cache": final["cache"],
                          "kind": _kind(res.telemetry.events), "tokens": final["tokens_in"] + final["tokens_out"],
                          "dollars": final["dollars"], "dollars_saved": final["dollars_saved"], "ms": final["ms"],
                          "tokens_saved": final["tokens_kept_off_big"],
                          "verified": ok, "tried": [e["tier"] for e in res.telemetry.events if e["step"] == "call"]})
            if ok is not False:
                break
            if final["cache"]:  # a cached answer failed the check: ask the tiers, from the bottom
                skip_cache = True
            elif final["tier"] in self.ladder and self.ladder.index(final["tier"]) + 1 < len(self.ladder):
                floor, skip_cache = self.ladder.index(final["tier"]) + 1, True  # climb one tier
            else:
                break  # the top tier failed the check too: serve it, marked verified=False
        last = steps[-1]
        saved_tokens, saved = last["tokens_saved"], last["dollars_saved"]
        top = self._pools[0].top
        if last["cache"] and top is not None:  # the call the cache avoided: facts + question in, the answer out
            t_in, t_out = (len(brief) + len(prompt)) // 4 + 1, len(last["text"]) // 4 + 1
            saved_tokens, saved = t_in + t_out, t_in / 1000 * top.cost_per_1k_in + t_out / 1000 * top.cost_per_1k_out
        a = Answer(answer=last["text"], tier=last["tier"], model=last["model"], tokens=sum(s["tokens"] for s in steps),
                   tokens_saved=saved_tokens, dollars=sum(s["dollars"] for s in steps), dollars_saved=round(saved, 6),
                   cache_hit=bool(last["cache"]), latency_ms=round((time.perf_counter() - t0) * 1000, 1),
                   verified=last["verified"], tried=[t for s in steps for t in s["tried"]],
                   steps=[{k: v for k, v in s.items() if k != "text"} for s in steps])
        self._count(a, last["kind"])
        return a

    # ---- totals for a stats strip --------------------------------------------------
    def reset_stats(self) -> None:
        with self._lock:
            self._stats = {"questions": 0, "cache_hits": 0, "exact": 0, "cosine": 0, "model_calls": 0, "climbs": 0,
                           "unverified": 0, "tokens": 0, "tokens_saved": 0, "dollars": 0.0, "dollars_saved": 0.0,
                           "by_tier": Counter()}

    def stats(self) -> dict:
        with self._lock:
            s = {**self._stats, "by_tier": dict(self._stats["by_tier"])}
        s["hit_rate"] = round(s["cache_hits"] / s["questions"], 4) if s["questions"] else 0.0
        return s

    def _count(self, a: Answer, kind: str | None) -> None:
        with self._lock:
            s = self._stats
            s["questions"] += 1
            s["cache_hits"] += a["cache_hit"]
            if a["cache_hit"]:
                s["exact" if kind == "exact" else "cosine"] += 1
            s["unverified"] += a["verified"] is False
            s["model_calls"] += len(a["tried"])
            s["climbs"] += max(len(a["tried"]) - 1, 0)  # tiers called above the first one (low confidence, empty, failed check)
            s["tokens"] += a["tokens"]
            s["tokens_saved"] += a["tokens_saved"]
            s["dollars"] += a["dollars"]
            s["dollars_saved"] += a["dollars_saved"]
            s["by_tier"][a["tier"]] += 1

    def _namespace(self, facts: str, context: str) -> str:
        version = getattr(self.knowledge, "version", None) or facts
        if not (version or context):
            return self.cfg.namespace
        key = hashlib.sha256(f"{version}\x00{context}".encode()).hexdigest()[:12]
        return f"{self.cfg.namespace}:{key}"


class _WithBrief:
    """The pool sees instructions + facts + question; the router (cache key, memory, telemetry) sees the question.
    Complexity is scored on the question, so long facts do not push an easy question to the top tier."""

    def __init__(self, pool: TierPool, brief: str) -> None:
        self.pool, self.brief = pool, brief

    def generate(self, prompt, complexity=None, on_event=None, context=""):
        full = f"{self.brief}\n\nQuestion: {prompt}" if self.brief else prompt
        score = complexity_score(prompt) if complexity is None else complexity
        return self.pool.generate(full, score, on_event, context)

    def __getattr__(self, name):
        return getattr(self.pool, name)


class _SkipLookup:
    """Retry after a failed check: the cache was already asked for this question. Writes still go through.
    shortcut: a cached answer that failed the check stays in the cache; mark it with report_false_hit once
    Lookup carries the row id."""

    def __init__(self, shared) -> None:
        self.shared = shared

    def lookup(self, prompt, namespace=""):
        return Lookup(None, None, None, 0.0, status="skipped")

    def __getattr__(self, name):
        return getattr(self.shared, name)


def _kind(events: list[dict]) -> str | None:
    return next((e.get("kind") for e in events if e["step"] == "cache_shared" and e.get("hit")), None)


def _tiers(cfg: Config) -> list[TierCfg]:
    """The ladder's [[tiers]] entries. Demo: chimera.example.toml (prices only, no URL is used).
    Live: chimera.toml (else the example), the same entries the product runs."""
    if cfg.mode == "live":
        from chimera_core.config import load_config
        all_tiers = load_config(cfg.chimera_config or None).tiers
    else:
        all_tiers = []
    if not all_tiers:
        ex = tomllib.loads((ROOT / "chimera.example.toml").read_text()).get("tiers", [])
        all_tiers = [TierCfg.model_validate(t) for t in ex]
    by_name = {t.name: t for t in all_tiers}
    missing = [n for n in cfg.ladder if n not in by_name]
    if missing:
        raise KeyError(f"ladder names no [[tiers]] entry: {missing}")
    return [by_name[n].model_copy(update={"enabled": True}) for n in cfg.ladder]


def _live_router(cfg: Config, tiers: list[TierCfg]):
    """The product router: Supabase cache (CHIMERA_DB_URL), N+1 memory, telemetry JSONL, keys from .env."""
    from chimera_core.config import build_router, load_config
    cc = load_config(cfg.chimera_config or None)
    return build_router(cc.model_copy(update={"use_pool": True, "tiers": tiers}))
