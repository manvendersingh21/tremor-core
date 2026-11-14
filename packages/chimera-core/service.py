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


CACHE_TIERS = ("exact_cache", "semantic_cache")
OUR_TABLES = ("prompts", "cache_events", "routing_signals", "eval_runs", "teacher_pairs", "mem_nodes", "mem_edges")
ID_RE = re.compile(r"^[\w.:-]{1,64}$")  # conversation_id and task: plain ids only


def _tokens(r: dict) -> int:
    return (r.get("tokens_in") or 0) + (r.get("tokens_out") or 0)


def _cache_split(rows: list[dict]) -> dict:
    """Cache answers split by how they matched: exact hash or cosine. false_hits = cache answers reported wrong."""
    return {"exact": sum(r.get("tier_used") == "exact_cache" for r in rows),
            "cosine": sum(r.get("tier_used") == "semantic_cache" for r in rows),
            "false_hits": sum(bool(r.get("false_hit")) for r in rows)}


def _group(rows: list[dict], key: str, default: str | None, limit: int) -> dict:
    out: dict[str, dict] = {}
    for r in rows:
        k = r.get(key) or default
        if k is None:
            continue
        g = out.setdefault(k, {"calls": 0, "tokens": 0, "cache_hits": 0, "tokens_saved": 0, "dollars_saved": 0.0,
                               "last_ts": None})
        g["calls"] += 1
        g["tokens"] += _tokens(r)
        g["cache_hits"] += r.get("tier_used") in CACHE_TIERS
        g["tokens_saved"] += r.get("tokens_saved") or 0
        g["dollars_saved"] = round(g["dollars_saved"] + (r.get("dollars_saved") or 0), 6)
        g["last_ts"] = r.get("ts") or g["last_ts"]
    newest = sorted(out, key=lambda k: out[k]["last_ts"] or 0, reverse=True)[:limit]
    return {k: out[k] for k in newest}


def _series(rows: list[dict], fmt: str, start: float) -> list[dict]:
    """Calls, tokens and dollars saved per bucket (local time), oldest first. Rows with no ts are left out."""
    b: dict[str, dict] = {}
    for r in rows:
        ts = r.get("ts")
        if not ts or ts < start:
            continue
        t = time.strftime(fmt, time.localtime(ts))
        x = b.setdefault(t, {"t": t, "calls": 0, "tokens": 0, "tokens_saved": 0, "dollars_saved": 0.0,
                             "dollars_spent": 0.0})
        x["calls"] += 1
        x["tokens"] += _tokens(r)
        x["tokens_saved"] += r.get("tokens_saved") or 0
        x["dollars_saved"] = round(x["dollars_saved"] + (r.get("dollars_saved") or 0), 6)
        x["dollars_spent"] = round(x["dollars_spent"] + (r.get("dollars_spent") or 0), 6)
    return [b[k] for k in sorted(b)]


def recent_calls(rows: list[dict], n: int = 20) -> list[dict]:
    """The last n calls, newest first, each with its step trace. Prompt text is a scrubbed 80-character preview."""
    out = []
    for r in reversed(rows[-n:]):
        steps = r.get("events") or []
        sh = next((e for e in steps if e.get("step") == "cache_shared"), {})
        fin = next((e for e in steps if e.get("step") == "final"), {})
        out.append({"ts": r.get("ts"), "prompt": r.get("prompt_preview") or "", "task": r.get("task"),
                    "conversation_id": r.get("conversation_id"), "tier": r.get("tier_name") or r.get("tier_used"),
                    "model": fin.get("model") or "", "cache": r.get("cache_source"), "score": sh.get("score"),
                    "tokens_in": r.get("tokens_in") or 0, "tokens_out": r.get("tokens_out") or 0,
                    "ms": round(r.get("latency_ms") or 0, 1), "dollars": r.get("dollars_spent") or 0.0,
                    "dollars_saved": r.get("dollars_saved") or 0.0, "steps": steps})
    return out


