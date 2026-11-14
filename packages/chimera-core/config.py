"""chimera.toml loader: validates the file and builds a LadderRouter from it.

Secrets are never read from the toml. CRUSOE_API_KEY comes from the environment or the repo's .env.
"""
from __future__ import annotations

import os
import pathlib
import tomllib

from pydantic import BaseModel, Field

from .cache.exact_cache import ExactCache
from .cache.semantic_cache import Embedder, OnnxMiniLMEmbedder, SemanticCache
from .inference.cloud_verifier import CrusoeBackend, OllamaBackend
from .inference.local_draft import LlamaCppBackend
from .inference.telemetry import TelemetryTracker
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
    confidence: float = 0.85
    heavy: float = 0.6


class PathCfg(BaseModel):
    path: str


class CacheCfg(BaseModel):
    path: str = "~/.chimera/cache.db"
    semantic: bool = True


class GatewayCfg(BaseModel):
    db: str = "~/.chimera/gateway.db"   # API key hashes + audit log
    rate_per_min: float = 120.0         # per-key token bucket refill
    burst: int = 30                     # per-key bucket size
    max_body_bytes: int = 1_000_000
    timeout_s: float = 90.0             # per backend call; the whole request may take 2x this
    retry_backoff_s: float = 1.0
    log_prompts: bool = False           # opt-in: put prompt text in request logs
    actions: bool = False               # enable POST /v1/actions/score


class ChimeraConfig(BaseModel):
    local: LocalCfg = LocalCfg()
    gpu: GpuCfg = GpuCfg()
    crusoe: CrusoeCfg = CrusoeCfg()
    thresholds: Thresholds = Thresholds()
    cache: CacheCfg = CacheCfg()
    telemetry: PathCfg = PathCfg(path="~/.chimera/telemetry.jsonl")
    gateway: GatewayCfg = GatewayCfg()

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
    key = os.environ.get("CRUSOE_API_KEY", "")
    checks = [("local", cfg.local.url, f"{cfg.local.url.rstrip('/')}/health", {})]
    if cfg.gpu.enabled:
        checks.append(("gpu", cfg.gpu.url, f"{cfg.gpu.url.rstrip('/')}/api/tags", {}))
    checks.append(("crusoe", cfg.crusoe.base_url, f"{cfg.crusoe.base_url.rstrip('/')}/v1/models",
                   {"Authorization": f"Bearer {key}"} if key else {}))
    return checks


def load_config(path: str | os.PathLike | None = None) -> ChimeraConfig:
    """`path`, else $CHIMERA_CONFIG, else <repo>/chimera.toml, else built-in defaults."""
    p = pathlib.Path(path or os.environ.get("CHIMERA_CONFIG") or ROOT / "chimera.toml")
    if not p.exists():
        if path or os.environ.get("CHIMERA_CONFIG"):
            raise FileNotFoundError(p)
        return ChimeraConfig()
    return ChimeraConfig.model_validate(tomllib.loads(p.read_text()))


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
    cfg.cache_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.telemetry_path.parent.mkdir(parents=True, exist_ok=True)
    t = cfg.thresholds
    return LadderRouter(
        local, mid, top,
        LadderConfig(min_confidence=t.confidence, heavy_threshold=t.heavy),
        exact=ExactCache(path=str(cfg.cache_path)),
        semantic=(SemanticCache(embedder or _LazyEmbedder(), t.semantic, str(cfg.cache_path))
                  if cfg.cache.semantic else None),
        tracker=tracker or TelemetryTracker([TelemetryTracker.jsonl_sink(str(cfg.telemetry_path))]),
    )
