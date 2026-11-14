"""Tier pool: a company lists its hardware as `[[tiers]]` in chimera.toml; adding a tier is a config edit.

Routing: cheapest enabled, healthy tier whose max_complexity >= the task's complexity. On low
confidence, a timeout or an error, climb to the next tier that fits. A tier that keeps failing is
skipped for a cooldown (circuit breaker); health probes are cached. Speculative verify is allowed
only between tiers of the same `family`.
Every call returns per-tier token usage in `PoolResult.per_tier` (Telemetry has no per_tier field yet).
"""
from __future__ import annotations

import os
import time
import urllib.request
from typing import Callable, Literal

from pydantic import BaseModel, Field, field_validator

from .router import complexity_score

HUD_KEYS = {"phone_3b", "mac_3b", "gpu_small", "gpu_large", "crusoe"}
DEVICE_LABEL = {"phone": "Phone", "laptop": "Mac", "gpu": "GPU", "cloud": "Crusoe"}  # HUD labels
PROBES = {"llamacpp": "/health", "ollama": "/api/tags", "openai": "/v1/models"}


class TierCfg(BaseModel):
    name: str
    device: Literal["phone", "laptop", "gpu", "cloud"]
    backend: Literal["llamacpp", "ollama", "openai"]
    url: str
    model: str = ""
    family: str = ""
    max_complexity: float = Field(1.0, ge=0.0, le=1.0)
    cost_per_1k_in: float = 0.0   # dollars; 0 for owned hardware
    cost_per_1k_out: float = 0.0
    timeout_s: float = 120.0
    enabled: bool = True
    template_kwargs: dict = Field(default_factory=dict)  # openai backend: chat_template_kwargs
    api_key_env: str = "CRUSOE_API_KEY"  # openai backend: env var holding the key (never the key itself)

    @field_validator("url")
    @classmethod
    def _expand_env(cls, v: str) -> str:  # "$MODAL_VLLM_URL" -> its value; unset stays literal and fails the probe
        return os.path.expandvars(v)


class TierUsage(BaseModel):
    calls: int = 0
    errors: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    dollars: float = 0.0
    latency_ms: float = 0.0
    cached_tokens: int = 0


class PoolResult(BaseModel):
    text: str
    tier: str
    device: str
    latency_ms: float
    per_tier: dict[str, TierUsage]            # every tier tried, including failed attempts
    attempts: list[str]                       # tiers tried, in order
    confidence: float | None = None           # of the answering tier (llama.cpp tiers only)
    low_confidence: bool = False              # True: no tier passed the gate, this is the last low-confidence answer
    model: str = ""


class AllTiersFailed(RuntimeError):
    pass


def can_verify(draft: TierCfg, target: TierCfg) -> bool:
    """Speculative verify needs the same vocabulary: same non-empty family."""
    return bool(draft.family) and draft.family == target.family


def build_backend(t: TierCfg):
    """Return an object with complete(prompt, max_tokens) -> (text, tokens_in, tokens_out, confidence|None)."""
    from .inference.cloud_verifier import OllamaBackend
    from .inference.local_draft import LlamaCppBackend
    from .ladder import TopBackend

    if t.backend == "llamacpp":
        b = LlamaCppBackend(t.url, timeout=t.timeout_s)

        def run(prompt: str, n: int):
            d = b.complete(prompt, n)
            return d.text, len(prompt) // 4, d.n_tokens, d.mean_confidence
    elif t.backend == "ollama":
        ob = OllamaBackend(t.model, t.url, timeout=t.timeout_s)

        def run(prompt: str, n: int):
            text = ob.complete(prompt, n)
            return text, ob.last_usage["prompt_tokens"], ob.last_usage["completion_tokens"], None
    else:
        cb = TopBackend(t.model, t.template_kwargs, api_key=os.environ.get(t.api_key_env, ""),
                        base_url=os.path.expandvars(t.url), timeout=t.timeout_s)

        def run(prompt: str, n: int):
            text = cb.complete(prompt, n)
            return text, cb.last_usage["prompt_tokens"], cb.last_usage["completion_tokens"], None

    class _B:
        complete = staticmethod(run)
        raw = cb if t.backend == "openai" else None  # exposes usage_log (cached_tokens) to benches

    return _B()


def http_probe(t: TierCfg) -> bool:
    try:
        req = urllib.request.Request(os.path.expandvars(t.url).rstrip("/") + PROBES[t.backend],
                                     headers={"User-Agent": "chimera/0.1"})
        if t.backend == "openai" and os.environ.get(t.api_key_env):
            req.add_header("Authorization", "Bearer " + os.environ[t.api_key_env])
        with urllib.request.urlopen(req, timeout=3) as r:  # noqa: S310 (configured URL)
            return r.status == 200
    except Exception:
        return False


