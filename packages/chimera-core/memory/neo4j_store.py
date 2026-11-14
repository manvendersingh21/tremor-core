"""Neo4j Community GraphStore (the `graph` extra: `pip install neo4j`). Teacher pairs stay in Supabase.

Model:  (:Problem)-[:SOLVED_BY]->(:Solution)-[:USES]->(:Concept)   (:Problem)-[:SIMILAR_TO {score}]->(:Problem)
        (:Solution)-[:FIXES]->(:Error)   (:Pattern)-[:PART_OF]->(:Solution)   (the one-line "why it works")
Every node also has the label :Mem and the properties id, tenant, text, embedding, created_at. Embeddings sit in
Neo4j vector indexes (5.18+), cosine, 384 dims. Edge weight is the `weight` property (`score` on SIMILAR_TO).
The server runs from /root/chimera-graph/run.sh on the GPU box, reached through a local port forward (docs/memory.md).
"""
from __future__ import annotations

import os
import time
from typing import Any

from .graph import KINDS, Edge, Node, Pair

LABEL = {"problem": "Problem", "solution": "Solution", "concept": "Concept", "pattern": "Pattern", "error": "Error"}
KIND = {v: k for k, v in LABEL.items()}
# GraphStore relation -> (neo4j type, flipped). `solves` is stored problem -> solution as SOLVED_BY.
REL = {"solves": ("SOLVED_BY", True), "uses": ("USES", False), "similar_to": ("SIMILAR_TO", False),
       "fixes": ("FIXES", False), "part_of": ("PART_OF", False)}
BACK = {v[0]: (k, v[1]) for k, v in REL.items()}
DIM = 384


