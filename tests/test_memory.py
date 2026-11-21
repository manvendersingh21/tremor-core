"""Memory with fakes: no models, no DB, no keys."""
import hashlib
import math
import os
import re

from chimera_core.memory import InMemoryStore, Memory, Neo4jGraphStore, scrub
from chimera_core.memory.extract import llm_extractor, parse
import pytest


class BagEmbedder:
    """Words hashed into 64 buckets: texts that share words are close."""
    def embed(self, text):
        v = [0.0] * 384
        for w in re.findall(r"[a-z]+", text.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 384] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]


def mk(tenant="a", store=None, extractor=None):
    kw = {"extractor": extractor} if extractor else {}
    return Memory(store or InMemoryStore(), BagEmbedder(), tenant, **kw)


def put(m, prompt, ans="def f(x):\n    return sorted(x)", **kw):
    args = dict(model="big", tier="top", verified=True, tests=True, tokens={"in": 10, "out": 5})
    args.update(kw)
    return m.store(prompt, ans, **args)


def test_only_verified_is_stored():
    m = mk()
    assert put(m, "sort a list of numbers", verified=False) is None
    assert put(m, "sort a list of numbers", tests=False) is None
    assert put(m, "sort a list of numbers", tests=None) is None            # flag alone is not enough
    assert put(m, "sort a list of numbers", tests=None, score=3) is None
    assert put(m, "sort a list of numbers", tests=None, score=4) is not None  # blind grader >= 4/5
    assert put(m, "reverse a string", tests=True) is not None
    s = m.stats()
    assert s["teacher_pairs"] == 2 and s["rejected_this_session"] == 4


def test_scrub_secrets_and_pii():
    t = ("mail bob@example.com key sk-abcdefghijklmnopqrstuvwx password=hunter22 "
         "db postgres://u:pw@host:5432/x ssn 123-45-6789 card 4111 1111 1111 1111 call 555-123-4567")
    out = scrub(t)
    for bad in ("bob@example.com", "sk-abcdef", "hunter22", "u:pw@", "123-45-6789", "4111 1111", "555-123-4567"):
        assert bad not in out
    assert scrub("assert f(1234567890123) == 5") == "assert f(1234567890123) == 5"  # not a card (Luhn)
    m = mk()
    put(m, "send mail to bob@example.com", ans="x = 'sk-abcdefghijklmnopqrstuvwx'")
    p = m.graph.pairs[0][1]
    assert "bob@" not in p.prompt and "sk-abc" not in p.answer


def test_retrieve_ranks_similar_first_and_caps_tokens():
    m = mk()
    put(m, "write a function that sorts a list of integers ascending", "def sort_it(a):\n    return sorted(a)")
    put(m, "parse an ISO date string into day month year", "def p(s):\n    return s.split('-')")
    put(m, "compute the greatest common divisor of two numbers", "def g(a, b):\n    return a if b == 0 else g(b, a % b)")
    ctx = m.retrieve("sort a list of integers in ascending order", k=2)
    assert ctx.examples and "sorted" in ctx.examples[0].solution
    assert ctx.examples[0].score >= ctx.examples[-1].score
    big = mk()
    for i in range(5):
        put(big, f"sort list numbers variant {i}", "def s(a):\n" + "    # filler\n" * 400 + "    return sorted(a)")
    c = big.retrieve("sort list numbers", k=3)
    assert c.tokens <= 800 and c.examples


def test_empty_memory_gives_empty_context():
    c = mk().retrieve("anything")
    assert c.render() == "" and c.tokens == 0


def test_graph_expansion_reaches_shared_concept_problem():
    ex = lambda p, s: (["sliding window"], "keep a running sum while the window moves")  # noqa: E731
    m = mk(extractor=ex); m.min_score = 0.2
    # the two problems share no words, only the concept
    put(m, "maximum sum of k consecutive elements in an array", "def a(x,k): return 1  # window")
    put(m, "longest substring without repeating letters zebra quartz", "def b(s): return 2  # window")
    ctx = m.retrieve("maximum sum of k consecutive elements in a list", k=3)
    texts = [e.problem for e in ctx.examples]
    assert any("consecutive" in t for t in texts)
    assert "sliding window" in ctx.concepts
    # 2-hop: the concept links the unrelated-looking problem in, at a lower rank
    assert any("zebra" in t for t in texts) and texts[0].startswith("maximum")


def test_tenant_isolation_and_purge():
    st = InMemoryStore()
    a, b = mk("a", st), mk("b", st)
    put(a, "sort a list of integers ascending")
    assert b.retrieve("sort a list of integers ascending").examples == []
    assert a.retrieve("sort a list of integers ascending").examples
    assert b.purge() == 0 and a.stats()["teacher_pairs"] == 1
    assert a.purge() > 0
    assert a.stats()["teacher_pairs"] == 0 and a.retrieve("sort a list of integers ascending").examples == []
    with pytest.raises(ValueError):
        x = st.add_node("a", "concept", "x", [0.0]); y = st.add_node("b", "concept", "y", [0.0])
        st.add_edge("a", x, y, "uses")


def test_extractor_parse_and_fallback():
    assert parse('noise {"concepts": ["Two-Pointer", "sorting"], "why": "moves both ends"} tail') == (
        ["two-pointer", "sorting"], "moves both ends")
    assert parse("no json") is None
    bad = llm_extractor(lambda p: "garbage")
    cs, why = bad("p", "def f(x):\n    return sorted(x)")
    assert "sorting" in cs and why
    boom = llm_extractor(lambda p: (_ for _ in ()).throw(RuntimeError("down")))
    assert boom("p", "def f(): pass")[0]


def test_graph_down_never_fails_the_call(monkeypatch):
    from chimera_core.memory import default_store
    for k in ("CHIMERA_GRAPH_URL", "CHIMERA_DB_URL"):
        monkeypatch.delenv(k, raising=False)
    pytest.importorskip("neo4j")
    m = Memory(default_store(), BagEmbedder(), "x")       # no graph configured
    assert m.retrieve("sort a list").examples == []
    assert put(m, "sort a list of numbers") == 0           # no pair store either: skipped, not raised
    monkeypatch.setenv("CHIMERA_GRAPH_URL", "bolt://127.0.0.1:1")  # configured but unreachable
    m = Memory(default_store(), BagEmbedder(), "x")
    assert m.retrieve("sort a list").examples == []


def test_graph_error_skips_the_graph_for_a_cooldown(monkeypatch):
    # Found live (bench/run_faults.py neo4j): an Aura that never answers cost every call a 10 s connect timeout.
    from chimera_core.memory import memory as mm
    calls = []

    class Down(InMemoryStore):
        def nearest(self, *a, **kw):
            calls.append(1)
            raise TimeoutError

    now = [100.0]
    monkeypatch.setattr(mm.time, "monotonic", lambda: now[0])
    m = Memory(Down(), BagEmbedder(), "x")
    assert m.retrieve("sort a list").examples == [] and len(calls) == 1
    assert m.retrieve("sort a list").examples == [] and len(calls) == 1  # within the cooldown: graph not asked
    now[0] += mm.GRAPH_COOLDOWN_S
    m.retrieve("sort a list")
    assert len(calls) == 2  # cooldown over: tried again
