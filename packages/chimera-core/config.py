"""chimera.toml loader: validates the file and builds a LadderRouter from it.

Secrets are never read from the toml. CRUSOE_API_KEY comes from the environment or the repo's .env.
"""
from __future__ import annotations

import logging
import os
import pathlib
import threading
import tomllib
from typing import Literal

from pydantic import BaseModel, Field

from .cache.exact_cache import ExactCache
from .cache.semantic_cache import CachedEmbedder, Embedder, OnnxMiniLMEmbedder, SemanticCache
from .inference.cloud_verifier import CrusoeBackend, OllamaBackend
from .inference.local_draft import LlamaCppBackend
from .inference.telemetry import TelemetryTracker
from .router import RouterConfig, SpeculativeCascadeRouter
from .tiers import PROBES, TierCfg, TierPool
from .ladder import LadderConfig, LadderRouter, TopBackend

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


class LocalCfg(BaseModel):
    url: str = "http://127.0.0.1:8080"
    chatml: bool = True


class GpuCfg(BaseModel):
    enabled: bool = True
    url: str = "http://127.0.0.1:11435"
    model: str = "qwen3:30b-instruct"


class CrusoeCfg(BaseModel):
    base_url: str = "https://api.inference.crusoecloud.com"
    mid_model: str = "Qwen/Qwen3.8-27B"
    top_model: str = "openai/gpt-oss-120b"
    top_template_kwargs: dict = Field(default_factory=lambda: {"reasoning_effort": "low"})


class Thresholds(BaseModel):
    semantic: float = 0.97
    confidence: float = 0.95     # local mean token probability to answer locally; 0.85 -> 0.95 lifted accuracy 70% -> 82.8% (bench/results_backend.md)
    heavy: float = 0.6
    learned_router: str = ""  # path to router_weights.json; "" keeps keyword complexity_score + confidence gate


class PathCfg(BaseModel):
    path: str


class CacheCfg(BaseModel):
    backend: Literal["supabase", "postgres", "sqlite"] = "supabase"  # supabase (= postgres): the only answer cache
    path: str = "~/.chimera/cache.db"  # sqlite backend only (offline tests); never created otherwise
    semantic: bool = True              # sqlite backend only: false = exact cache only
    dsn_env: str = "CHIMERA_DB_URL"                    # NAME of the env var holding the DSN. The DSN is never in toml.
    tenant: str = "default"
    store_text: bool = False       # opt-in: keep prompt text in the shared DB
    ttl_s: int | None = None       # row lifetime in seconds; None = forever
    top_k: int = 5
    budget_ms: int = 300           # DB time per lookup (measured ~120 ms); over it the call skips the cache
    guard: bool = True  # MeanCache-style false-hit guard on semantic hits (cache/guard.py); wrong hits 4 -> 2 of 34
    # Paraphrases (cache/band.py, bench/results_paraphrase_cache.md). Need store_text = true.
    normalize: bool = True         # also compare prompts with polite lead-ins, punctuation and case stripped (0 added wrong hits)
    band_low: float = 0.0          # > 0: cosine in [band_low, semantic threshold) is served after guard + check; 0 = off
    band_check: str = ""           # [[tiers]] name of the yes/no checker (the self-hosted 30B: "gpu-small"); "" = guard only
    band_check_timeout_s: float = 5.0  # per check; over it, or an error: a miss (then no check for 60 s)


class GatewayCfg(BaseModel):
    db: str = "~/.chimera/gateway.db"   # API key hashes + audit log
    rate_per_min: float = 120.0         # per-key token bucket refill
    burst: int = 30                     # per-key bucket size
    max_body_bytes: int = 1_000_000
    timeout_s: float = 90.0             # per backend call; the whole request may take 2x this
    retry_backoff_s: float = 1.0
    log_prompts: bool = False           # opt-in: put prompt text in request logs
    actions: bool = False               # enable POST /v1/actions/score


class MemoryCfg(BaseModel):
    enabled: bool = True  # N+1 memory: 30B gets solved examples; checked big-model answers are stored (docs/memory.md)


def _guard(cfg: "ChimeraConfig"):
    from .cache.guard import make_guard
    return make_guard() if cfg.cache.guard else None


class ChimeraConfig(BaseModel):
    local: LocalCfg = LocalCfg()
    gpu: GpuCfg = GpuCfg()
    crusoe: CrusoeCfg = CrusoeCfg()
    thresholds: Thresholds = Thresholds()
    cache: CacheCfg = CacheCfg()
    telemetry: PathCfg = PathCfg(path="~/.chimera/telemetry.jsonl")
    gateway: GatewayCfg = GatewayCfg()
    use_pool: bool = False  # true: route through [[tiers]] (needs at least one)
    memory: MemoryCfg = MemoryCfg()
    tiers: list[TierCfg] = Field(default_factory=list)  # empty: the fixed 4-tier ladder is used

    @property
    def cache_path(self) -> pathlib.Path:
        return pathlib.Path(self.cache.path).expanduser()

    @property
    def gateway_db(self) -> pathlib.Path:
        return pathlib.Path(os.environ.get("CHIMERA_GATEWAY_DB") or self.gateway.db).expanduser()

    @property
    def telemetry_path(self) -> pathlib.Path:
        return pathlib.Path(os.environ.get("CHIMERA_TELEMETRY") or self.telemetry.path).expanduser()


