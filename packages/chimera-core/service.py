"""Web API handlers: POST /api/chat (SSE), GET /api/health, GET /api/stats.

Framework-free. The single web server wires them in with one call:

    from chimera_core.service import handle_http          # inside do_GET / do_POST
    if handle_http(self, "GET"):  # or "POST"
        return

Everything goes through the same router the gateway uses (`config.build_router`), so both entry points
share one cache stack and one tier pool. Nothing here returns a key, a DSN or a hostname: outbound JSON is
scrubbed of every secret value found in the environment, and logs carry lengths, never prompt text.
"""
from __future__ import annotations

import concurrent.futures as cf
import copy
import json
import logging
import os
import pathlib
import queue
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Iterator

from .firewall.risk_scorer import score_action

log = logging.getLogger("chimera.service")
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|DB_URL|DSN)", re.I)
MAX_BODY = 16_384


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.retry_after = status, code, message, retry_after


def scrub(obj: Any) -> Any:
    """Replace every secret value from the environment inside any string of obj."""
    secrets = [v for k, v in os.environ.items() if SECRET_NAME.search(k) and len(v) >= 8]
    if not secrets:
        return obj
    if isinstance(obj, str):
        for s in secrets:
            obj = obj.replace(s, "[redacted]")
        return obj
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return obj


