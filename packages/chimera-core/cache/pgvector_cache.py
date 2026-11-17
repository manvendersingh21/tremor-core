"""Shared semantic cache in Postgres + pgvector (plain Postgres or Supabase).

Same interface as SemanticCache (`get`, `put`, `purge`). Lookup order: exact hash, then nearest
neighbour by cosine distance. Only `verified` rows are served. The DB is never allowed to block a call:
every DB step runs under a short budget, and on error or timeout the local SQLite cache answers instead.
Run deploy/sql/*.sql first. The DSN comes from the environment only.
"""
from __future__ import annotations

import concurrent.futures as cf
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .exact_cache import prompt_hash
from .semantic_cache import Embedder, Lookup, SemanticCache, _norm

log = logging.getLogger("chimera.pgvector")


@dataclass
class Hit:
    id: int | None
    response: str
    similarity: float
    source: str  # "exact" | "vector" | "sqlite"


class Store(Protocol):
    def lookup(self, tenant: str, ns: str, h: str, emb: list[float], k: int
               ) -> tuple[tuple[int, str] | None, list[tuple]]: ...  # rows: (id, answer, sim, verified[, prompt_text])
    def insert(self, tenant: str, ns: str, h: str, text: str | None, emb: list[float], answer: str,
               meta: dict[str, Any]) -> int: ...
    def touch(self, tenant: str, prompt_id: int) -> None: ...
    def event(self, tenant: str, kind: str, prompt_id: int | None, similarity: float | None,
              lookup_ms: float | None) -> None: ...
    def signal(self, tenant: str, prompt_id: int, sig: dict[str, Any]) -> None: ...
    def set_verified(self, tenant: str, prompt_id: int, verified: bool) -> None: ...
    def purge(self, tenant: str, ns: str | None) -> int: ...


def _vec(emb: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in emb) + "]"


class PgStore:
    """psycopg v3 + a small pool. Each operation is one transaction that first sets `app.tenant` for RLS."""

    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 4) -> None:
        from psycopg_pool import ConnectionPool  # lazy: optional `postgres` extra

        self._pool = ConnectionPool(dsn, min_size=min_size, max_size=max_size, open=False,
                                    timeout=0.5, kwargs={"connect_timeout": 2})
        self._pool.open(wait=False)

    def _tx(self, tenant: str, sql: str, params: tuple = (), fetch: str = "") -> Any:
        with self._pool.connection() as conn:  # commits on exit
            conn.execute("select set_config('app.tenant', %s, true)", (tenant,))
            cur = conn.execute(sql, params)
            return cur.fetchone() if fetch == "one" else cur.fetchall() if fetch == "all" else cur.rowcount

    def lookup(self, tenant, ns, h, emb, k):
        """Exact row and top-k neighbours in ONE round trip (pipeline mode): the DB is far, round trips cost."""
        v = _vec(emb)
        live = "(ttl_s is null or created_at + ttl_s * interval '1 second' > now())"
        with self._pool.connection() as conn:
            with conn.pipeline():
                conn.execute("select set_config('app.tenant', %s, true)", (tenant,))
                c1 = conn.execute(f"select id, answer from prompts where tenant=%s and namespace=%s "
                                  f"and prompt_hash=%s and verified and {live}", (tenant, ns, h))
                c2 = conn.execute(f"select id, answer, 1 - (embedding <=> %s::vector), verified, prompt_text from prompts "
                                  f"where tenant=%s and namespace=%s and {live} "
                                  f"order by embedding <=> %s::vector limit %s", (v, tenant, ns, v, k))
            r = c1.fetchone()
            rows = c2.fetchall()
        return ((r[0], r[1]) if r else None), [(x[0], x[1], float(x[2]), bool(x[3]), x[4]) for x in rows]

    def find_exact(self, tenant, ns, h):
        r = self._tx(tenant, "select id, answer from prompts where tenant=%s and namespace=%s and prompt_hash=%s "
                     "and verified and (ttl_s is null or created_at + ttl_s * interval '1 second' > now())",
                     (tenant, ns, h), "one")
        return (r[0], r[1]) if r else None

    def find_nearest(self, tenant, ns, emb, k):
        v = _vec(emb)
        rows = self._tx(tenant, "select id, answer, 1 - (embedding <=> %s::vector) as sim, verified from prompts "
                        "where tenant=%s and namespace=%s "
                        "and (ttl_s is null or created_at + ttl_s * interval '1 second' > now()) "
                        "order by embedding <=> %s::vector limit %s", (v, tenant, ns, v, k), "all")
        return [(r[0], r[1], float(r[2]), bool(r[3])) for r in rows]

    def insert(self, tenant, ns, h, text, emb, answer, meta):
        r = self._tx(
            tenant,
            "insert into prompts (tenant, namespace, prompt_hash, prompt_text, embedding, answer, model, tier, "
            "tokens_in, tokens_out, verified, ttl_s) values (%s,%s,%s,%s,%s::vector,%s,%s,%s,%s,%s,%s,%s) "
            "on conflict (tenant, namespace, prompt_hash) do update set answer=excluded.answer, "
            "embedding=excluded.embedding, prompt_text=excluded.prompt_text, model=excluded.model, "
            "tier=excluded.tier, tokens_in=excluded.tokens_in, tokens_out=excluded.tokens_out, "
            "verified=excluded.verified, ttl_s=excluded.ttl_s, created_at=now() returning id",
            (tenant, ns, h, text, _vec(emb), answer, meta.get("model", ""), meta.get("tier", ""),
             meta.get("tokens_in", 0), meta.get("tokens_out", 0), meta.get("verified", True), meta.get("ttl_s")),
            "one")
        return r[0]

    def touch(self, tenant, prompt_id):
        self._tx(tenant, "update prompts set hits=hits+1, last_hit_at=now() where id=%s", (prompt_id,))

    def event(self, tenant, kind, prompt_id, similarity, lookup_ms):
        self._tx(tenant, "insert into cache_events (tenant, kind, prompt_id, similarity, lookup_ms) "
                 "values (%s,%s,%s,%s,%s)", (tenant, kind, prompt_id, similarity, lookup_ms))

    def signal(self, tenant, prompt_id, sig):
        self._tx(tenant, "insert into routing_signals (prompt_id, tenant, tier_tried, confidence, escalated, "
                 "passed_checks, latency_ms, cost) values (%s,%s,%s,%s,%s,%s,%s,%s)",
                 (prompt_id, tenant, sig["tier_tried"], sig.get("confidence"), sig.get("escalated", False),
                  sig.get("passed_checks"), sig.get("latency_ms"), sig.get("cost")))

    def set_verified(self, tenant, prompt_id, verified):
        self._tx(tenant, "update prompts set verified=%s where id=%s", (verified, prompt_id))

    def purge(self, tenant, ns):
        if ns is None:
            return self._tx(tenant, "delete from prompts where tenant=%s", (tenant,))
        return self._tx(tenant, "delete from prompts where tenant=%s and namespace=%s", (tenant, ns))


