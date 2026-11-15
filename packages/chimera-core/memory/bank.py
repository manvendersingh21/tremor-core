"""Solved-problem bank: verified problem/solution pairs, looked up before any model call.

    bank.lookup(problem, tests=None) -> Lookup     exact hash, then cosine
    bank.add(problem, answer, tests, ...)          only after the answer passes `tests` again

A close match is served only after its tests pass. A weaker match, or a close one whose tests fail, becomes a hint
for the 30B. A miss goes to the ladder; the passing answer is written back with `add`. See docs/memory.md.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .graph import _vec, cosine
from .memory import Example, Memory
from .safety import scrub

log = logging.getLogger("chimera.bank")
SERVE_AT = 0.90   # cosine at or above this: try the stored answer against the tests
HINT_AT = 0.70    # cosine at or above this: show the stored answer to the 30B as an example
TRY = 3           # candidates tried per lookup


def prompt_hash(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().lower().encode()).hexdigest()


def scrub_obj(x: Any) -> Any:
    if isinstance(x, str):
        return scrub(x)
    if isinstance(x, list):
        return [scrub_obj(i) for i in x]
    if isinstance(x, dict):
        return {k: scrub_obj(v) for k, v in x.items()}
    return x


@dataclass
class Record:
    id: int
    prompt: str
    answer: str
    tests: dict
    source: str = ""
    model: str = ""
    tier: str = ""


@dataclass
class Lookup:
    kind: str                       # served | hint | miss
    answer: str = ""                # set when served
    how: str = ""                   # exact | cosine
    score: float = 0.0
    hints: list[Example] = field(default_factory=list)  # for the 30B when not served
    tests_run: int = 0
    wrong_caught: int = 0           # candidates at or above SERVE_AT whose tests failed

    def hint_text(self) -> str:
        return "".join(f"\nExample {i}\nProblem: {h.problem}\nSolution:\n{h.solution}\n" for i, h in enumerate(self.hints, 1))


class InMemoryBankStore:
    """Fake for tests and offline runs."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], tuple[Record, list[float]]] = {}
        self.hits: dict[int, int] = {}
        self._n = 0

    def exact(self, tenant: str, h: str) -> Record | None:
        r = self.rows.get((tenant, h))
        return r[0] if r else None

    def nearest(self, tenant: str, emb: list[float], k: int) -> list[tuple[Record, float]]:
        c = [(r, cosine(emb, e)) for (t, _), (r, e) in self.rows.items() if t == tenant]
        return sorted(c, key=lambda x: -x[1])[:k]

    def add(self, tenant: str, h: str, rec: Record, emb: list[float], tokens: tuple[int, int] = (0, 0)) -> int:
        old = self.rows.get((tenant, h))
        rec.id = old[0].id if old else self._n + 1
        self._n = max(self._n, rec.id)
        self.rows[(tenant, h)] = (rec, emb)
        return rec.id

    def hit(self, tenant: str, rid: int) -> None:
        self.hits[rid] = self.hits.get(rid, 0) + 1

    def stats(self, tenant: str) -> dict:
        rs = [r for (t, _), (r, _) in self.rows.items() if t == tenant]
        by: dict[str, int] = {}
        for r in rs:
            by[r.source] = by.get(r.source, 0) + 1
        return {"size": len(rs), "by_source": by, "hits": sum(self.hits.values())}

    def purge(self, tenant: str) -> int:
        keys = [k for k in self.rows if k[0] == tenant]
        for k in keys:
            del self.rows[k]
        return len(keys)


class PgBankStore:
    """Supabase Postgres + pgvector (deploy/sql/006_bank.sql). One transaction per call, `app.tenant` set for RLS."""

    def __init__(self, dsn: str, max_size: int = 4) -> None:
        from psycopg_pool import ConnectionPool  # lazy: optional `postgres` extra

        self._pool = ConnectionPool(dsn, min_size=1, max_size=max_size, open=False, timeout=10, kwargs={"connect_timeout": 5})
        self._pool.open(wait=False)

    def _tx(self, tenant: str, sql: str, params: tuple = (), fetch: str = "") -> Any:
        with self._pool.connection() as conn:
            conn.execute("select set_config('app.tenant', %s, true)", (tenant,))
            cur = conn.execute(sql, params)
            return cur.fetchone() if fetch == "one" else cur.fetchall() if fetch == "all" else cur.rowcount

    @staticmethod
    def _rec(r) -> Record:
        return Record(r[0], r[1], r[2], r[3] if isinstance(r[3], dict) else json.loads(r[3]), r[4], r[5], r[6])

    def exact(self, tenant, h):
        r = self._tx(tenant, "select id, prompt, answer, tests, source, model, tier from solved_bank "
                     "where tenant=%s and prompt_hash=%s", (tenant, h), "one")
        return self._rec(r) if r else None

    def nearest(self, tenant, emb, k):
        v = _vec(emb)
        rows = self._tx(tenant, "select id, prompt, answer, tests, source, model, tier, 1 - (prompt_embedding <=> %s::vector) "
                        "from solved_bank where tenant=%s order by prompt_embedding <=> %s::vector limit %s",
                        (v, tenant, v, k), "all")
        return [(self._rec(r), float(r[7])) for r in rows]

    def add(self, tenant, h, rec, emb, tokens=(0, 0)):
        return self._tx(tenant, "insert into solved_bank (tenant, prompt_hash, prompt, prompt_embedding, answer, tests, "
                        "source, model, tier, tokens_in, tokens_out) values (%s,%s,%s,%s::vector,%s,%s::jsonb,%s,%s,%s,%s,%s) "
                        "on conflict (tenant, prompt_hash) do update set answer=excluded.answer, tests=excluded.tests "
                        "returning id", (tenant, h, rec.prompt, _vec(emb), rec.answer, json.dumps(rec.tests), rec.source,
                                         rec.model, rec.tier, tokens[0], tokens[1]), "one")[0]

    def hit(self, tenant, rid):
        self._tx(tenant, "update solved_bank set hits = hits + 1 where tenant=%s and id=%s", (tenant, rid))

    def stats(self, tenant):
        by = dict(self._tx(tenant, "select source, count(*) from solved_bank where tenant=%s group by source", (tenant,), "all"))
        hits = self._tx(tenant, "select coalesce(sum(hits),0) from solved_bank where tenant=%s", (tenant,), "one")[0]
        return {"size": sum(by.values()), "by_source": by, "hits": int(hits)}

    def purge(self, tenant):
        return self._tx(tenant, "delete from solved_bank where tenant=%s", (tenant,))

    def close(self) -> None:
        self._pool.close()