class IpLimiter:
    """Token bucket per client IP (the socket peer, never a header a client can set)."""

    def __init__(self, rate_per_min: float, burst: int, clock: Callable[[], float] = time.monotonic,
                 max_ips: int = 10_000) -> None:
        self.rate, self.burst, self._clock, self._max = rate_per_min / 60.0, float(burst), clock, max_ips
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def acquire(self, ip: str) -> float:
        """0.0 if allowed, else seconds to wait."""
        now = self._clock()
        with self._lock:
            tokens, last = self._state.get(ip, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if len(self._state) >= self._max and ip not in self._state:
                self._state.pop(next(iter(self._state)))
            if tokens >= 1:
                self._state[ip] = (tokens - 1, now)
                return 0.0
            self._state[ip] = (tokens, now)
            return (1 - tokens) / self.rate if self.rate > 0 else 60.0


def summarize(rows: list[dict]) -> dict:
    """Totals over telemetry rows (Telemetry.model_dump() dicts). Old rows without cache_source count as local."""
    n = len(rows)
    src = {"exact": 0, "local": 0, "shared": 0}
    tiers: dict[str, int] = {}
    for r in rows:
        tiers[r.get("tier_used", "?")] = tiers.get(r.get("tier_used", "?"), 0) + 1
        if r.get("tier_used") in ("exact_cache", "semantic_cache"):
            src[r.get("cache_source") or ("exact" if r["tier_used"] == "exact_cache" else "local")] += 1
    hits = sum(src.values())
    return {
        "calls": n, "cache_hits": src, "hit_rate": round(hits / n, 4) if n else 0.0,
        "gpu_calls_avoided": sum(r.get("gpu_calls_avoided") or 0 for r in rows),
        "big_calls_avoided": sum(r.get("tier_used") != "top" for r in rows),
        "dollars_saved": round(sum(r.get("dollars_saved") or 0 for r in rows), 6),
        "dollars_spent": round(sum(r.get("dollars_spent") or 0 for r in rows), 6),
        "tokens_kept_off_big": sum(r.get("tokens_saved") or 0 for r in rows),
        "false_hits": sum(bool(r.get("false_hit")) for r in rows), "by_tier": tiers,
    }


def _ram_mb() -> dict:
    try:
        if os.path.exists("/proc/meminfo"):
            m = {k: int(v.split()[0]) for k, v in (ln.split(":", 1) for ln in open("/proc/meminfo"))}
            return {"free_mb": m["MemAvailable"] // 1024, "total_mb": m["MemTotal"] // 1024}
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=3).stdout
        page = int(re.search(r"page size of (\d+)", out).group(1))
        pg = lambda k: int(re.search(rf"{k}:\s+(\d+)", out).group(1))  # noqa: E731
        free = (pg("Pages free") + pg("Pages inactive") + pg("Pages speculative")) * page // 2**20
        total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // 2**20
        return {"free_mb": free, "total_mb": total}
    except Exception:  # noqa: BLE001
        return {"free_mb": None, "total_mb": None}


def _modal_state() -> dict:
    """Read-only `modal app list`. Never deploys, starts or probes the app URL (that would wake the GPU)."""
    exe = shutil.which("modal") or str(pathlib.Path(__file__).resolve().parents[2] / ".venv/bin/modal")
    try:
        out = subprocess.run([exe, "app", "list"], capture_output=True, text=True, timeout=15).stdout
    except Exception:  # noqa: BLE001
        return {"state": "unknown"}
    line = next((ln for ln in out.splitlines() if "chimera-gpu-large" in ln), "")
    low = line.lower()
    state = ("stopped" if "stopped" in low else "deployed" if "deployed" in low else "ephemeral" if "ephemeral" in low
             else "not_deployed" if out.strip() else "unknown")
    return {"state": state}


def _http_probe(t) -> bool:
    from .tiers import http_probe
    return http_probe(t)


class Service:
    def __init__(self, router, cfg=None, *, tenant: str = "web", rate_per_min: float = 20, burst: int = 5,
                 max_chars: int = 2000, max_inflight: int = 16, timeout_s: float = 240,
                 telemetry_path: str | os.PathLike | None = None, probe: Callable[[Any], bool] | None = None,
                 modal_state: Callable[[], dict] = _modal_state, clock: Callable[[], float] = time.monotonic) -> None:
        self.cfg, self.max_chars, self.timeout_s, self._clock = cfg, max_chars, timeout_s, clock
        self.router = copy.copy(router)  # one tenant namespace; shares the backends and caches with the gateway
        self.router.cfg = router.cfg.model_copy(update={"namespace": tenant})
        self.limiter = IpLimiter(rate_per_min, burst, clock)
        self._slots = threading.BoundedSemaphore(max_inflight)
        self._pool = cf.ThreadPoolExecutor(max_workers=max_inflight, thread_name_prefix="chat")
        self._probe = probe or _http_probe
        self._modal_state = modal_state
        self._memo: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._telemetry = pathlib.Path(telemetry_path) if telemetry_path else (cfg.telemetry_path if cfg else None)
        self._rows: list[dict] = []  # this process only
        self._tps: tuple[float, float] | None = None  # (tokens/s, when)

    # ---- POST /api/chat ---------------------------------------------------------------------------
    def chat(self, body: dict, ip: str) -> Iterator[tuple[str, dict]]:
        """Validate, start the call, return a generator of (event, data): step events, `answer`, `done`.

        Errors found before streaming raise ApiError (the server turns them into JSON 4xx/5xx).
        """
        prompt = body.get("prompt") if isinstance(body, dict) else None
        if not isinstance(prompt, str) or not prompt.strip():
            raise ApiError(400, "invalid_request", 'Body must be JSON like {"prompt": "..."}.')
        if len(prompt) > self.max_chars:
            raise ApiError(413, "prompt_too_long", f"Prompt is over {self.max_chars} characters.")
        action = body.get("action")
        if action is not None:
            if not isinstance(action, str) or len(action) > 4096:
                raise ApiError(400, "invalid_request", '"action" must be a string of at most 4096 characters.')
            verdict = score_action(action)  # the firewall decides before anything acts on the text
            if verdict.needs_approval:
                raise ApiError(403, "approval_required", f"Risk {verdict.score}/100 ({', '.join(verdict.reasons)}). "
                               f"Held for approval; token {verdict.approval_token}.")
        wait = self.limiter.acquire(ip)
        if wait:
            raise ApiError(429, "rate_limited", "Too many requests from this address.", int(wait) + 1)
        if not self._slots.acquire(blocking=False):
            raise ApiError(503, "busy", "The server is busy. Try again in a moment.", 2)
        q: queue.Queue = queue.Queue()

        def work() -> None:
            try:
                res = self.router.generate(prompt, on_event=lambda s, d: q.put((s, d)))
                self._count(res.telemetry)
                q.put(("answer", {"text": res.text}))
            except Exception as e:  # noqa: BLE001  type name only: messages can carry URLs
                code = "all_tiers_failed" if type(e).__name__ == "AllTiersFailed" else "internal"
                log.error("chat failed: %s", type(e).__name__)
                q.put(("error", {"code": code, "message": "No tier could answer this request."}))
            finally:
                q.put(None)
                self._slots.release()

        self._pool.submit(work)
        return self._drain(q)

    def _drain(self, q: queue.Queue) -> Iterator[tuple[str, dict]]:
        deadline = self._clock() + self.timeout_s
        while True:
            try:
                item = q.get(timeout=max(deadline - self._clock(), 0.01))
            except queue.Empty:
                yield "error", {"code": "timeout", "message": "The backend did not answer in time."}
                break
            if item is None:
                break
            step, data = item
            if step == "call" and data.get("ok") and data.get("ms"):
                self._note_tps(data)
            yield step, scrub(data)
        yield "done", {}

    def _note_tps(self, d: dict) -> None:
        names = {t.name for t in (self.cfg.tiers if self.cfg else []) if t.backend == "llamacpp"}
        if d.get("tier") in names and d.get("tokens_out"):
            self._tps = (d["tokens_out"] / (d["ms"] / 1000), self._clock())

    def _count(self, tel) -> None:
        with self._lock:
            self._rows.append(tel.model_dump(exclude={"events", "per_tier"}))
            del self._rows[:-20_000]

    # ---- GET /api/stats ---------------------------------------------------------------------------
    def stats(self) -> dict:
        def build() -> dict:
            with self._lock:
                rows = list(self._rows)
            return {"session": summarize(rows), "global": summarize(self._read_global())}
        return self._cached("stats", 2.0, build)

    def _read_global(self, max_bytes: int = 20_000_000) -> list[dict]:
        p = self._telemetry
        if not p or not p.exists():
            return []
        with open(p, "rb") as fh:
            size = fh.seek(0, 2)
            fh.seek(max(size - max_bytes, 0))
            lines = fh.read().splitlines()
        rows = []
        for ln in lines[1:] if size > max_bytes else lines:
            try:
                rows.append(json.loads(ln))
            except ValueError:
                pass
        return rows

    # ---- GET /api/health --------------------------------------------------------------------------
    def health(self) -> dict:
        return self._cached("health", 2.0, self._health)

    def _cached(self, key: str, ttl: float, fn: Callable[[], Any]) -> Any:
        now = self._clock()
        with self._lock:
            hit = self._memo.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        val = fn()
        with self._lock:
            self._memo[key] = (self._clock(), val)
        return val

    def _health(self) -> dict:
        tiers = self.cfg.tiers if self.cfg else []
        by = lambda f: next((t for t in tiers if t.enabled and f(t)), None)  # noqa: E731
        llama = by(lambda t: t.backend == "llamacpp")
        gpu = by(lambda t: t.backend == "ollama")
        crusoe = by(lambda t: "crusoe" in t.url)
        gmi = by(lambda t: "gmi" in t.url)
        shared = getattr(self.router, "shared", None)
        jobs: dict[str, Callable[[], dict]] = {
            "ram": _ram_mb,
            "modal": lambda: self._cached("modal", 60.0, self._modal_state),
        }
        for name, t in (("llama", llama), ("gpu_tunnel", gpu), ("crusoe", crusoe), ("gmi", gmi)):
            if t is not None:
                jobs[name] = (lambda t=t: self._timed(t))
        if shared is not None:
            jobs["supabase"] = lambda: self._ping(shared)
        with cf.ThreadPoolExecutor(max_workers=len(jobs)) as ex:
            futs = {k: ex.submit(fn) for k, fn in jobs.items()}
            out = {k: f.result() for k, f in futs.items()}
        if llama is not None:
            out["llama"]["tokens_per_s"] = self._llama_tps(llama) if out["llama"]["up"] else None
        out["ts"] = int(time.time())
        out["ok"] = bool(out.get("llama", {}).get("up") or out.get("crusoe", {}).get("up"))
        return out

    def _timed(self, t) -> dict:
        t0 = time.perf_counter()
        up = self._probe(t)
        return {"up": up, "ms": round((time.perf_counter() - t0) * 1000, 1)}

    def _ping(self, shared) -> dict:
        try:
            return {"up": True, "lookup_ms": round(shared.ping(), 1)}
        except Exception:  # noqa: BLE001
            return {"up": False, "lookup_ms": None}

    def _llama_tps(self, t) -> float | None:
        """Tokens/s of the last real call, else a 16-token timing call at most once a minute."""
        if self._tps and self._clock() - self._tps[1] < 60:
            return round(self._tps[0], 1)
        try:
            from .inference.local_draft import LlamaCppBackend
            t0 = time.perf_counter()
            d = LlamaCppBackend(t.url, timeout=10).complete("Count: one, two, three, four, five, six", 16)
            self._tps = (d.n_tokens / (time.perf_counter() - t0), self._clock())
            return round(self._tps[0], 1)
        except Exception:  # noqa: BLE001
            return None


_default: Service | None = None
_default_lock = threading.Lock()


def default_service() -> Service:
    """The process-wide Service, built from chimera.toml on first use."""
    global _default
    with _default_lock:
        if _default is None:
            from .config import build_router, load_config
            from .inference.telemetry import TelemetryTracker

            cfg = load_config()
            tracker = TelemetryTracker([TelemetryTracker.jsonl_sink(str(cfg.telemetry_path))], keep=0)
            _default = Service(build_router(cfg, tracker=tracker), cfg)
        return _default


# ---- stdlib http.server glue ---------------------------------------------------------------------
def _send_json(h, code: int, obj: Any, extra: dict | None = None) -> None:
    body = json.dumps(scrub(obj)).encode()
    h.send_response(code)
    h.send_header("Content-Type", "application/json")
    h.send_header("Content-Length", str(len(body)))
    h.send_header("Cache-Control", "no-store")
    for k, v in (extra or {}).items():
        h.send_header(k, v)
    h.end_headers()
    h.wfile.write(body)


def handle_http(h, method: str, svc: Service | None = None) -> bool:
    """Serve /api/chat, /api/health, /api/stats on a BaseHTTPRequestHandler. False when the path is not ours."""
    path = h.path.split("?")[0]
    if path not in ("/api/chat", "/api/health", "/api/stats"):
        return False
    try:
        svc = svc or default_service()
        if path == "/api/chat":
            if method != "POST":
                raise ApiError(405, "method_not_allowed", "Use POST.")
            n = int(h.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_BODY:
                raise ApiError(413 if n else 400, "invalid_request", f"Body must be 1 to {MAX_BODY} bytes.")
            try:
                body = json.loads(h.rfile.read(n))
            except ValueError:
                raise ApiError(400, "invalid_request", "Body is not JSON.") from None
            events = svc.chat(body, h.client_address[0])
            h.send_response(200)
            for k, v in (("Content-Type", "text/event-stream"), ("Cache-Control", "no-store"),
                         ("X-Accel-Buffering", "no")):
                h.send_header(k, v)
            h.end_headers()
            try:
                for step, data in events:
                    h.wfile.write(f"event: {step}\ndata: {json.dumps(data)}\n\n".encode())
                    h.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                events.close()
        else:
            if method != "GET":
                raise ApiError(405, "method_not_allowed", "Use GET.")
            _send_json(h, 200, svc.health() if path == "/api/health" else svc.stats())
    except ApiError as e:
        _send_json(h, e.status, {"error": {"code": e.code, "message": e.message}},
                   {"Retry-After": str(e.retry_after)} if e.retry_after else None)
    return True
