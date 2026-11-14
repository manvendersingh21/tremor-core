"""PgVectorCache against an in-memory fake store (no DB, no psycopg). One `live` test hits a real DB."""
import math
import os
import time

import pytest

from chimera_core.cache.pgvector_cache import PgVectorCache, PgStore
from chimera_core.cache.semantic_cache import SemanticCache
from chimera_core.inference.telemetry import Telemetry, TelemetryTracker

WORDS = ["sort", "list", "python", "capital", "france", "paris", "reverse", "string"]


class Bag:
    def embed(self, text):
        t = text.lower().split()
        return [float(t.count(w)) for w in WORDS] + [0.001]


class FakeStore:
    def __init__(self):
        self.rows, self.events, self.signals, self.n = [], [], [], 0
        self.delay = 0.0
        self.fail = False

    def _chk(self):
        if self.fail:
            raise ConnectionError("db down")
        time.sleep(self.delay)

    def lookup(self, tenant, ns, h, emb, k):
        return self.find_exact(tenant, ns, h), self.find_nearest(tenant, ns, emb, k)

    def find_exact(self, tenant, ns, h):
        self._chk()
        for r in self.rows:
            if (r["tenant"], r["ns"], r["h"]) == (tenant, ns, h) and r["verified"]:
                return r["id"], r["answer"]

    def find_nearest(self, tenant, ns, emb, k):
        self._chk()
        sims = [(r["id"], r["answer"], sum(a * b for a, b in zip(emb, r["emb"])), r["verified"])
                for r in self.rows if (r["tenant"], r["ns"]) == (tenant, ns)]
        return sorted(sims, key=lambda x: -x[2])[:k]

    def insert(self, tenant, ns, h, text, emb, answer, meta):
        self._chk()
        self.n += 1
        self.rows.append(dict(id=self.n, tenant=tenant, ns=ns, h=h, text=text, emb=emb, answer=answer, **meta))
        return self.n

    def touch(self, tenant, pid):
        pass

    def event(self, tenant, kind, pid, sim, ms):
        self.events.append((tenant, kind, pid))

    def signal(self, tenant, pid, sig):
        self.signals.append((pid, sig))

    def set_verified(self, tenant, pid, v):
        for r in self.rows:
            if r["id"] == pid:
                r["verified"] = v

    def purge(self, tenant, ns):
        before = len(self.rows)
        self.rows = [r for r in self.rows if not (r["tenant"] == tenant and ns in (None, r["ns"]))]
        return before - len(self.rows)


def settle(c):  # background writes run on a thread pool
    c._wpool.shutdown(wait=True)
    import concurrent.futures as cf
    c._wpool = cf.ThreadPoolExecutor(max_workers=2)


def make(store=None, **kw):
    store = store or FakeStore()
    return PgVectorCache(Bag(), store, threshold=0.97, fallback=SemanticCache(Bag(), 0.97), **kw), store


def test_exact_then_vector_hit_and_miss():
    c, s = make()
    c.put("sort a list in python", "use sorted()", tier="gpu")
    settle(c)
    assert c.get_hit("sort a list in python").source == "exact"
    assert c.get_hit("Sort  A list in python").source == "exact"  # normalized hash
    assert c.get_hit("python sort a list").source == "vector"     # same words, other order
    assert c.get("capital france paris") is None
    assert c.summary()["hit_rate"] == 0.75


def test_unverified_rows_are_not_served_and_false_hit_disables_row():
    c, s = make()
    c.put("sort a list", "maybe", verified=False)
    settle(c)
    assert c.get("sort a list") is None and c.get("list sort a") is None
    c.mark_verified(1)
    settle(c)
    hit = c.get_hit("list sort a")
    assert hit.response == "maybe"
    c.report_false_hit(hit)
    settle(c)
    assert c.get("list sort a") is None
    assert ("default", "false_hit", 1) in s.events and c.summary()["false_hit_rate"] > 0