class Neo4jGraphStore:
    def __init__(self, url: str | None = None, user: str | None = None, password: str | None = None,
                 pairs: Any = None, database: str | None = None) -> None:
        from neo4j import GraphDatabase  # lazy: optional `graph` extra

        url = url or os.environ.get("CHIMERA_GRAPH_URL", "")
        self.pairs = pairs
        if not url:  # no graph configured: every graph call raises ConnectionError, which Memory logs and skips
            self._driver, self._ready, self._db = None, False, None
            return
        self._driver = GraphDatabase.driver(url, auth=(user or os.environ.get("CHIMERA_GRAPH_USER", "neo4j"),
                                                       password or os.environ.get("CHIMERA_GRAPH_PASSWORD", "")),
                                            connection_timeout=10)
        self._db = database or os.environ.get("CHIMERA_GRAPH_DATABASE") or None
        self.pairs = pairs  # a store with add_pair (PgGraphStore); None = teacher pairs are not kept
        self._ready = False
        try:
            self._setup()
        except Exception as e:  # noqa: BLE001  Aura unreachable now: Memory skips the graph for each call and logs it
            import logging
            logging.getLogger("chimera.memory").warning("memory: Aura not reachable (%s); graph skipped", type(e).__name__)

    def _run(self, q: str, **p: Any) -> list[dict]:
        if self._driver is None:
            raise ConnectionError("CHIMERA_GRAPH_URL is not set")
        if not self._ready and not q.startswith("CREATE"):
            self._setup()
        with self._driver.session(database=self._db) as s:
            return [r.data() for r in s.run(q, **p)]

    def _setup(self) -> None:
        self._run("CREATE INDEX mem_id IF NOT EXISTS FOR (n:Mem) ON (n.id)")
        self._run("CREATE INDEX mem_tenant IF NOT EXISTS FOR (n:Mem) ON (n.tenant)")
        for lab in LABEL.values():
            self._run(f"CREATE VECTOR INDEX {lab.lower()}_emb IF NOT EXISTS FOR (n:{lab}) ON (n.embedding) "
                      f"OPTIONS {{indexConfig: {{`vector.dimensions`: {DIM}, `vector.similarity_function`: 'cosine'}}}}")
        self._ready = True

    def close(self) -> None:
        self._driver.close()

    def add_node(self, tenant, kind, text, emb):
        if kind not in LABEL:
            raise ValueError(f"unknown kind {kind}")
        r = self._run("MERGE (c:Counter {name:'node'}) SET c.v = coalesce(c.v, 0) + 1 WITH c.v AS id "
                      f"CREATE (n:Mem:{LABEL[kind]} {{id:id, tenant:$t, text:$text, embedding:$emb, created_at:$now}}) "
                      "RETURN id", t=tenant, text=text, emb=emb, now=time.time())
        return r[0]["id"]

    def find_node(self, tenant, kind, text):
        r = self._run(f"MATCH (n:Mem:{LABEL[kind]} {{tenant:$t, text:$text}}) RETURN n.id AS id LIMIT 1", t=tenant, text=text)
        return r[0]["id"] if r else None

    def add_edge(self, tenant, src, dst, rel, weight=1.0):
        typ, flip = REL[rel]
        a, b = (dst, src) if flip else (src, dst)
        prop = "score" if typ == "SIMILAR_TO" else "weight"
        n = self._run(f"MATCH (x:Mem {{id:$a, tenant:$t}}), (y:Mem {{id:$b, tenant:$t}}) "
                      f"MERGE (x)-[r:{typ}]->(y) SET r.{prop} = $w, r.tenant = $t RETURN count(r) AS n",
                      a=a, b=b, t=tenant, w=float(weight))
        if not n or n[0]["n"] == 0:
            raise ValueError("edge crosses tenants or an end node is missing")

    def nearest(self, tenant, kind, emb, k):
        rows = self._run("CALL db.index.vector.queryNodes($idx, $n, $emb) YIELD node, score "
                         "WHERE node.tenant = $t RETURN node.id AS id, node.text AS text, node.created_at AS ts, "
                         "score ORDER BY score DESC LIMIT $k",
                         idx=f"{LABEL[kind].lower()}_emb", n=max(k * 20, 100), emb=emb, t=tenant, k=k)
        # Neo4j's cosine score is (1 + cos) / 2; turn it back into cosine so it matches the Postgres store.
        return [(Node(r["id"], kind, r["text"], float(r["ts"])), 2 * float(r["score"]) - 1) for r in rows]

    def neighbors(self, tenant, ids):
        if not ids:
            return []
        rows = self._run("MATCH (x:Mem {tenant:$t})-[r]->(y:Mem {tenant:$t}) WHERE x.id IN $ids OR y.id IN $ids "
                         "RETURN labels(x) AS lx, x.id AS xi, x.text AS xt, x.created_at AS xc, type(r) AS typ, "
                         "coalesce(r.weight, r.score, 1.0) AS w, labels(y) AS ly, y.id AS yi, y.text AS yt, "
                         "y.created_at AS yc", t=tenant, ids=list(ids))
        out = []
        for r in rows:
            if r["typ"] not in BACK:
                continue
            kx = next(KIND[l] for l in r["lx"] if l in KIND)
            ky = next(KIND[l] for l in r["ly"] if l in KIND)
            x, y = Node(r["xi"], kx, r["xt"], float(r["xc"])), Node(r["yi"], ky, r["yt"], float(r["yc"]))
            rel, flip = BACK[r["typ"]]
            if flip:  # stored problem -> solution; the interface wants solution -> problem
                out.append((Edge(y.id, x.id, rel, float(r["w"])), y, x))
            else:
                out.append((Edge(x.id, y.id, rel, float(r["w"])), x, y))
        return out

    def add_pair(self, tenant, pair: Pair, emb):
        return self.pairs.add_pair(tenant, pair, emb) if self.pairs else 0

    def stats(self, tenant):
        out = {k: 0 for k in KINDS}
        for r in self._run("MATCH (n:Mem {tenant:$t}) RETURN labels(n) AS l, count(*) AS c", t=tenant):
            for l in r["l"]:
                if l in KIND:
                    out[KIND[l]] += r["c"]
        out["edges"] = self._run("MATCH (:Mem {tenant:$t})-[r]->() RETURN count(r) AS c", t=tenant)[0]["c"]
        out["teacher_pairs"] = self.pairs.stats(tenant)["teacher_pairs"] if self.pairs else 0
        return out

    def purge(self, tenant):
        n = self._run("MATCH (n:Mem {tenant:$t}) DETACH DELETE n RETURN count(*) AS c", t=tenant)
        return (n[0]["c"] if n else 0) + (self.pairs.purge(tenant) if self.pairs else 0)


def default_store():
    """The graph is hosted Neo4j Aura only (CHIMERA_GRAPH_URL/USER/PASSWORD/DATABASE). Teacher pairs go to Supabase
    when CHIMERA_DB_URL is set. Never raises: if Aura is down, `Memory` skips the graph for that call and logs it."""
    import logging

    from .graph import PgGraphStore

    log = logging.getLogger("chimera.memory")
    try:
        pg = PgGraphStore(os.environ["CHIMERA_DB_URL"]) if os.environ.get("CHIMERA_DB_URL") else None
    except Exception as e:  # noqa: BLE001
        log.warning("memory: Supabase unavailable (%s); teacher pairs skipped", type(e).__name__)
        pg = None
    log.info("memory: graph store = aura")
    return Neo4jGraphStore(pairs=pg)