class PgVectorCache:
    def __init__(
        self, embedder: Embedder, store: Store | Callable[[], Store], *, threshold: float = 0.97,
        tenant: str = "default", fallback: SemanticCache | None = None, store_text: bool = False, guard=None,
        ttl_s: int | None = None, top_k: int = 5, budget_s: float = 0.3, cooldown_s: float = 30.0,
        max_strikes: int = 3, normalize: bool = False, band_low: float = 0.0, checker=None,
    ) -> None:
        self._embedder, self.threshold, self.tenant = embedder, threshold, tenant
        self.guard = guard  # (query, cached_prompt, sim) -> accept; only judges rows stored with prompt text
        self.guarded_out = 0
        # Paraphrases (cache/band.py, bench/results_paraphrase_cache.md). normalize: also compare the normalized
        # prompts ("tell me ..." vs "what is ..."). band_low > 0: a score in [band_low, threshold) is served only if
        # the guard passes and checker(new, old, answer) -> (ok, info) says yes. Needs rows stored with prompt text.
        self.normalize, self.band_low, self.checker = normalize, band_low, checker
        self._store_arg = store  # a callable is built lazily on first use, so a dead DB cannot block startup
        self._store: Store | None = None if callable(store) else store
        self.fallback, self.store_text, self.ttl_s, self.top_k = fallback, store_text, ttl_s, top_k
        self.budget_s, self.cooldown_s, self.max_strikes = budget_s, cooldown_s, max_strikes
        self._down_until = 0.0
        self._strikes = 0
        self._lock = threading.Lock()
        self._pool = cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="pgcache")
        self._wpool = cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="pgcache-w")  # writes never queue lookups
        self.stats = {"hits": 0, "misses": 0, "false_hits": 0, "fallbacks": 0, "lookup_ms": []}

    # ---- DB access under a budget ------------------------------------------------
    def _call(self, fn: Callable[[Store], Any]) -> Any:
        """Run fn(store) with the time budget. Raises on timeout or error and opens the circuit breaker."""
        if time.monotonic() < self._down_until:
            raise TimeoutError("db circuit open")

        def run() -> Any:
            with self._lock:
                if self._store is None:
                    self._store = self._store_arg()  # type: ignore[operator]
            return fn(self._store)

        try:
            out = self._pool.submit(run).result(timeout=self.budget_s)
            self._strikes = 0
            return out
        except Exception as e:  # noqa: BLE001  (timeout or any driver error; never log the DSN)
            self._strikes += 1
            if self._strikes >= self.max_strikes:  # one slow lookup is not an outage
                self._down_until = time.monotonic() + self.cooldown_s
            log.warning("pgvector cache unavailable, skipping the cache for this call: %s", type(e).__name__)
            raise

    def _bg(self, fn: Callable[[Store], Any]) -> None:
        """Fire and forget: writes never delay the caller."""
        if time.monotonic() < self._down_until:
            return

        def run() -> None:
            try:
                with self._lock:
                    if self._store is None:
                        self._store = self._store_arg()  # type: ignore[operator]
                fn(self._store)
            except Exception as e:  # noqa: BLE001
                self._down_until = time.monotonic() + self.cooldown_s
                log.warning("pgvector write failed: %s", type(e).__name__)

        self._wpool.submit(run)

    # ---- SemanticCache interface -------------------------------------------------
    def get_hit(self, prompt: str, namespace: str = "") -> Hit | None:
        return self._lookup(prompt, namespace)[0]

    def lookup(self, prompt: str, namespace: str = "") -> Lookup:
        """Like get(), plus the best cosine, the guard verdict and the DB status, for step events."""
        return self._lookup(prompt, namespace)[1]

    def _lookup(self, prompt: str, namespace: str) -> tuple[Hit | None, Lookup]:
        t0 = time.perf_counter()
        h = prompt_hash(prompt, namespace)
        emb = _norm(self._embedder.embed(prompt))
        info = {"best": None, "guard": "off" if self.guard is None else None, "check": None, "via": None}

        def lookup(s: Store) -> Hit | list:
            ex, near = s.lookup(self.tenant, namespace, h, emb, self.top_k)
            if ex:
                return Hit(ex[0], ex[1], 1.0, "exact")
            info["best"] = near[0][2] if near else None
            return near

        try:
            got = self._call(lookup)  # only the DB round trip runs under the budget; the choice below does not
            hit = got if isinstance(got, Hit) or got is None else self._choose(prompt, got, info)
        except Exception as e:  # noqa: BLE001
            self.stats["fallbacks"] += 1
            fb = self.fallback.get(prompt, namespace) if self.fallback else None
            ms = (time.perf_counter() - t0) * 1000
            h2 = Hit(None, fb[0], fb[1], "sqlite") if fb else None
            return h2, Lookup(fb, fb[1] if fb else None, None, ms,
                              "unavailable")  # skipped: the call goes to the tiers
        ms = (time.perf_counter() - t0) * 1000
        self.stats["lookup_ms"].append(ms)
        if hit:
            self.stats["hits"] += 1
            self._bg(lambda s: (s.touch(self.tenant, hit.id), s.event(self.tenant, "hit", hit.id, hit.similarity, ms)))
        else:
            self.stats["misses"] += 1
            self._bg(lambda s: s.event(self.tenant, "miss", None, None, ms))
        best = 1.0 if hit and hit.source == "exact" else info["best"]
        kind = None if hit is None else "exact" if hit.source == "exact" else "semantic"
        return hit, Lookup((hit.response, hit.similarity) if hit else None, best, info["guard"], ms,
                           kind=kind, check=info["check"], via=info["via"] if hit else None)

    def _choose(self, prompt: str, near: list, info: dict) -> Hit | None:
        """Pick a verified neighbour: >= threshold as before; in the band only with guard + check. Never raises."""
        from .band import normalize_prompt
        from .guard import consistent

        qn = normalize_prompt(prompt) if self.normalize else ""
        qv: list[float] | None = None
        floor = (self.band_low or self.threshold) - 0.1  # shortcut: rows further off are not re-embedded (cost)
        scored = []
        for pid, answer, sim, verified, *rest in near:
            if not verified:
                continue
            text = rest[0] if rest else None
            score, via = sim, "raw"
            if qn and text and sim >= floor:
                tn = normalize_prompt(text)
                if tn == qn:
                    ns = 1.0
                elif tn:
                    qv = qv or _norm(self._embedder.embed(qn))
                    ns = sum(a * b for a, b in zip(qv, _norm(self._embedder.embed(tn))))
                else:
                    ns = 0.0
                if ns > score:
                    score, via = ns, "normalized"
            scored.append((score, via, pid, answer, text))
        scored.sort(key=lambda x: -x[0])
        if scored and (info["best"] is None or scored[0][0] > info["best"]):
            info["best"] = scored[0][0]
        checked = False
        for score, via, pid, answer, text in scored:
            if score >= self.threshold:
                if self.guard is not None and text is not None:
                    if not self.guard(prompt, text, score):
                        self.guarded_out += 1
                        info["guard"] = "rejected"
                        continue
                    info["guard"] = "pass"
                info["via"] = via
                return Hit(pid, answer, min(score, 1.0), "vector")
            if not self.band_low or score < self.band_low:
                break  # sorted: nothing further can reach the band
            if text is None or checked:  # no prompt text: cannot judge; at most one 30B check per lookup
                continue
            if not (self.guard or (lambda q, c, s: consistent(q, c)))(prompt, text, score):
                self.guarded_out += 1
                info["guard"] = "rejected"
                continue
            info["guard"] = "pass"
            if self.checker is not None:
                checked = True
                try:
                    ok, cinfo = self.checker(prompt, text, answer)
                except Exception as e:  # noqa: BLE001  a broken checker never serves
                    ok, cinfo = False, {"verdict": "error", "error": type(e).__name__}
                info["check"] = cinfo
                if not ok:
                    continue
            info["via"] = "band+" + via
            return Hit(pid, answer, score, "band")
        return None

    def ping(self, timeout_s: float = 3.0) -> float:
        """ms for one real lookup round trip (health checks). Own timeout, no breaker strikes. Raises when unreachable."""
        t0 = time.perf_counter()
        emb = [0.0] * 383 + [1.0]
        self._pool.submit(lambda: self._store_ready().lookup(self.tenant, "__health__", "-", emb, 1)
                          ).result(timeout=timeout_s)
        return (time.perf_counter() - t0) * 1000

    def get(self, prompt: str, namespace: str = "") -> tuple[str, float] | None:
        hit = self.get_hit(prompt, namespace)
        return (hit.response, hit.similarity) if hit else None

    def put(self, prompt: str, response: str, namespace: str = "", *, verified: bool = True, model: str = "",
            tier: str = "", tokens_in: int = 0, tokens_out: int = 0, stored_prompt: str | None = None) -> None:
        """Store an answer. Pass verified=False for answers no check has passed yet; they are never auto-served."""
        if self.fallback:
            self.fallback.put(prompt, response, namespace)
        h = prompt_hash(prompt, namespace)
        emb = _norm(self._embedder.embed(prompt))
        meta = {"model": model, "tier": tier, "tokens_in": tokens_in, "tokens_out": tokens_out,
                "verified": verified, "ttl_s": self.ttl_s}
        text = (stored_prompt if stored_prompt is not None else prompt) if self.store_text else None
        self._bg(lambda s: s.insert(self.tenant, namespace, h, text, emb, response, meta))

    def purge(self, namespace: str | None = None) -> int:
        """Delete this tenant's rows (one namespace, or all when None). Waits for the DB; raises if it is down."""
        if self.fallback and namespace is not None:
            self.fallback.purge(namespace)
        return self._pool.submit(lambda: self._store_ready().purge(self.tenant, namespace)).result(timeout=10)

    def flush(self, timeout: float = 30.0) -> None:
        """Wait until queued background writes finished (tests and benchmarks)."""
        for _ in range(2):  # two write workers
            self._wpool.submit(lambda: None).result(timeout=timeout)

    def _store_ready(self) -> Store:
        with self._lock:
            if self._store is None:
                self._store = self._store_arg()  # type: ignore[operator]
            return self._store

    # ---- feedback ------------------------------------------------------------------
    def report_false_hit(self, hit: Hit) -> None:
        """A served answer was wrong: stop serving that row and count it."""
        self.stats["false_hits"] += 1
        if hit.id is not None:
            self._bg(lambda s: (s.set_verified(self.tenant, hit.id, False),
                                s.event(self.tenant, "false_hit", hit.id, hit.similarity, None)))

    def mark_verified(self, prompt_id: int, verified: bool = True) -> None:
        self._bg(lambda s: s.set_verified(self.tenant, prompt_id, verified))

    def record_signal(self, prompt_id: int, tier_tried: str, *, confidence: float | None = None,
                      escalated: bool = False, passed_checks: bool | None = None,
                      latency_ms: float | None = None, cost: float | None = None) -> None:
        sig = {"tier_tried": tier_tried, "confidence": confidence, "escalated": escalated,
               "passed_checks": passed_checks, "latency_ms": latency_ms, "cost": cost}
        self._bg(lambda s: s.signal(self.tenant, prompt_id, sig))

    def summary(self) -> dict[str, float]:
        ms = sorted(self.stats["lookup_ms"])
        n = self.stats["hits"] + self.stats["misses"]
        pick = lambda q: ms[min(int(q * len(ms)), len(ms) - 1)] if ms else 0.0  # noqa: E731
        return {"lookups": n, "hit_rate": self.stats["hits"] / n if n else 0.0,
                "false_hit_rate": self.stats["false_hits"] / self.stats["hits"] if self.stats["hits"] else 0.0,
                "fallbacks": self.stats["fallbacks"], "p50_ms": pick(0.5), "p90_ms": pick(0.9)}