def tier_checks(cfg: ChimeraConfig) -> list[tuple[str, str, str, dict]]:
    """(name, base_url, probe_url, headers) for each configured tier. Used by `chimera doctor` and /readyz."""
    load_env()
    if cfg.use_pool and cfg.tiers:  # the pool is what routes; [local]/[gpu] are not used then
        out = []
        for t in cfg.tiers:
            if t.enabled:
                k = os.environ.get(t.api_key_env, "") if t.backend == "openai" else ""
                url = os.path.expandvars(t.url)
                out.append((t.name, url, url.rstrip("/") + PROBES[t.backend], {"Authorization": f"Bearer {k}"} if k else {}))
        return out
    key = os.environ.get("CRUSOE_API_KEY", "")
    checks = [("local", cfg.local.url, f"{cfg.local.url.rstrip('/')}/health", {})]
    if cfg.gpu.enabled:
        checks.append(("gpu", cfg.gpu.url, f"{cfg.gpu.url.rstrip('/')}/api/tags", {}))
    checks.append(("crusoe", cfg.crusoe.base_url, f"{cfg.crusoe.base_url.rstrip('/')}/v1/models",
                   {"Authorization": f"Bearer {key}"} if key else {}))
    return checks


def load_config(path: str | os.PathLike | None = None) -> ChimeraConfig:
    """`path`, else $CHIMERA_CONFIG, else <repo>/chimera.toml, else built-in defaults. .env is read first ($VARS in tier URLs)."""
    load_env()
    p = pathlib.Path(path or os.environ.get("CHIMERA_CONFIG") or ROOT / "chimera.toml")
    if not p.exists():
        if path or os.environ.get("CHIMERA_CONFIG"):
            raise FileNotFoundError(p)
        return ChimeraConfig()
    return ChimeraConfig.model_validate(tomllib.loads(p.read_text()))


def product_tier(name: str) -> TierCfg:
    """The [[tiers]] entry `name` as the product runs it (chimera.toml, else chimera.example.toml).
    Benches take their GPU tier from here so num_thread, keep_alive and timeout cannot drift from the product:
    an Ollama call with other runner options (num_thread) also reloads the model on the GPU box."""
    tiers = load_config().tiers or load_config(ROOT / "chimera.example.toml").tiers
    for t in tiers:
        if t.name == name:
            return t
    raise KeyError(f"no [[tiers]] entry named {name!r}")


def load_env(env_file: pathlib.Path = ROOT / ".env") -> None:
    """Fill os.environ from .env without overriding real environment variables."""
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip())


class _LazyEmbedder:
    """Defers the sentence-transformers import until the first cache lookup."""

    def __init__(self) -> None:
        self._inner: Embedder | None = None

    def embed(self, text: str) -> list[float]:
        self._inner = self._inner or OnnxMiniLMEmbedder()
        return self._inner.embed(text)


class _NoKey:
    def complete(self, prompt: str, max_tokens: int = 0) -> str:
        raise RuntimeError("CRUSOE_API_KEY is not set (put it in .env or the environment)")


def make_caches(cfg: ChimeraConfig, embedder: Embedder | None, threshold: float):
    """(exact, semantic, shared, embedder) for the router.

    backend = "supabase" (default): the ONLY answer cache is the shared PgVectorCache (exact hash, then pgvector
    cosine). Nothing is cached on this machine; with no DSN, or the DB down, calls go straight to the tiers.
    backend = "sqlite": the old local exact + semantic caches, for offline tests only.
    """
    cc = cfg.cache
    if cc.backend == "sqlite":
        emb = CachedEmbedder(embedder or _LazyEmbedder()) if cc.semantic else None
        sem = SemanticCache(emb, threshold, str(cfg.cache_path), guard=_guard(cfg)) if emb else None
        return ExactCache(path=str(cfg.cache_path)), sem, None, emb
    dsn = os.environ.get(cc.dsn_env, "")
    if not dsn:
        logging.getLogger("chimera").warning("cache.backend=supabase but %s is not set; no answer cache", cc.dsn_env)
        return None, None, None, None
    from .cache.pgvector_cache import PgStore, PgVectorCache

    emb = CachedEmbedder(embedder or _LazyEmbedder())  # one embedding per prompt for the router and the cache
    band_low, checker = band_settings(cfg)
    shared = PgVectorCache(emb, lambda: PgStore(dsn), threshold=threshold, tenant=cc.tenant,
                           fallback=None, store_text=cc.store_text, ttl_s=cc.ttl_s, top_k=cc.top_k,
                           budget_s=cc.budget_ms / 1000, guard=_guard(cfg), normalize=cc.normalize,
                           band_low=band_low, checker=checker)
    # Open the DB link now, in the background (a dead DB must not block startup): a cold first lookup took about
    # 310 ms, ran past its 300 ms budget and skipped the cache for the first call of every process.
    threading.Thread(target=_ping, args=(shared,), daemon=True).start()
    return None, None, shared, emb


