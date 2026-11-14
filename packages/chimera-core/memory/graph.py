"""Graph storage adapters. `GraphStore` is the interface; Postgres (pgvector) is the real one, `InMemoryStore` is
the fake used by tests and benchmarks, `Neo4jGraphStore` is a stub for a dedicated graph DB later."""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

KINDS = ("problem", "solution", "concept", "pattern", "error")
RELS = ("solves", "uses", "similar_to", "fixes", "part_of")


@dataclass
class Node:
    id: int
    kind: str
    text: str
    created_at: float  # unix seconds


@dataclass
class Edge:
    src: int
    dst: int
    rel: str
    weight: float = 1.0


@dataclass
class Pair:
    prompt: str
    answer: str
    model: str = ""
    tier: str = ""
    verified: bool = True
    tests_passed: bool | None = None
    tokens_in: int = 0
    tokens_out: int = 0


class GraphStore(Protocol):
    """Everything is per tenant. Embeddings are L2-normalised lists of floats (384 for MiniLM)."""

    def add_node(self, tenant: str, kind: str, text: str, emb: list[float]) -> int: ...
    def find_node(self, tenant: str, kind: str, text: str) -> int | None: ...
    def add_edge(self, tenant: str, src: int, dst: int, rel: str, weight: float = 1.0) -> None: ...
    def nearest(self, tenant: str, kind: str, emb: list[float], k: int) -> list[tuple[Node, float]]: ...
    def neighbors(self, tenant: str, ids: list[int]) -> list[tuple[Edge, Node, Node]]:
        """All edges touching `ids` (either direction) with both end nodes: (edge, src_node, dst_node)."""
    def add_pair(self, tenant: str, pair: Pair, emb: list[float]) -> int: ...
    def stats(self, tenant: str) -> dict[str, int]: ...
    def purge(self, tenant: str) -> int: ...


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class InMemoryStore:
    """Dict-backed GraphStore for tests and benchmarks. Same behaviour as the Postgres one."""

    def __init__(self) -> None:
        self._n: dict[int, tuple[str, Node, list[float]]] = {}  # id -> (tenant, node, emb)
        self._e: dict[tuple[int, int, str], tuple[str, float]] = {}
        self.pairs: list[tuple[str, Pair, list[float]]] = []
        self._next = 1
        self._lock = threading.Lock()

    def add_node(self, tenant, kind, text, emb):
        with self._lock:
            i, self._next = self._next, self._next + 1
            self._n[i] = (tenant, Node(i, kind, text, time.time()), emb)
            return i

    def find_node(self, tenant, kind, text):
        for i, (t, n, _) in self._n.items():
            if t == tenant and n.kind == kind and n.text == text:
                return i
        return None

    def add_edge(self, tenant, src, dst, rel, weight=1.0):
        with self._lock:
            if self._n[src][0] != tenant or self._n[dst][0] != tenant:
                raise ValueError("edge crosses tenants")
            self._e[(src, dst, rel)] = (tenant, weight)

    def nearest(self, tenant, kind, emb, k):
        c = [(n, cosine(emb, e)) for t, n, e in self._n.values() if t == tenant and n.kind == kind]
        return sorted(c, key=lambda x: -x[1])[:k]

    def neighbors(self, tenant, ids):
        s = set(ids)
        return [(Edge(a, b, r, w), self._n[a][1], self._n[b][1])
                for (a, b, r), (t, w) in self._e.items() if t == tenant and (a in s or b in s)]

    def add_pair(self, tenant, pair, emb):
        self.pairs.append((tenant, pair, emb))
        return len(self.pairs)

    def stats(self, tenant):
        out = {k: sum(1 for t, n, _ in self._n.values() if t == tenant and n.kind == k) for k in KINDS}
        out["edges"] = sum(1 for t, _ in self._e.values() if t == tenant)
        out["teacher_pairs"] = sum(1 for t, _, _ in self.pairs if t == tenant)
        return out

    def purge(self, tenant):
        n = sum(1 for t, _, _ in self.pairs if t == tenant) + sum(1 for t, _, _ in self._n.values() if t == tenant)
        self.pairs = [p for p in self.pairs if p[0] != tenant]
        self._n = {i: v for i, v in self._n.items() if v[0] != tenant}
        self._e = {k: v for k, v in self._e.items() if v[0] != tenant}
        return n


def _vec(emb: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in emb) + "]"