def summarize(rows: list[dict], now: float | None = None) -> dict:
    """Totals over telemetry rows (Telemetry.model_dump() dicts). Old rows without cache_source count as local."""
    now = time.time() if now is None else now
    lt = time.localtime(now)
    midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    today = [r for r in rows if (r.get("ts") or 0) >= midnight]
    n = len(rows)
    src = {"exact": 0, "local": 0, "shared": 0}
    tiers: dict[str, int] = {}
    for r in rows:
        tiers[r.get("tier_used", "?")] = tiers.get(r.get("tier_used", "?"), 0) + 1
        if r.get("tier_used") in CACHE_TIERS:
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
        "tokens": sum(_tokens(r) for r in rows), "tokens_today": sum(_tokens(r) for r in today),
        "calls_today": len(today),
        "cache": {"today": _cache_split(today), "all_time": _cache_split(rows)},
        "by_task": _group(rows, "task", "other", 50),
        "by_conversation": _group(rows, "conversation_id", None, 50),
        "series": {"hourly": _series(rows, "%Y-%m-%dT%H:00", now - 48 * 3600),
                   "daily": _series(rows, "%Y-%m-%d", now - 30 * 86400)},
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
        apps = json.loads(subprocess.run([exe, "app", "list", "--json"], capture_output=True, text=True,
                                         timeout=15).stdout)
    except Exception:  # noqa: BLE001
        return {"state": "unknown"}
    return {"state": modal_state_of(apps)}


def modal_state_of(apps: list[dict]) -> str:
    """State of the newest chimera-gpu-large app in `modal app list --json` output."""
    mine = sorted((a for a in apps if a.get("description") == "chimera-gpu-large"),
                  key=lambda a: a.get("created_at", ""), reverse=True)
    if not mine:
        return "not_deployed"
    st = str(mine[0].get("state", "")).lower()
    return st if st in ("stopped", "deployed", "ephemeral") else "unknown"


def _http_probe(t) -> bool:
    from .tiers import http_probe
    return http_probe(t)