class TierPool:
    def __init__(
        self, tiers: list[TierCfg], *, min_confidence: float = 0.85, max_tokens: int = 1024,
        probe: Callable[[TierCfg], bool] = http_probe,
        backend_factory: Callable[[TierCfg], object] = build_backend,
        health_ttl_s: float = 15.0, breaker_threshold: int = 3, breaker_cooldown_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        # Cheapest first; owned hardware (cost 0) is ordered by capability, small before large.
        self.tiers = sorted((t for t in tiers if t.enabled),
                            key=lambda t: (t.cost_per_1k_in + t.cost_per_1k_out, t.max_complexity))
        self.min_confidence, self.max_tokens = min_confidence, max_tokens
        self._probe, self._factory, self._clock = probe, backend_factory, clock
        self._ttl, self._threshold, self._cooldown = health_ttl_s, breaker_threshold, breaker_cooldown_s
        self._health: dict[str, tuple[float, bool]] = {}
        self._fails: dict[str, int] = {}
        self._open_until: dict[str, float] = {}
        self._backends: dict[str, object] = {}

    def healthy(self, t: TierCfg) -> bool:
        now = self._clock()
        if self._open_until.get(t.name, 0.0) > now:
            return False
        cached = self._health.get(t.name)
        if cached is None or now - cached[0] > self._ttl:
            cached = (now, self._probe(t))
            self._health[t.name] = cached
        return cached[1]

    def _record(self, t: TierCfg, ok: bool) -> None:
        if ok:
            self._fails[t.name] = 0
            return
        self._fails[t.name] = self._fails.get(t.name, 0) + 1
        self._health.pop(t.name, None)
        if self._fails[t.name] >= self._threshold:
            self._open_until[t.name] = self._clock() + self._cooldown
            self._fails[t.name] = 0

    @property
    def top(self) -> TierCfg | None:
        """The most expensive tier: what 'kept off the big model' is measured against."""
        return max(self.tiers, key=lambda t: (t.cost_per_1k_in + t.cost_per_1k_out, t.max_complexity), default=None)

    def generate(self, prompt: str, complexity: float | None = None,
                 on_event: Callable[[str, dict], None] | None = None) -> PoolResult:
        ev = on_event or (lambda step, data: None)
        t0 = time.perf_counter()
        score = complexity_score(prompt) if complexity is None else complexity
        usage: dict[str, TierUsage] = {}
        attempts: list[str] = []
        fallback: tuple[str, TierCfg, float | None] | None = None  # last low-confidence answer
        why, skipped = f"cheapest healthy tier that covers complexity {score:.2f}", []
        for t in (x for x in self.tiers if x.max_complexity >= score):
            if not self.healthy(t):
                skipped.append(t.name)
                continue
            ev("decide", {"tier": t.name, "reason": why + (f"; skipped unhealthy: {', '.join(skipped)}" if skipped else "")})
            attempts.append(t.name)
            u = usage.setdefault(t.name, TierUsage())
            u.calls += 1
            ta = time.perf_counter()
            try:
                be = self._backends.get(t.name) or self._backends.setdefault(t.name, self._factory(t))
                text, tin, tout, conf = be.complete(prompt, self.max_tokens)
            except Exception as e:  # timeout, connection or HTTP error: climb
                ms = (time.perf_counter() - ta) * 1000
                u.latency_ms += ms
                u.errors += 1
                self._record(t, False)
                err = type(e).__name__
                ev("call", {"tier": t.name, "model": t.model, "ok": False, "error": err, "ms": round(ms, 1),
                            "tokens_in": 0, "tokens_out": 0, "cached_tokens": 0})
                why, skipped = f"climb: {t.name} failed ({err})", []
                continue
            ms = (time.perf_counter() - ta) * 1000
            u.latency_ms += ms
            self._record(t, True)
            u.tokens_in, u.tokens_out = tin, tout
            u.cached_tokens = int(((getattr(be, "raw", None) and be.raw.last_usage) or {}).get("cached_tokens", 0))
            u.dollars = tin / 1000 * t.cost_per_1k_in + tout / 1000 * t.cost_per_1k_out
            ev("call", {"tier": t.name, "model": t.model, "ok": True, "ms": round(ms, 1), "tokens_in": tin,
                        "tokens_out": tout, "cached_tokens": u.cached_tokens})
            if conf is not None:
                ev("draft", {"tier": t.name, "model": t.model, "confidence": round(conf, 4), "gate": self.min_confidence})
            if conf is not None and conf < self.min_confidence:
                fallback = (text, t, conf)  # low confidence: climb (its tokens stay billed to this tier)
                why, skipped = f"climb: {t.name} confidence {conf:.3f} < gate {self.min_confidence}", []
                continue
            return self._result(text, t, attempts, usage, t0, conf)
        if fallback:
            ev("decide", {"tier": fallback[1].name, "reason": "no tier above answered; serving the last low-confidence answer"})
            return self._result(fallback[0], fallback[1], attempts, usage, t0, fallback[2], low=True)
        raise AllTiersFailed(f"no tier answered (tried: {attempts or 'none healthy'})")

    def telemetry_per_tier(self, r: PoolResult) -> dict:
        """Fill Telemetry.per_tier (fixed keys: gpu-small -> gpu_small, any cloud tier -> crusoe)."""
        from .inference.telemetry import TierUsage as HudUsage
        by_name = {t.name: t for t in self.tiers}
        out: dict[str, HudUsage] = {}
        for name, u in r.per_tier.items():
            t = by_name[name]
            key = "crusoe" if t.device == "cloud" else name.replace("-", "_")
            if key not in HUD_KEYS:  # shortcut: Telemetry.per_tier has fixed keys; extra tiers are left out until it takes any name
                continue
            h = out.setdefault(key, HudUsage(model=t.model, device=DEVICE_LABEL[t.device]))
            h.model = t.model  # actual model name (e.g. Qwen2.5-3B on the phone), last tier touched wins
            h.input_tokens += u.tokens_in
            h.output_tokens += u.tokens_out
            h.dollars += u.dollars
            h.latency_ms += u.latency_ms
        return out

    @staticmethod
    def _result(text, t, attempts, usage, t0, conf=None, low=False) -> PoolResult:
        return PoolResult(text=text, tier=t.name, device=t.device, attempts=attempts, model=t.model,
                          confidence=conf, low_confidence=low,
                          latency_ms=(time.perf_counter() - t0) * 1000, per_tier=usage)
