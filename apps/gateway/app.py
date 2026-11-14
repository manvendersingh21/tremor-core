"""FastAPI app: OpenAI-compatible chat API in front of a LadderRouter, with per-tenant keys and caches."""
from __future__ import annotations

import asyncio
import copy
import hmac
import json
import logging
import os
import re
import time
import urllib.request
import uuid
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from chimera_core.config import ChimeraConfig, tier_checks
from chimera_core.firewall.risk_scorer import score_action

from .limits import RateLimiter
from .metrics import Metrics
from .resilient import FALLBACKS
from .store import AuditLog, Key, KeyStore

log = logging.getLogger("chimera.gateway")
MODELS = ["chimera-auto", "chimera-local", "chimera-gpu", "chimera-top"]
_RID = re.compile(r"^[\w.-]{1,64}$")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None) -> None:
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


class Message(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: str
    content: str | list[dict] | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")  # temperature, max_tokens, ... are accepted and ignored
    model: str = "chimera-auto"
    messages: list[Message]
    stream: bool = False


def _text(content) -> str:
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if p.get("type") == "text")
    return content or ""


def to_prompt(messages: list[Message]) -> str:
    """A lone user message goes through unchanged (best cache hit rate); anything else becomes a transcript."""
    if len(messages) == 1 and messages[0].role == "user":
        return _text(messages[0].content)
    return "\n".join(f"{m.role}: {_text(m.content)}" for m in messages) + "\nassistant:"


def _sse(obj: dict | str) -> bytes:
    return f"data: {obj if isinstance(obj, str) else json.dumps(obj)}\n\n".encode()


def _probe(check: tuple) -> bool:
    name, _base, url, headers = check
    if name == "crusoe" and not headers:
        return False
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=3):  # noqa: S310
            return True
    except Exception:  # noqa: BLE001
        return False


