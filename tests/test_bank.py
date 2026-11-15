"""Solved-problem bank with fakes: no models, no DB, no keys."""
import hashlib
import math
import re

from chimera_core.memory import Bank, InMemoryBankStore, InMemoryStore, Memory


class BagEmbedder:
    def embed(self, text):
        v = [0.0] * 384
        for w in re.findall(r"[a-z]+", text.lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 384] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]


def verify(answer, tests):
    return tests["want"] in answer  # stand-in for "run the unit tests"


def mk(**kw):
    return Bank(InMemoryBankStore(), BagEmbedder(), "t", verify, **kw)


P = "write a function that returns the sum of a list of numbers"


def test_add_is_gated_by_tests():
    b = mk()
    assert b.add(P, "return sum(xs)", {"want": "product"}) is None  # fails its tests
    assert b.add(P, "", {"want": ""}) is None
    assert b.stats()["size"] == 0 and b.rejected == 2
    assert b.add(P, "return sum(xs)", {"want": "sum"}, source="mbpp") and b.stats()["size"] == 1


def test_exact_hit_reruns_stored_tests():
    b = mk()
    b.add(P, "return sum(xs)", {"want": "sum"})
    r = b.lookup("Write a function  that returns the SUM of a list of numbers")  # same after normalising
    assert (r.kind, r.how, r.tests_run) == ("served", "exact", 1) and "sum" in r.answer
    row = next(iter(b.store.rows.values()))[0]
    row.answer = "return 0"  # a corrupted row must not be served
    assert b.lookup(P).kind != "served"


def test_cosine_served_only_when_new_tests_pass():
    b = mk()
    b.add(P, "return sum(xs)", {"want": "sum"})
    near = "write a function that returns the sum of a list of numbers please"
    assert b.lookup(near).kind == "hint"  # close, but no tests to run: hint only
    ok = b.lookup(near, {"want": "sum"})
    assert (ok.kind, ok.how) == ("served", "cosine")
    wrong = b.lookup(near, {"want": "product"})  # looks the same, tests disagree
    assert wrong.kind == "hint" and wrong.wrong_caught == 1 and wrong.hints


def test_weak_match_is_hint_and_far_is_miss():
    b = mk()
    b.add(P, "return sum(xs)", {"want": "sum"})
    weak = "write a function that returns the sum of a list of strings joined by commas and sorted"
    r = b.lookup(weak, {"want": "sum"})
    assert r.kind in ("hint", "miss") and r.answer == ""
    assert b.lookup("parse a csv file and plot the histogram of column three").kind == "miss"


def test_scrub_and_tenant_isolation_and_purge():
    b = mk()
    b.add(P + " key sk-abcdefghijklmnopqrstuvwx", "return sum(xs)  # mail a@b.com", {"want": "sum", "note": "token=abcdef123456"})
    row = next(iter(b.store.rows.values()))[0]
    assert "sk-abc" not in row.prompt and "a@b.com" not in row.answer and "abcdef123456" not in str(row.tests)
    other = Bank(b.store, BagEmbedder(), "other", verify)
    assert other.lookup(P).kind == "miss" and other.stats()["size"] == 0
    assert b.purge() == 1 and b.stats()["size"] == 0


def test_store_down_is_a_miss_and_memory_gets_the_pair():
    class Down(InMemoryBankStore):
        def exact(self, *a):
            raise RuntimeError("db down")
    assert Bank(Down(), BagEmbedder(), "t", verify).lookup(P).kind == "miss"
    g = InMemoryStore()
    b = mk(memory=Memory(g, BagEmbedder(), "t"))
    b.add(P, "return sum(xs)", {"want": "sum"})
    assert g.stats("t")["problem"] == 1 and g.stats("t")["solution"] == 1