def band_settings(cfg: ChimeraConfig, factory=None):
    """(band_low, checker) for the shared cache. A band with a named checker that cannot be built is turned off
    (never silently weaker), and so is a band without stored prompt text (the guard and the check need it)."""
    cc, log = cfg.cache, logging.getLogger("chimera")
    if cc.band_low <= 0:
        return 0.0, None
    if not cc.store_text:
        log.warning("cache.band_low needs cache.store_text = true; band off")
        return 0.0, None
    if not cc.band_check:
        return cc.band_low, None
    t = next((x for x in cfg.tiers if x.name == cc.band_check), None)
    if t is None or t.backend == "llamacpp":
        log.warning("cache.band_check %r is not an ollama/openai [[tiers]] entry; band off", cc.band_check)
        return 0.0, None
    from .cache.band import make_checker
    from .tiers import build_backend

    raw = (factory or build_backend)(checker_tier(t, cc.band_check_timeout_s)).raw
    return cc.band_low, make_checker(raw.complete, usage=lambda: getattr(raw, "last_usage", {}) or {})


def checker_tier(t: TierCfg, timeout_s: float) -> TierCfg:
    """The tier as the yes/no checker runs it: short timeout, temperature 0 (the same pair gets the same verdict).
    temperature is a sampling option, so Ollama keeps the loaded 30B (num_thread is unchanged)."""
    return t.model_copy(update={"timeout_s": timeout_s, "options": {**t.options, "temperature": 0}})


def _ping(shared) -> None:
    try:
        shared.ping(10.0)
    except Exception:  # noqa: BLE001  down: lookups report "unavailable" and the tiers answer
        pass


def make_memory(cfg: ChimeraConfig, embedder: Embedder | None):
    """N+1 teacher memory (packages/chimera-core/memory/, docs/memory.md), or None (the router then uses NoMemory).

    Never fails the router build: a missing driver or an unreachable store logs a warning and turns memory off.
    """
    if not cfg.memory.enabled:
        return None
    try:
        from . import memory as mem
        return mem.build(embedder or CachedEmbedder(_LazyEmbedder()), tenant=cfg.cache.tenant)
    except Exception as e:  # noqa: BLE001
        logging.getLogger("chimera").warning("memory off: %s", type(e).__name__)
        return None


def build_router(cfg: ChimeraConfig, *, local=None, mid=None, top=None, embedder: Embedder | None = None,
                 tracker: TelemetryTracker | None = None) -> LadderRouter:
    """Backend/embedder/tracker arguments are test seams; production passes none of them."""
    load_env()
    has_key = bool(os.environ.get("CRUSOE_API_KEY"))
    cr = cfg.crusoe
    local = local or LlamaCppBackend(cfg.local.url, chatml=cfg.local.chatml)
    if mid is None:
        if cfg.gpu.enabled:
            mid = OllamaBackend(cfg.gpu.model, cfg.gpu.url)
        else:
            mid = CrusoeBackend(cr.mid_model, base_url=cr.base_url) if has_key else _NoKey()
    if top is None:
        top = (TopBackend(cr.top_model, cr.top_template_kwargs, base_url=cr.base_url)
               if has_key else _NoKey())
    if cfg.cache.backend == "sqlite":
        cfg.cache_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.telemetry_path.parent.mkdir(parents=True, exist_ok=True)
    t = cfg.thresholds
    exact, sem, shared, emb = make_caches(cfg, embedder, t.semantic)
    exact = exact if exact is not None else False  # False: no exact cache on this machine
    if cfg.use_pool and cfg.tiers:
        return SpeculativeCascadeRouter(
            local, exact=exact, semantic=sem, shared=shared, embedder=emb,
            tracker=tracker or TelemetryTracker([TelemetryTracker.jsonl_sink(str(cfg.telemetry_path))]),
            config=RouterConfig(min_confidence=t.confidence, heavy_threshold=t.heavy),
            pool=TierPool(cfg.tiers, min_confidence=t.confidence), memory=make_memory(cfg, emb),
        )
    return LadderRouter(
        local, mid, top,
        LadderConfig(min_confidence=t.confidence, heavy_threshold=t.heavy, learned_router=t.learned_router),
        exact=exact, semantic=sem, shared=shared, embedder=emb,
        tracker=tracker or TelemetryTracker([TelemetryTracker.jsonl_sink(str(cfg.telemetry_path))]),
    )