class Service:
    def __init__(self, router, cfg=None, *, tenant: str = "web", rate_per_min: float = 20, burst: int = 5,
                 max_chars: int = 2000, max_inflight: int = 32, timeout_s: float = 240,
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
        tags = {}
        for k in ("conversation_id", "task"):
            v = body.get(k)
            if v is not None and not (isinstance(v, str) and ID_RE.match(v)):
                raise ApiError(400, "invalid_request", f'"{k}" must be 1-64 letters, digits, ".", "_", ":" or "-".')
            tags[k] = v
        wait = self.limiter.acquire(ip)
        if wait:
            raise ApiError(429, "rate_limited", "Too many requests from this address.", int(wait) + 1)
        if not self._slots.acquire(blocking=False):
            raise ApiError(503, "busy", "The server is busy. Try again in a moment.", 2)
        q: queue.Queue = queue.Queue()

        def work() -> None:
            try:
                res = self.router.generate(prompt, on_event=lambda s, d: q.put((s, d)), task=tags["task"] or "chat",
                                           conversation_id=tags["conversation_id"])
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
            self._rows.append(tel.model_dump(exclude={"per_tier"}))
            del self._rows[:-5_000]  # rows carry their step traces; keep memory bounded
            self._memo.pop("stats", None)  # the next /api/stats shows this call at once

    # ---- GET /api/stats ---------------------------------------------------------------------------
    def stats(self) -> dict:
        def build() -> dict:
            with self._lock:
                rows = list(self._rows)
            glob = self._read_global()
            return {"session": summarize(rows), "global": summarize(glob), "recent": recent_calls(glob or rows),
                    "storage": self.storage()}
        return self._cached("stats", 2.0, build)

    # ---- storage counts (cached 60 s) -----------------------------------------------------------------
    def storage(self) -> dict:
        return self._cached("storage", 60.0, self._storage)

    def _storage(self) -> dict:
        jobs = {"supabase": self._supabase_sizes, "neo4j": self._neo4j_counts}
        with cf.ThreadPoolExecutor(max_workers=2) as ex:
            futs = {k: ex.submit(fn) for k, fn in jobs.items()}
            out = {}
            for k, f in futs.items():
                try:
                    out[k] = {"up": True, **f.result(timeout=8)}
                except Exception as e:  # noqa: BLE001  counts are optional; never fail /api/stats
                    out[k] = {"up": False, "error": type(e).__name__}
        out["ts"] = int(time.time())
        return out

    def _supabase_sizes(self) -> dict:
        """Rows and bytes of the tables this project created (deploy/sql/001-005). Counts only, no text."""
        shared = getattr(self.router, "shared", None)
        if shared is None:
            raise RuntimeError("no shared cache")
        st = shared._store_ready()
        tenant = shared.tenant
        tables = {}
        for t in OUR_TABLES:
            rows = st._tx(tenant, f"select count(*), pg_total_relation_size('{t}'::regclass), "  # noqa: S608 fixed names
                                  f"(select reltuples::bigint from pg_class where oid = '{t}'::regclass) from {t}",
                          (), "one")
            tables[t] = {"tenant_rows": rows[0], "bytes": rows[1], "rows_estimate": max(rows[2], 0)}
        return {"tenant": tenant, "tables": tables,
                "bytes_total": sum(v["bytes"] for v in tables.values())}

    def _neo4j_counts(self) -> dict:
        from .memory.neo4j_store import Neo4jGraphStore
        g = getattr(getattr(self.router, "memory", None), "graph", None)
        if not isinstance(g, Neo4jGraphStore):
            g = self._neo4j = getattr(self, "_neo4j", None) or Neo4jGraphStore()
        nodes = g._run("MATCH (n:Mem) RETURN count(n) AS c")[0]["c"]
        edges = g._run("MATCH (:Mem)-[r]->() RETURN count(r) AS c")[0]["c"]
        return {"nodes": nodes, "edges": edges}

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
            threading.Thread(target=_warm, args=(_default.router,), daemon=True).start()
        return _default


def _warm(router) -> None:
    """Load the embedder and open the DB pool off the request path (the first embed took ~6 s, the first lookup > 300 ms)."""
    try:
        if router.embedder is not None:
            router.embedder.embed("warm up")
        if router.shared is not None:
            router.shared.ping()
    except Exception as e:  # noqa: BLE001
        log.warning("warm-up failed: %s", type(e).__name__)


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


def evals() -> dict:
    """The eval log (bench/evallog.py: every benchmark run, SQLite log plus Supabase eval_runs)."""
    import sys
    bench = str(pathlib.Path(__file__).resolve().parents[2] / "bench")
    if bench not in sys.path:
        sys.path.insert(0, bench)
    import evallog  # noqa: PLC0415
    try:
        return evallog.api_payload(evallog.load_rows())
    except Exception as e:  # noqa: BLE001  a bad log must not kill the page
        raise ApiError(500, "evals_unavailable", type(e).__name__) from None


def handle_http(h, method: str, svc: Service | None = None) -> bool:
    """Serve /api/chat, /api/health, /api/stats, /api/evals on a BaseHTTPRequestHandler. False when the path is not ours."""
    path = h.path.split("?")[0]
    if path not in ("/api/chat", "/api/health", "/api/stats", "/api/evals"):
        return False
    try:
        if path == "/api/evals":
            if method != "GET":
                raise ApiError(405, "method_not_allowed", "Use GET.")
            _send_json(h, 200, evals())
            return True
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
            _send_json(h, 200, evals() if path == "/api/evals" else svc.health() if path == "/api/health" else svc.stats())
    except ApiError as e:
        _send_json(h, e.status, {"error": {"code": e.code, "message": e.message}},
                   {"Retry-After": str(e.retry_after)} if e.retry_after else None)
    return True
