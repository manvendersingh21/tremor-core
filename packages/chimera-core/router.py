"""SpeculativeCascadeRouter: every LLM call goes through generate().

Order: exact cache -> semantic cache -> (heavy task? hand off) -> local draft ->
confident? return : escalate (verify if same-family tokenizer, else handoff).
"""
from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Callable, Protocol

from pydantic import BaseModel, ConfigDict

from .cache.exact_cache import ExactCache
from .cache.semantic_cache import SemanticCache
from .inference.cloud_verifier import CloudVerifier
from .inference.handoff import build_brief, cloud_prompt
from .inference.local_draft import DraftBackend, DraftResult, chatml, should_escalate
from .inference.telemetry import Telemetry, TelemetryTracker

if TYPE_CHECKING:
    from .tiers import TierPool

log = logging.getLogger("chimera.router")
OnEvent = Callable[[str, dict], None]


class Memory(Protocol):
    """N+1 memory: solved problems from the big model, retrieved as few-shot context for the 30B."""

    def retrieve(self, prompt: str):  # -> str, or an object with .render() -> str (memory.MemoryContext)
        ...

    def store(self, prompt: str, answer: str, model: str, tier: str, verified: bool, tests: bool | None,
              tokens: dict | None = None): ...


class NoMemory:
    """Used when packages/chimera-core/memory/ is not configured: retrieves nothing, stores nothing."""

    def retrieve(self, prompt: str) -> str:
        return ""

    def store(self, prompt, answer, model, tier, verified, tests, tokens=None):
        return None


class Events:
    """Collects the step events of one call and forwards each to the caller's on_event(step, data)."""

    def __init__(self, cb: OnEvent | None = None, tags: dict | None = None) -> None:
        self.cb, self.log, self.tags = cb, [], tags or {}  # tags: task, conversation_id, prompt_preview

    def __call__(self, step: str, data: dict) -> None:
        self.log.append({"step": step, **data})
        if self.cb is not None:
            try:
                self.cb(step, data)
            except Exception as e:  # noqa: BLE001  a broken listener must never break the call
                log.warning("on_event failed: %s", type(e).__name__)


def _tags(prompt: str, task: str | None, conversation_id: str | None) -> dict:
    from .memory.safety import scrub
    return {"task": task, "conversation_id": conversation_id, "prompt_preview": scrub(prompt[:200])[:80]}


HEAVY_HINTS = re.compile(
    r"\b(refactor|architecture|migrate|redesign|implement|debug|optimi[sz]e|concurrency|"
    r"across (the )?(repo|codebase)|multi-?file|design)\b",
    re.I,
)