def create_app(cfg: ChimeraConfig, router, keys: KeyStore, audit: AuditLog, *,
               probe: Callable[[tuple], bool] = _probe, clock: Callable[[], float] = time.monotonic) -> FastAPI:
    g = cfg.gateway
    app = FastAPI(title="CHIMERA gateway", docs_url=None, redoc_url=None, openapi_url=None)
    metrics = Metrics()
    limiter = RateLimiter(g.rate_per_min, g.burst, clock)
    routers: dict[str, object] = {}
    ready_cache: tuple[float, dict] = (-1e9, {})

    def tenant_router(tenant: str):
        r = routers.get(tenant)
        if r is None:  # shares backends and caches; only the cache namespace differs
            r = copy.copy(router)
            r.cfg = router.cfg.model_copy(update={"namespace": tenant})
            routers[tenant] = r
        return r

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, e: ApiError):
        metrics.event("errors", getattr(request.state, "tenant", "-"), e.code)
        kind = "invalid_request_error" if e.status < 500 else "api_error"
        return JSONResponse({"error": {"message": e.message, "type": kind, "code": e.code}},
                            status_code=e.status, headers=e.headers)

    @app.middleware("http")
    async def _request(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")
        request.state.rid = rid if _RID.match(rid) else uuid.uuid4().hex[:16]
        request.state.tenant, request.state.tier, request.state.prompt = "-", "-", None
        t0 = time.perf_counter()
        try:
            resp = await call_next(request)
        except Exception as e:  # noqa: BLE001
            log.error("unhandled", extra={"fields": {"request_id": request.state.rid, "error": type(e).__name__}})
            resp = JSONResponse({"error": {"message": "internal error", "type": "api_error", "code": "internal"}},
                                status_code=500)
        resp.headers["x-request-id"] = request.state.rid
        fields = {"request_id": request.state.rid, "method": request.method, "path": request.url.path,
                  "status": resp.status_code, "tenant": request.state.tenant, "tier": request.state.tier,
                  "ms": round((time.perf_counter() - t0) * 1000, 1)}
        if g.log_prompts and request.state.prompt is not None:
            fields["prompt"] = request.state.prompt
        log.info("request", extra={"fields": fields})
        return resp

    def authed(request: Request) -> Key:
        h = request.headers.get("authorization", "")
        scheme, _, tok = h.partition(" ")
        key = keys.lookup(tok.strip()) if scheme.lower() == "bearer" and tok.strip() else None
        if key is None:
            raise ApiError(401, "invalid_api_key", "Missing, invalid or revoked API key.",
                           {"www-authenticate": "Bearer"})
        request.state.tenant = key.tenant
        wait = limiter.acquire(key.id)
        if wait:
            metrics.event("rate_limited", key.tenant)
            raise ApiError(429, "rate_limit_exceeded", "Rate limit exceeded.", {"retry-after": str(int(wait) + 1)})
        return key

    async def read_body(request: Request) -> bytes:
        if int(request.headers.get("content-length") or 0) > g.max_body_bytes:
            raise ApiError(413, "request_too_large", f"Body over {g.max_body_bytes} bytes.")
        buf = bytearray()
        async for chunk in request.stream():
            buf += chunk
            if len(buf) > g.max_body_bytes:
                raise ApiError(413, "request_too_large", f"Body over {g.max_body_bytes} bytes.")
        return bytes(buf)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz():
        nonlocal ready_cache
        if clock() - ready_cache[0] > 5:  # probes are slow when a tier is down; reuse for 5 s
            checks = tier_checks(cfg)
            oks = await asyncio.gather(*[run_in_threadpool(probe, c) for c in checks])
            ready_cache = (clock(), {c[0]: ok for c, ok in zip(checks, oks)})
        tiers = ready_cache[1]
        ready = any(tiers.values())  # caches still answer with every tier down, but that is not ready
        return JSONResponse({"ready": ready, "tiers": tiers}, status_code=200 if ready else 503)

    @app.get("/metrics")
    async def metrics_endpoint(request: Request):
        token = os.environ.get("CHIMERA_METRICS_TOKEN", "")
        if token and not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {token}"):
            raise ApiError(401, "invalid_api_key", "Metrics token required.")
        return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    @app.get("/v1/models")
    async def models(request: Request):
        authed(request)
        return {"object": "list", "data": [
            {"id": m, "object": "model", "created": 0, "owned_by": "chimera"} for m in MODELS]}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        key = authed(request)
        raw = await read_body(request)
        try:
            req = ChatRequest.model_validate(json.loads(raw))
        except (ValueError, ValidationError):
            raise ApiError(400, "invalid_request", "Body must be JSON with a non-empty messages list.") from None
        if req.model not in MODELS:
            raise ApiError(404, "model_not_found", f"Unknown model. Use one of: {', '.join(MODELS)}.")
        prompt = to_prompt(req.messages) if req.messages else ""
        if not prompt.strip():
            raise ApiError(400, "invalid_request", "Messages contain no text.")
        request.state.prompt = prompt
        rid, tenant = request.state.rid, key.tenant

        def work():
            fb: list = []
            token = FALLBACKS.set(fb)
            try:
                return tenant_router(tenant).generate(prompt), fb
            finally:
                FALLBACKS.reset(token)

        try:
            res, fb = await asyncio.wait_for(run_in_threadpool(work), timeout=2 * g.timeout_s)
        except asyncio.TimeoutError:
            raise ApiError(504, "timeout", "The backend did not answer in time.") from None
        except Exception as e:  # noqa: BLE001
            log.error("backend_error", extra={"fields": {"request_id": rid, "error": type(e).__name__}})
            raise ApiError(502, "upstream_error", "All backends failed for this request.") from None

        tel = res.telemetry
        if fb:  # report the tier that really answered
            tel = tel.model_copy(update={"tier_used": fb[-1][1]})
            metrics.event("fallbacks", tenant, f"{fb[-1][0]}->{fb[-1][1]}")
        request.state.tier = tel.tier_used
        metrics.observe(tenant, tel.tier_used, tel.tokens_saved, tel.dollars_saved, tel.latency_ms)
        audit.record(rid, tenant, tel)
        usage = {"prompt_tokens": max(len(prompt) // 4, 1), "completion_tokens": len(res.text) // 4}
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]  # estimates, len/4
        extra = {**tel.model_dump(), "request_id": rid, "fallback_from": fb[-1][0] if fb else None}
        headers = {"x-chimera-tier": tel.tier_used, "x-chimera-tokens-saved": str(tel.tokens_saved),
                   "x-chimera-latency-ms": f"{tel.latency_ms:.1f}"}
        cid, created = f"chatcmpl-{rid}", int(time.time())

        if not req.stream:
            return JSONResponse({
                "id": cid, "object": "chat.completion", "created": created, "model": "chimera-auto",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": res.text},
                             "finish_reason": "stop"}],
                "usage": usage, "chimera": extra}, headers=headers)

        def chunk(delta: dict, finish=None, **more) -> bytes:
            return _sse({"id": cid, "object": "chat.completion.chunk", "created": created, "model": "chimera-auto",
                         "choices": [{"index": 0, "delta": delta, "finish_reason": finish}], **more})

        async def events():
            # shortcut: the router answers whole, so this replays the finished text in pieces; upgrade when a tier streams.
            yield chunk({"role": "assistant", "content": ""})
            for piece in re.findall(r"\S+\s*|\s+", res.text):
                yield chunk({"content": piece})
            yield chunk({}, "stop", usage=usage, chimera=extra)
            yield _sse("[DONE]")

        return StreamingResponse(events(), media_type="text/event-stream", headers=headers)

    if g.actions:
        @app.post("/v1/actions/score")
        async def score(request: Request):
            authed(request)
            try:
                action = json.loads(await read_body(request))["action"]
                assert isinstance(action, str) and 0 < len(action) <= 4096
            except (ValueError, KeyError, TypeError, AssertionError):
                raise ApiError(400, "invalid_request", 'Body must be {"action": "<1-4096 chars>"}.') from None
            return score_action(action).model_dump()

    return app
