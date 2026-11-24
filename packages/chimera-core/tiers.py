"""Tier pool: a company lists its hardware as `[[tiers]]` in chimera.toml; adding a tier is a config edit.

Routing: cheapest enabled, healthy tier whose max_complexity >= the task's complexity. On low
confidence, a timeout or an error, climb to the next tier that fits. A tier that keeps failing is
skipped for a cooldown (circuit breaker); health probes are cached, and a failed call marks the tier
down until its next probe. A `warm_only` tier (Modal H200) goes first, but only while warm: its warm
check runs in the background, and a cold tier is skipped. A cold check starts the app only when the tier sets
`wake = true`; without it the router never starts a paid GPU.
OpenAI-style tiers (the 763B) retry up to RETRIES times on HTTP 429 or 5xx before they climb.
A tier that answers with empty text climbs too; an empty answer is never served.
Speculative verify is allowed only between tiers of the same `family`.
Every call returns per-tier token usage in `PoolResult.per_tier` (Telemetry has no per_tier field yet).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Literal

from pydantic import BaseModel, Field, field_validator

from .router import complexity_score

HUD_KEYS = {"phone_3b", "mac_3b", "gpu_small", "gpu_large", "gpu_h200", "crusoe"}
DEVICE_LABEL = {"phone": "Phone", "laptop": "Mac", "gpu": "GPU", "cloud": "Crusoe"}  # HUD labels
PROBES = {"llamacpp": "/health", "ollama": "/api/tags", "openai": "/v1/models"}
RETRIES, BACKOFF_S = 2, 1.0  # openai tiers: retries on 429/5xx, seconds of backoff per retry (Retry-After wins, max 10 s)
_sleep = time.sleep  # test seam


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
    teacher: bool = False  # a big model: its checked answers are stored as N+1 memory (the top tier counts if none is set)
    # A scale-to-zero GPU (Modal): used only while warm, tried before every other tier then (it is billed by the
    # second while up, so a call costs nothing extra). Cold: skipped at once and woken in the background.
    warm_only: bool = False
    modal_app: str = ""  # warm_only: Modal app name; warm = a running container (read-only `modal container list`)
    wake: bool = False  # warm_only: a cold check may start a container (it bills). Off: cold stays cold until started by hand
    logprobs: bool = False  # openai backend: ask for token logprobs and gate on mean token probability (vLLM)
    # ollama backend: runtime options sent with every call, e.g. {num_thread = 4} (bench/results_akash_tuning.md)
    options: dict = Field(default_factory=dict)
    keep_alive: int | str | None = None  # ollama backend: how long the model stays loaded; -1 = always, None = server default

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
        ob = OllamaBackend(t.model, t.url, timeout=t.timeout_s, options=t.options, keep_alive=t.keep_alive)
        ob.api_key = _ollama_key(t)  # an Ollama behind a token proxy (e.g. a public tunnel); "" sends no header

        def run(prompt: str, n: int):
            text = ob.complete(prompt, n)
            conf, u = ob.last_confidence, dict(ob.last_usage)
            if conf is None:  # this Ollama sent no logprobs: the 30B checks its own answer (one short extra call)
                from .ladder import CHECK_PROMPT
                conf = 0.0 if "ESCALATE" in ob.complete(CHECK_PROMPT.format(task=prompt, answer=text), 8).upper() else 1.0
                ob.last_usage = u
            return text, u["prompt_tokens"], u["completion_tokens"], conf
    else:
        cb = TopBackend(t.model, t.template_kwargs, api_key=os.environ.get(t.api_key_env, ""),
                        base_url=os.path.expandvars(t.url), timeout=t.timeout_s, logprobs=t.logprobs)

        def run(prompt: str, n: int):
            for i in range(RETRIES + 1):
                try:
                    text = cb.complete(prompt, n)
                    break
                except urllib.error.HTTPError as e:  # 429 rate limit or 5xx: wait (Retry-After, capped), try again
                    if i == RETRIES or not (e.code == 429 or e.code >= 500):
                        raise
                    try:
                        wait = float(e.headers.get("Retry-After") or 0)
                    except (TypeError, ValueError):  # an HTTP date or junk: use the backoff
                        wait = 0.0
                    _sleep(min(wait or BACKOFF_S * (i + 1), 10.0))
            return text, cb.last_usage["prompt_tokens"], cb.last_usage["completion_tokens"], cb.last_confidence

    class _B:
        complete = staticmethod(run)
        raw = cb if t.backend == "openai" else ob if t.backend == "ollama" else None  # usage (cached_tokens)

    return _B()


def _ollama_key(t: TierCfg) -> str:
    """Bearer key for an Ollama tier, only when its config names api_key_env itself: the default names the
    Crusoe key, which must never be sent to a GPU box."""
    return os.environ.get(t.api_key_env, "") if "api_key_env" in t.model_fields_set else ""


def http_probe(t: TierCfg) -> bool:
    try:
        req = urllib.request.Request(os.path.expandvars(t.url).rstrip("/") + PROBES[t.backend],
                                     headers={"User-Agent": "chimera/0.1"})
        key = os.environ.get(t.api_key_env, "") if t.backend == "openai" else _ollama_key(t) if t.backend == "ollama" else ""
        if key:
            req.add_header("Authorization", "Bearer " + key)
        with urllib.request.urlopen(req, timeout=3) as r:  # noqa: S310 (configured URL)
            return r.status == 200
    except Exception:
        return False


def modal_running(app: str) -> bool | None:
    """True when the Modal app has a running container, None when the modal CLI cannot tell. Never wakes the app."""
    exe = shutil.which("modal") or str(pathlib.Path(__file__).resolve().parents[2] / ".venv/bin/modal")
    try:
        out = subprocess.run([exe, "container", "list", "--json"], capture_output=True, text=True, timeout=20).stdout
        return any(c.get("app_name") == app for c in json.loads(out))
    except Exception:  # noqa: BLE001
        return None


def warm_probe(t: TierCfg) -> bool:
    """warm_only tiers: a running container that answers /v1/models. Without the modal CLI, the HTTP probe alone."""
    running = modal_running(t.modal_app) if t.modal_app else None
    return running is not False and http_probe(t)


def wake(t: TierCfg) -> None:
    """One request makes Modal start a container; it returns when the server is up (cold start: minutes)."""
    req = urllib.request.Request(os.path.expandvars(t.url).rstrip("/") + PROBES[t.backend],
                                 headers={"User-Agent": "chimera/0.1"})
    if os.environ.get(t.api_key_env):
        req.add_header("Authorization", "Bearer " + os.environ[t.api_key_env])
    try:
        urllib.request.urlopen(req, timeout=900).close()  # noqa: S310 (configured URL)
    except Exception:  # noqa: BLE001  not deployed or still starting: the next refresh tries again
        pass


def unset_env(url: str) -> str | None:
    """Name of the env var a tier URL still waits for ("$CHIMERA_120B_URL" with nothing set), else None.
    A tier with an unset URL is off: its probe fails at once (no request is sent), so the pool skips it, and
    `chimera doctor` shows it as off, not down."""
    m = re.search(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", url)
    return m.group(1) if m else None


def _spawn(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, daemon=True).start()


class TierPool:
    def __init__(
        self, tiers: list[TierCfg], *, min_confidence: float = 0.85, max_tokens: int = 1024,
        probe: Callable[[TierCfg], bool] = http_probe,
        backend_factory: Callable[[TierCfg], object] = build_backend,
        health_ttl_s: float = 15.0, breaker_threshold: int = 3, breaker_cooldown_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        warm_check: Callable[[TierCfg], bool] = warm_probe, waker: Callable[[TierCfg], None] = wake,
        spawn: Callable[[Callable[[], None]], None] = _spawn,
    ) -> None:
        # Warm-only tiers first (already paid for while up), then cheapest; owned hardware (cost 0) is ordered by
        # capability, small before large. Ties keep config order.
        self.tiers = sorted((t for t in tiers if t.enabled),
                            key=lambda t: (not t.warm_only, t.cost_per_1k_in + t.cost_per_1k_out, t.max_complexity))
        self.min_confidence, self.max_tokens = min_confidence, max_tokens
        self._probe, self._factory, self._clock = probe, backend_factory, clock
        self._warm_check, self._waker, self._spawn = warm_check, waker, spawn
        self._refreshing: set[str] = set()
        self._waking: set[str] = set()
        self._bg = threading.Lock()
        self._ttl, self._threshold, self._cooldown = health_ttl_s, breaker_threshold, breaker_cooldown_s
        self._health: dict[str, tuple[float, bool]] = {}
        self._fails: dict[str, int] = {}
        self._open_until: dict[str, float] = {}
        self._backends: dict[str, object] = {}

    def healthy(self, t: TierCfg) -> bool:
        now = self._clock()
        if self._open_until.get(t.name, 0.0) > now:
            return False
        if t.warm_only:
            return self._warm(t, now)
        cached = self._health.get(t.name)
        if cached is None or now - cached[0] > self._ttl:
            cached = (now, self._probe(t))
            self._health[t.name] = cached
        return cached[1]

    def _warm(self, t: TierCfg, now: float) -> bool:
        """Never blocks a call: answer from the last check and refresh it in the background when stale.
        Unknown counts as cold. A cold check starts one wake request, so the next calls find it warm."""
        cached = self._health.get(t.name)
        with self._bg:
            go = (cached is None or now - cached[0] > self._ttl) and t.name not in self._refreshing
            if go:
                self._refreshing.add(t.name)
        if go:
            self._spawn(lambda: self._refresh_warm(t))
        return bool(cached and cached[1])

    def _refresh_warm(self, t: TierCfg) -> None:
        try:
            warm = bool(self._warm_check(t))
        except Exception:  # noqa: BLE001
            warm = False
        self._health[t.name] = (self._clock(), warm)
        with self._bg:
            self._refreshing.discard(t.name)
            wake_now = not warm and t.wake and t.name not in self._waking
            if wake_now:
                self._waking.add(t.name)
        if wake_now:
            def run() -> None:
                try:
                    self._waker(t)
                finally:
                    with self._bg:
                        self._waking.discard(t.name)
            self._spawn(run)

    def _record(self, t: TierCfg, ok: bool, down: bool = True) -> None:
        if ok:
            self._fails[t.name] = 0
            return
        self._fails[t.name] = self._fails.get(t.name, 0) + 1
        # Down until the next probe (health_ttl_s): a hung tier whose /api/tags still answers (a dead SSH tunnel)
        # costs one timeout, not one per call until the breaker opens. down=False (the server answered with an
        # HTTP error such as 429): it is reachable, so only the breaker counts it; a lone top tier is not lost for 15 s.
        if down:
            self._health[t.name] = (self._clock(), False)
        if self._fails[t.name] >= self._threshold:
            self._open_until[t.name] = self._clock() + self._cooldown
            self._fails[t.name] = 0

    def is_teacher(self, name: str) -> bool:
        t = next((x for x in self.tiers if x.name == name), None)
        if t is None:
            return False
        return t.teacher or (not any(x.teacher for x in self.tiers) and t is self.top)

    @property
    def top(self) -> TierCfg | None:
        """The most expensive tier: what 'kept off the big model' is measured against."""
        return max(self.tiers, key=lambda t: (t.cost_per_1k_in + t.cost_per_1k_out, t.max_complexity), default=None)

    def generate(self, prompt: str, complexity: float | None = None,
                 on_event: Callable[[str, dict], None] | None = None, context: str = "") -> PoolResult:
        """context: solved examples from memory, prepended for owned (non-cloud) tiers only."""
        ev = on_event or (lambda step, data: None)
        t0 = time.perf_counter()
        score = complexity_score(prompt) if complexity is None else complexity
        usage: dict[str, TierUsage] = {}
        attempts: list[str] = []
        fallback: tuple[str, TierCfg, float | None] | None = None  # last low-confidence answer
        why, skipped = f"cheapest healthy tier that covers complexity {score:.2f}", []
        for t in (x for x in self.tiers if x.max_complexity >= score):
            low = fallback[1] if fallback else None
            if low and t.family and t.family == low.family and t.max_complexity <= low.max_complexity:
                skipped.append(f"{t.name} (same family as {low.name}, no stronger)")  # H200 30B -> Akash 30B: would not be surer
                continue
            if not self.healthy(t):
                skipped.append(t.name)
                continue
            ev("decide", {"tier": t.name, "reason": why + (f"; skipped: {', '.join(skipped)}" if skipped else "")})
            attempts.append(t.name)
            u = usage.setdefault(t.name, TierUsage())
            u.calls += 1
            ta = time.perf_counter()
            try:
                be = self._backends.get(t.name) or self._backends.setdefault(t.name, self._factory(t))
                full = f"{context}\n\n{prompt}" if context and t.device != "cloud" else prompt
                text, tin, tout, conf = be.complete(full, self.max_tokens)
            except Exception as e:  # timeout, connection or HTTP error: climb
                ms = (time.perf_counter() - ta) * 1000
                u.latency_ms += ms
                u.errors += 1
                self._record(t, False, down=not isinstance(e, urllib.error.HTTPError))
                err = type(e).__name__
                code = f"http_{e.code}" if isinstance(e, urllib.error.HTTPError) and e.code in (429, 503) else "error"
                ev("call", {"tier": t.name, "model": t.model, "ok": False, "error": err, "ms": round(ms, 1),
                            "tokens_in": 0, "tokens_out": 0, "cached_tokens": 0,
                            "climb_reason": code})  # own reason: reports count 429s apart from failed checks
                why, skipped = f"climb: {t.name} failed ({err})", []
                continue
            ms = (time.perf_counter() - ta) * 1000
            u.latency_ms += ms
            self._record(t, True)
            u.tokens_in, u.tokens_out = tin, tout
            u.cached_tokens = int(((getattr(be, "raw", None) and be.raw.last_usage) or {}).get("cached_tokens", 0))
            u.dollars = tin / 1000 * t.cost_per_1k_in + tout / 1000 * t.cost_per_1k_out
            ev("call", {"tier": t.name, "model": t.model, "ok": True, "ms": round(ms, 1), "tokens_in": tin,
                        "tokens_out": tout, "cached_tokens": u.cached_tokens,
                        **({} if (text or "").strip() else {"climb_reason": "empty_answer"})})
            if not (text or "").strip():  # never served (a model that only thought): climb, no health strike
                why, skipped = f"climb: {t.name} gave an empty answer", []
                continue
            if conf is not None:
                ev("draft", {"tier": t.name, "model": t.model, "confidence": round(conf, 4), "gate": self.min_confidence,
                            **({"climb_reason": "low_confidence"} if conf < self.min_confidence else {})})
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