class Bank:
    """`verify(answer, tests) -> bool` runs the tests (a sandbox for code). `memory` is optional: when given, every
    banked answer is also stored there, so the same problem and solution land in the Aura graph and teacher_pairs."""

    def __init__(self, store, embedder, tenant: str, verify: Callable[[str, dict], bool], memory: Memory | None = None,
                 serve_at: float = SERVE_AT, hint_at: float = HINT_AT) -> None:
        self.store, self.embedder, self.tenant, self.verify, self.memory = store, embedder, tenant, verify, memory
        self.serve_at, self.hint_at = serve_at, hint_at
        self.rejected = 0

    def _emb(self, text: str) -> list[float]:
        v = [float(x) for x in self.embedder.embed(text)]
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def _check(self, answer: str, tests: dict | None) -> bool:
        try:
            return bool(tests) and bool(self.verify(answer, tests))
        except Exception as e:  # noqa: BLE001  a crashing check counts as a failed check
            log.warning("bank: verify raised (%s)", type(e).__name__)
            return False

    def lookup(self, problem: str, tests: dict | None = None) -> Lookup:
        """Never raises: a store failure is a miss. `tests` are the new problem's own tests; an exact hit may use its
        stored tests instead. A cosine hit with no tests to run is never served, only offered as a hint."""
        try:
            return self._lookup(scrub(problem), tests)
        except Exception as e:  # noqa: BLE001
            log.warning("bank: lookup skipped (%s)", type(e).__name__)
            return Lookup("miss")

    def _lookup(self, problem: str, tests: dict | None) -> Lookup:
        t = self.tenant
        cands: list[tuple[Record, float, str]] = []
        ex = self.store.exact(t, prompt_hash(problem))
        if ex:
            cands.append((ex, 1.0, "exact"))
        for r, s in self.store.nearest(t, self._emb(problem), TRY + 1):
            if not ex or r.id != ex.id:
                cands.append((r, s, "cosine"))
        out = Lookup("miss")
        for r, s, how in cands:
            if s < self.hint_at:
                continue
            if s >= self.serve_at and out.tests_run < TRY:
                use = tests if tests is not None else (r.tests if how == "exact" else None)
                if use:
                    out.tests_run += 1
                    if self._check(r.answer, use):
                        self.store.hit(t, r.id)
                        out.kind, out.answer, out.how, out.score = "served", r.answer, how, s
                        return out
                    out.wrong_caught += 1  # looked like a match, the tests say no
            out.hints.append(Example(r.prompt, r.answer, "", s))
        if out.hints:
            out.kind, out.how, out.score = "hint", cands[0][2], out.hints[0].score
            out.hints = out.hints[:3]
        return out

    def add(self, problem: str, answer: str, tests: dict, source: str = "", model: str = "", tier: str = "",
            tokens: dict | None = None) -> int | None:
        """Write back an answer. It must pass `tests` here, now; the caller's own flag is not trusted."""
        if not answer.strip() or not problem.strip() or not self._check(answer, tests):
            self.rejected += 1
            return None
        p, a = scrub(problem), scrub(answer)
        tk = tokens or {}
        try:
            rid = self.store.add(self.tenant, prompt_hash(p), Record(0, p, a, scrub_obj(tests), source, model, tier),
                                 self._emb(p), (int(tk.get("in", 0)), int(tk.get("out", 0))))
        except Exception as e:  # noqa: BLE001  never fail the caller's request because the bank is down
            log.warning("bank: write skipped (%s)", type(e).__name__)
            return None
        if self.memory:
            self.memory.store(problem, answer, model or source, tier, True, True, tk)
        return rid

    def stats(self) -> dict:
        s = self.store.stats(self.tenant)
        s.update(rejected_this_session=self.rejected, tenant=self.tenant)
        return s

    def purge(self) -> int:
        return self.store.purge(self.tenant)
