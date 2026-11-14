"""Build the production gateway from chimera.toml and run it under uvicorn."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from chimera_core.config import ChimeraConfig, build_router, load_config
from chimera_core.inference.telemetry import Telemetry, TelemetryTracker

from .app import create_app
from .resilient import Resilient
from .store import AuditLog, KeyStore


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname,
                           "event": record.getMessage(), **getattr(record, "fields", {})})


class ServiceTracker(TelemetryTracker):
    """TelemetryTracker keeps every event in memory; a long-running service must not."""

    def emit(self, event: Telemetry) -> None:
        for sink in self._sinks:
            sink(event)


def make_app(cfg: ChimeraConfig):
    g = cfg.gateway
    router = build_router(cfg, tracker=ServiceTracker([TelemetryTracker.jsonl_sink(str(cfg.telemetry_path))]))
    if router.pool is None:  # pool mode (use_pool) has no mid/top; TierPool already falls through on errors
        for b in (router.local, router.mid, router.top):
            if hasattr(b, "timeout"):
                b.timeout = g.timeout_s
        raw_mid, local, cap = router.mid, router.local, router.cfg.max_local_tokens
        router.mid = Resilient(raw_mid, lambda p, n: local.complete(p, min(n, cap)).text, "gpu", "local",
                               g.retry_backoff_s)
        router.top = Resilient(router.top, raw_mid.complete, "top", "gpu", g.retry_backoff_s)
    return create_app(cfg, router, KeyStore(str(cfg.gateway_db)), AuditLog(str(cfg.gateway_db)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="chimera-gateway")
    ap.add_argument("--config")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8088)
    ap.add_argument("--log-prompts", action="store_true", help="include prompt text in request logs")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    if args.log_prompts:
        cfg.gateway.log_prompts = True
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    logging.getLogger("chimera.gateway").addHandler(h)
    logging.getLogger("chimera.gateway").setLevel(logging.INFO)
    import uvicorn

    uvicorn.run(make_app(cfg), host=args.host, port=args.port, access_log=False)
    return 0