def complexity_score(prompt: str) -> float:
    """0..1 heuristic. Long prompts, code fences and heavy keywords push it up."""
    score = min(len(prompt) / 4000, 0.5)
    score += 0.2 * min(prompt.count("```") // 2, 2)
    score += 0.15 * min(len(HEAVY_HINTS.findall(prompt)), 3)
    return min(score, 1.0)


class Tokenizer(Protocol):
    def encode(self, text: str) -> list[int]: ...
    def decode(self, ids: list[int]) -> str: ...


class RouterConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    min_confidence: float = 0.95
    min_cache_confidence: float = 0.95  # answers below this are served but not cached
    heavy_threshold: float = 0.6
    max_local_tokens: int = 512
    max_cloud_tokens: int = 2048
    cloud_dollars_per_1k_tokens: float = 0.002
    namespace: str = ""


class GenerateResult(BaseModel):
    text: str
    telemetry: Telemetry


class SpeculativeCascadeRouter:
    def __init__(
        self,
        local: DraftBackend,
        cloud: CloudVerifier | None = None,
        exact: ExactCache | None = None,
        semantic: SemanticCache | None = None,
        tracker: TelemetryTracker | None = None,
        config: RouterConfig | None = None,
        tokenizer: Tokenizer | None = None,
        pool: "TierPool | None" = None,
        shared=None,
        embedder=None,
        memory: Memory | None = None,
    ) -> None:
        self.memory = memory or NoMemory()
        self.local, self.cloud = local, cloud
        # shortcut: with no shared cache and no exact cache given, keep the old in-memory default (tests and
        # offline use). Production (config.build_router, backend=supabase) passes a shared cache and no local one.
        # exact=False: no exact cache at all (production with no shared cache configured).
        self.exact = None if exact is False else exact if exact is not None or shared is not None else ExactCache()
        self.semantic = semantic
        self.tracker = tracker or TelemetryTracker()
        self.cfg = config or RouterConfig()
        self.tokenizer = tokenizer
        self.shared = shared      # shared PgVectorCache; looked up in parallel with the local caches
        self.embedder = embedder  # same object the caches use; lets generate() time the embed step
        self.pool = pool  # config flag `use_pool`: route through the tier pool instead of local/cloud

    # ---- public API -------------------------------------------------------
    def generate(self, prompt: str, context: str = "", on_event: OnEvent | None = None,
                 check: Callable[[str], bool] | None = None, task: str | None = None,
                 conversation_id: str | None = None) -> GenerateResult:
        """on_event(step, data) is optional. Steps: embed, cache_shared, memory, decide, call, draft, final.

        check(answer) -> bool (e.g. unit tests): a failing answer is served but never cached or stored as memory.
        """
        t0 = time.perf_counter()
        ev = Events(on_event, _tags(prompt, task, conversation_id))

        hit = self._lookup(prompt, ev)
        if hit is not None:
            text, tier, source = hit
            # a band hit asked the self-hosted 30B yes/no first: its tokens are counted (owned GPU, $0)
            chk = next((e.get("check") for e in reversed(ev.log) if e["step"] == "cache_shared"), None) or {}
            return self._done(text, tier, t0, tokens_saved=max(len(prompt) // 4, 1) + len(text) // 4, ev=ev,
                              cache_source=source, tokens_in=int(chk.get("tokens_in", 0)),
                              tokens_out=int(chk.get("tokens_out", 0)))  # dollars_saved: priced at the big tier

        if self.pool is not None:
            return self._pooled(prompt, t0, ev, check)

        heavy = complexity_score(prompt) >= self.cfg.heavy_threshold
        if heavy and self.cloud is not None:
            return self._handoff(prompt, context, t0, draft=None, ev=ev)

        draft = self.local.complete(prompt, self.cfg.max_local_tokens)
        ev("draft", {"tier": "local", "model": getattr(self.local, "model", "local"),
                     "confidence": round(draft.mean_confidence, 4), "gate": self.cfg.min_confidence})
        if not should_escalate(draft, self.cfg.min_confidence) or self.cloud is None:
            return self._store_local(prompt, draft, t0, ev)

        if self.tokenizer is not None and draft.token_ids and all(i is not None for i in draft.token_ids):
            return self._verify(prompt, draft, t0, ev)
        return self._handoff(prompt, context, t0, draft=draft, ev=ev)

    # ---- cache stack: exact, then local semantic, with the shared cache looked up in parallel -------
    def _lookup(self, prompt: str, ev: Events) -> tuple[str, str, str] | None:
        """(text, tier, source) from the first cache that answers, else None. Emits embed, cache_local, cache_shared."""
        ns = self.cfg.namespace
        if self.embedder is not None:
            t = time.perf_counter()
            vec = self.embedder.embed(prompt)
            ev("embed", {"ms": round((time.perf_counter() - t) * 1000, 2), "dim": len(vec)})
        if self.exact is not None or self.semantic is not None:  # local caches: offline tests only
            t = time.perf_counter()
            local: tuple[str, str, str] | None = None
            info: dict = {"kind": None, "score": None, "guard": None}
            exact = self.exact.get(prompt, ns) if self.exact is not None else None
            if exact is not None:
                local, info = (exact, "exact_cache", "exact"), {"kind": "exact", "score": 1.0, "guard": None}
            elif self.semantic is not None:
                lk = self.semantic.lookup(prompt, ns)
                if lk.hit is not None:
                    local = (lk.hit[0], "semantic_cache", "local")
                info = {"kind": "semantic" if lk.hit else None, "guard": lk.guard,
                        "score": None if lk.best_sim is None else round(lk.best_sim, 4)}
            ev("cache_local", {"hit": local is not None, **info, "threshold": getattr(self.semantic, "threshold", None),
                               "ms": round((time.perf_counter() - t) * 1000, 2)})
            if local is not None:
                return local
        if self.shared is None:
            return None
        try:
            lk = self.shared.lookup(prompt, ns)  # runs under its own budget; never raises past it
        except Exception as e:  # noqa: BLE001  the cache must never fail a call
            ev("cache_shared", {"hit": False, "status": "unavailable", "threshold": self.shared.threshold,
                                "error": type(e).__name__})
            return None
        kind = None if lk.hit is None else getattr(lk, "kind", None) or ("exact" if lk.hit[1] >= 1.0 else "semantic")
        data = {"hit": lk.hit is not None, "status": lk.status, "threshold": self.shared.threshold, "kind": kind,
                "score": None if lk.best_sim is None else round(lk.best_sim, 4), "guard": lk.guard, "ms": round(lk.ms, 2)}
        if getattr(self.shared, "band_low", 0):
            data["band_low"] = self.shared.band_low
        for k in ("via", "check"):  # paraphrase fields (cache/band.py); absent when unused
            if getattr(lk, k, None):
                data[k] = getattr(lk, k)
        ev("cache_shared", data)
        if lk.hit is None:
            return None
        return lk.hit[0], ("exact_cache" if kind == "exact" else "semantic_cache"), "shared"

    # ---- paths --------------------------------------------------------------
    def _price_saved(self, tin: int, tout: int) -> float:
        top = self.pool.top if self.pool is not None else None
        if top is None:
            return (tin + tout) / 1000 * self.cfg.cloud_dollars_per_1k_tokens
        return tin / 1000 * top.cost_per_1k_in + tout / 1000 * top.cost_per_1k_out

    def _pooled(self, prompt: str, t0: float, ev: Events, check: Callable[[str], bool] | None = None) -> GenerateResult:
        tm = time.perf_counter()
        try:
            got = self.memory.retrieve(prompt)
            ctx = (got if isinstance(got, str) else got.render()) if got else ""
        except Exception as e:  # noqa: BLE001  memory is optional; it must never fail a call
            ctx = ""
            log.warning("memory.retrieve failed: %s", type(e).__name__)
        ev("memory", {"op": "retrieve", "chars": len(ctx), "ms": round((time.perf_counter() - tm) * 1000, 2)})
        r = self.pool.generate(prompt, on_event=ev, context=ctx)
        passed = check(r.text) if check is not None else None
        cache_ok = (not r.low_confidence and passed is not False
                    and (r.confidence is None or r.confidence >= self.cfg.min_cache_confidence))
        if cache_ok and r.text.strip():
            self._remember(prompt, r.text, meta={"model": r.model, "tier": r.tier})
        stored = bool(cache_ok and r.text.strip() and self.pool.is_teacher(r.tier))
        if stored:  # a checked big-model answer becomes teacher data for the 30B
            try:
                u = r.per_tier[r.tier]
                stored = self.memory.store(prompt, r.text, model=r.model, tier=r.tier, verified=True, tests=passed,
                                           tokens={"in": u.tokens_in, "out": u.tokens_out}) is not None
            except Exception as e:  # noqa: BLE001
                stored = False
                log.warning("memory.store failed: %s", type(e).__name__)
        ev("memory", {"op": "store", "stored": stored, "tier": r.tier, "tests_passed": passed})
        per = self.pool.telemetry_per_tier(r)
        top = self.pool.top
        tin = sum(u.tokens_in for u in r.per_tier.values())
        tout = sum(u.tokens_out for u in r.per_tier.values())
        kept = r.tier != (top.name if top else "")  # answered below the big model: its tokens stayed off it
        a = r.per_tier[r.tier]
        return self._done(
            r.text, {"phone": "local", "laptop": "local", "gpu": "gpu", "cloud": "top"}[r.device], t0,
            tokens_saved=(a.tokens_in + a.tokens_out) if kept else 0,
            dollars_saved=self._price_saved(a.tokens_in, a.tokens_out) if kept else 0.0,
            local_tokens=sum(u.output_tokens for u in per.values() if u.device in ("Phone", "Mac")),
            cloud_tokens=sum(u.output_tokens for u in per.values() if u.device == "Crusoe"),
            per_tier=per, tier_name=r.tier, ev=ev, model=r.model, tokens_in=tin, tokens_out=tout,
            cached_tokens=sum(u.cached_tokens for u in r.per_tier.values()),
            dollars_spent=sum(u.dollars for u in r.per_tier.values()),
        )

    def _store_local(self, prompt: str, draft: DraftResult, t0: float, ev: Events) -> GenerateResult:
        self._remember(prompt, draft.text)
        return self._done(
            draft.text, "local", t0, tokens_saved=draft.n_tokens, local_tokens=draft.n_tokens, ev=ev
        )

    def _verify(self, prompt: str, draft: DraftResult, t0: float, ev: Events) -> GenerateResult:
        assert self.cloud and self.tokenizer
        # The draft saw the ChatML-wrapped prompt, so the target must score the same ids.
        prompt_ids = self.tokenizer.encode(chatml(prompt) if getattr(self.local, "chatml", False) else prompt)
        draft_ids = [i for i in draft.token_ids if i is not None]
        res = self.cloud.verify(prompt_ids, draft_ids, draft.logprobs)
        out_ids = res.accepted_ids + ([res.correction_id] if res.correction_id is not None else [])
        text = self.tokenizer.decode(out_ids)
        self._remember(prompt, text)
        return self._done(
            text, "cloud_verified", t0, tokens_saved=res.n_accepted, alpha=res.alpha,
            local_tokens=len(draft_ids), cloud_tokens=len(draft_ids) - res.n_accepted + 1, ev=ev,
        )

    def _handoff(self, prompt: str, context: str, t0: float, draft: DraftResult | None, ev: Events) -> GenerateResult:
        assert self.cloud
        brief = build_brief(self.local, prompt, context)
        full = cloud_prompt(prompt, brief, draft.text if draft else "")
        text = self.cloud.handoff(full, self.cfg.max_cloud_tokens)
        self._remember(prompt, text)
        return self._done(text, "cloud_handoff", t0, cloud_tokens=len(text) // 4,
                          local_tokens=len(brief) // 4, ev=ev)

    # ---- helpers ------------------------------------------------------------
    def _remember(self, prompt: str, text: str, *, meta: dict | None = None) -> None:
        """Write a checked answer to every configured cache (production: Supabase only)."""
        if self.exact is not None:
            self.exact.put(prompt, text, self.cfg.namespace)
        if self.semantic is not None:
            self.semantic.put(prompt, text, self.cfg.namespace)
        if self.shared is not None:
            from .memory.safety import scrub  # emails, keys, JWTs, DB URLs, card numbers never reach the shared DB
            # the hash/embedding use the raw prompt so lookups still match; only the stored text is scrubbed
            self.shared.put(prompt, scrub(text), self.cfg.namespace, verified=True, stored_prompt=scrub(prompt),
                            **(meta or {}))

    def _done(
        self, text: str, tier: str, t0: float, tokens_saved: int = 0, alpha: float | None = None,
        local_tokens: int = 0, cloud_tokens: int = 0, per_tier: dict | None = None, tier_name: str | None = None,
        ev: Events | None = None, cache_source: str | None = None, dollars_saved: float | None = None,
        model: str = "", tokens_in: int = 0, tokens_out: int = 0, cached_tokens: int = 0,
        dollars_spent: float = 0.0,
    ) -> GenerateResult:
        ms = (time.perf_counter() - t0) * 1000
        if dollars_saved is None:
            dollars_saved = self._price_saved(tokens_saved // 2, tokens_saved - tokens_saved // 2)
        ev = ev or Events()
        ev("final", {"tier": tier_name or tier, "model": model or (cache_source and "cache") or "", "tokens_in": tokens_in,
                     "tokens_out": tokens_out, "cached_tokens": cached_tokens, "dollars": round(dollars_spent, 6),
                     "dollars_saved": round(dollars_saved, 6), "ms": round(ms, 1), "tokens_kept_off_big": tokens_saved,
                     "cache": cache_source})
        tel = Telemetry(
            tier_used=tier, tokens_saved=tokens_saved, acceptance_rate_alpha=alpha, latency_ms=ms,
            dollars_saved=dollars_saved, local_tokens=local_tokens, cloud_tokens=cloud_tokens,
            per_tier=per_tier, tier_name=tier_name, cache_source=cache_source, events=ev.log,
            dollars_spent=dollars_spent, ts=time.time(), tokens_in=tokens_in, tokens_out=tokens_out, **ev.tags,
        )
        self.tracker.emit(tel)
        return GenerateResult(text=text, telemetry=tel)
