"""Structured telemetry emitted for every LLM call."""
from __future__ import annotations

import json
import threading
from typing import Callable, Literal

from pydantic import BaseModel, Field

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
    # Optional per-model split of this call. Old events lack it; readers fall back to local_tokens/cloud_tokens.
    per_tier: dict[TierKey, TierUsage] | None = None


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
        alphas = [e.acceptance_rate_alpha for e in events if e.acceptance_rate_alpha is not None]
        return {
            "calls": len(events),
            "tokens_saved": sum(e.tokens_saved for e in events),
            "dollars_saved": sum(e.dollars_saved for e in events),
            "cloud_tokens": sum(e.cloud_tokens for e in events),
            "local_tokens": sum(e.local_tokens for e in events),
            "mean_alpha": sum(alphas) / len(alphas) if alphas else 0.0,
        }

    @staticmethod
    def jsonl_sink(path: str) -> Callable[[Telemetry], None]:
        def write(event: Telemetry) -> None:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.model_dump()) + "\n")

        return write
