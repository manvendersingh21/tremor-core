"""Structured telemetry emitted for every LLM call."""
from __future__ import annotations

import json
import threading
from typing import Callable, Literal

from pydantic import BaseModel, Field, model_validator

Tier = Literal["exact_cache", "semantic_cache", "local", "cloud_verified", "cloud_handoff", "gpu", "top"]


# Keys of Telemetry.per_tier. The HUD ledger reads these names.
TierKey = Literal["phone_3b", "mac_3b", "gpu_small", "gpu_large", "crusoe"]


class TierUsage(BaseModel):
    """What one tier spent on one call. `model` is the exact model name (a Crusoe call names its model)."""
    model: str
    device: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    dollars: float = 0.0  # cloud list price only; local tiers stay 0


class Telemetry(BaseModel):
    tier_used: Tier
    tokens_saved: int = 0
    acceptance_rate_alpha: float | None = Field(default=None, ge=0.0, le=1.0)
    latency_ms: float = 0.0
    dollars_saved: float = 0.0
    cloud_tokens: int = 0
    local_tokens: int = 0
    gpu_tokens: int = 0
    tier_ms: dict[str, float] = {}  # ms per tier: local, mid, brief, top
    # Optional per-model split of this call. Old events lack it; readers fall back to local_tokens/cloud_tokens.
    per_tier: dict[TierKey, TierUsage] | None = None
    tier_name: str | None = None  # pool mode: the [[tiers]] name that answered (e.g. "gpu-large")
    # Shared-cache metrics. All optional: old events and old readers ignore them.
    gpu_calls_avoided: int | None = None  # defaults to 1 when a cache answered, else None
    false_hit: bool | None = None         # set by a caller that reports a served cache answer as wrong
    cache_lookup_ms: float | None = None

    @model_validator(mode="after")
    def _cache_avoids_gpu(self) -> "Telemetry":
        if self.gpu_calls_avoided is None and self.tier_used in ("exact_cache", "semantic_cache"):
            self.gpu_calls_avoided = 1
        return self


class TelemetryTracker:
    """Collects events, keeps totals, and forwards each event to optional sinks (e.g. HUD WebSocket)."""

    def __init__(self, sinks: list[Callable[[Telemetry], None]] | None = None) -> None:
        self.events: list[Telemetry] = []
        self._sinks = sinks or []
        self._lock = threading.Lock()

    def emit(self, event: Telemetry) -> None:
        with self._lock:
            self.events.append(event)
        for sink in self._sinks:
            sink(event)

    def totals(self) -> dict[str, float]:
        with self._lock:
            events = list(self.events)
        hits = sum(e.tier_used in ("exact_cache", "semantic_cache") for e in events)
        false_hits = sum(bool(e.false_hit) for e in events)
        alphas = [e.acceptance_rate_alpha for e in events if e.acceptance_rate_alpha is not None]
        return {
            "calls": len(events),
            "tokens_saved": sum(e.tokens_saved for e in events),
            "dollars_saved": sum(e.dollars_saved for e in events),
            "cloud_tokens": sum(e.cloud_tokens for e in events),
            "local_tokens": sum(e.local_tokens for e in events),
            "mean_alpha": sum(alphas) / len(alphas) if alphas else 0.0,
            "gpu_calls_avoided": sum(e.gpu_calls_avoided or 0 for e in events),
            "cache_hits": hits,
            "hit_rate": hits / len(events) if events else 0.0,
            "false_hits": false_hits,
            "false_hit_rate": false_hits / hits if hits else 0.0,
        }

    @staticmethod
    def jsonl_sink(path: str) -> Callable[[Telemetry], None]:
        def write(event: Telemetry) -> None:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.model_dump()) + "\n")

        return write