def test_tenants_and_namespaces_are_separate_and_purge_is_scoped():
    s = FakeStore()
    a, _ = make(s, tenant="a")
    b, _ = make(s, tenant="b")
    a.put("reverse a string", "ans-a")
    a.put("reverse a string", "ans-ns", namespace="n2")
    settle(a)
    assert b.get("reverse a string") is None
    assert a.get("reverse a string")[0] == "ans-a" and a.get("reverse a string", "n2")[0] == "ans-ns"
    assert a.purge("n2") == 1 and a.get("reverse a string", "n2") is None
    assert a.get("reverse a string") is not None


def test_prompt_text_only_stored_when_opted_in():
    c, s = make()
    c.put("capital of france", "paris")
    d, s2 = make(store_text=True)
    d.put("capital of france", "paris")
    settle(c), settle(d)
    assert s.rows[0]["text"] is None and s2.rows[0]["text"] == "capital of france"


def test_db_down_or_slow_falls_back_to_sqlite_within_budget():
    c, s = make(budget_s=0.05, cooldown_s=60, max_strikes=1)
    c.put("sort a list in python", "use sorted()")
    settle(c)
    s.delay = 0.5
    t0 = time.perf_counter()
    assert c.get("sort a list in python")[0] == "use sorted()"  # answered by SQLite
    assert time.perf_counter() - t0 < 0.3
    t0 = time.perf_counter()
    c.get("sort a list in python")  # breaker open: no DB wait at all
    assert time.perf_counter() - t0 < 0.02
    assert c.summary()["fallbacks"] == 2


def test_store_factory_error_does_not_raise():
    def boom():
        raise ConnectionError("no db")

    c = PgVectorCache(Bag(), boom, fallback=SemanticCache(Bag(), 0.97))
    c.put("sort a list", "x")
    assert c.get("sort a list") is not None


def test_signals_are_recorded():
    c, s = make()
    c.record_signal(7, "mac_3b", confidence=0.8, escalated=True, passed_checks=False, latency_ms=12.0)
    settle(c)
    assert s.signals[0][0] == 7 and s.signals[0][1]["escalated"] is True


def test_telemetry_gpu_calls_avoided_and_rates():
    tr = TelemetryTracker()
    for tier in ("semantic_cache", "exact_cache", "gpu", "gpu"):
        tr.emit(Telemetry(tier_used=tier))
    tr.emit(Telemetry(tier_used="semantic_cache", false_hit=True))
    t = tr.totals()
    assert t["gpu_calls_avoided"] == 3 and t["cache_hits"] == 3
    assert t["hit_rate"] == 0.6 and t["false_hit_rate"] == pytest.approx(1 / 3)
    assert Telemetry(tier_used="gpu").gpu_calls_avoided is None  # old events stay unchanged


def test_gateway_metrics_render_cache_counters():
    from apps.gateway.metrics import Metrics

    m = Metrics()
    m.observe("t1", "exact_cache", 10, 0.0, 5)
    m.observe("t1", "gpu", 0, 0.0, 500)
    m.event("gpu_calls_avoided", "t1")
    m.event("cache_false_hits", "t1")
    out = m.render()
    assert 'chimera_gpu_calls_avoided_total{tenant="t1"} 1' in out
    assert 'chimera_cache_hit_rate{tenant="t1"} 0.5' in out
    assert 'chimera_cache_false_hit_rate{tenant="t1"} 1' in out


@pytest.mark.live
def test_live_roundtrip():
    dsn = os.environ.get("CHIMERA_DB_URL")
    if not dsn:
        pytest.skip("CHIMERA_DB_URL not set")
    c = PgVectorCache(Bag(), lambda: PgStore(dsn), tenant="pytest-live", budget_s=2.0)
    try:
        c.put("sort a list in python", "use sorted()")
        time.sleep(1)
        assert c.get("python sort a list")[0] == "use sorted()"
    finally:
        c.purge()


def test_breaker_needs_three_strikes():
    c, s = make(budget_s=0.05, cooldown_s=60)
    c.put("sort a list in python", "use sorted()")
    settle(c)
    s.delay = 0.2
    for _ in range(3):
        c.get("sort a list in python")
    s.delay = 0.0
    t0 = time.perf_counter()
    c.get("sort a list in python")  # 4th call: breaker is open now, DB is skipped
    assert c.stats["fallbacks"] == 4 and time.perf_counter() - t0 < 0.02