class PgGraphStore:
    """Postgres + pgvector (deploy/sql/005_memory.sql). Each call is one transaction that first sets `app.tenant`
    for RLS, and every query also filters on tenant, so it stays isolated on a role that bypasses RLS."""

    def __init__(self, dsn: str, max_size: int = 4) -> None:
        from psycopg_pool import ConnectionPool  # lazy: optional `postgres` extra

        self._pool = ConnectionPool(dsn, min_size=1, max_size=max_size, open=False, timeout=10,
                                    kwargs={"connect_timeout": 5})
        self._pool.open(wait=False)

    def _tx(self, tenant: str, sql: str, params: tuple = (), fetch: str = "") -> Any:
        with self._pool.connection() as conn:
            conn.execute("select set_config('app.tenant', %s, true)", (tenant,))
            cur = conn.execute(sql, params)
            return cur.fetchone() if fetch == "one" else cur.fetchall() if fetch == "all" else cur.rowcount

    def close(self) -> None:
        self._pool.close()

    def add_node(self, tenant, kind, text, emb):
        return self._tx(tenant, "insert into mem_nodes (tenant, kind, text, embedding) values (%s,%s,%s,%s::vector) "
                        "returning id", (tenant, kind, text, _vec(emb)), "one")[0]

    def find_node(self, tenant, kind, text):
        r = self._tx(tenant, "select id from mem_nodes where tenant=%s and kind=%s and text=%s limit 1",
                     (tenant, kind, text), "one")
        return r[0] if r else None

    def add_edge(self, tenant, src, dst, rel, weight=1.0):
        self._tx(tenant, "insert into mem_edges (tenant, src, dst, rel, weight) select %s,%s,%s,%s,%s "
                 "where (select count(*) from mem_nodes where tenant=%s and id in (%s,%s)) = %s "
                 "on conflict (src, dst, rel) do update set weight=excluded.weight",
                 (tenant, src, dst, rel, weight, tenant, src, dst, 1 if src == dst else 2))

    def nearest(self, tenant, kind, emb, k):
        v = _vec(emb)
        rows = self._tx(tenant, "select id, kind, text, extract(epoch from created_at), 1 - (embedding <=> %s::vector) "
                        "from mem_nodes where tenant=%s and kind=%s order by embedding <=> %s::vector limit %s",
                        (v, tenant, kind, v, k), "all")
        return [(Node(r[0], r[1], r[2], float(r[3])), float(r[4])) for r in rows]

    def neighbors(self, tenant, ids):
        if not ids:
            return []
        rows = self._tx(tenant, "select e.src, e.dst, e.rel, e.weight, a.kind, a.text, extract(epoch from a.created_at), "
                        "b.kind, b.text, extract(epoch from b.created_at) from mem_edges e "
                        "join mem_nodes a on a.id=e.src join mem_nodes b on b.id=e.dst "
                        "where e.tenant=%s and (e.src = any(%s) or e.dst = any(%s))", (tenant, ids, ids), "all")
        return [(Edge(r[0], r[1], r[2], float(r[3])), Node(r[0], r[4], r[5], float(r[6])),
                 Node(r[1], r[7], r[8], float(r[9]))) for r in rows]

    def add_pair(self, tenant, pair, emb):
        return self._tx(tenant, "insert into teacher_pairs (tenant, prompt, prompt_embedding, answer, model, tier, "
                        "verified, tests_passed, tokens_in, tokens_out) values (%s,%s,%s::vector,%s,%s,%s,%s,%s,%s,%s) "
                        "returning id", (tenant, pair.prompt, _vec(emb), pair.answer, pair.model, pair.tier,
                                         pair.verified, pair.tests_passed, pair.tokens_in, pair.tokens_out), "one")[0]

    def stats(self, tenant):
        out = {k: 0 for k in KINDS}
        for kind, n in self._tx(tenant, "select kind, count(*) from mem_nodes where tenant=%s group by kind",
                                (tenant,), "all"):
            out[kind] = n
        out["edges"] = self._tx(tenant, "select count(*) from mem_edges where tenant=%s", (tenant,), "one")[0]
        out["teacher_pairs"] = self._tx(tenant, "select count(*) from teacher_pairs where tenant=%s", (tenant,), "one")[0]
        return out

    def purge(self, tenant):
        n = self._tx(tenant, "delete from mem_nodes where tenant=%s", (tenant,))  # edges cascade
        return n + self._tx(tenant, "delete from teacher_pairs where tenant=%s", (tenant,))
