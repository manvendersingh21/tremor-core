"""Property tests for the caches and the guard. Offline: fake embedder, fake Supabase store. See docs/handoff/property-tests.md."""
import math
import re

import pytest
from hypothesis import example, given, strategies as st

from _props import PBT
from test_pgvector_cache import FakeStore, settle

from chimera_core.cache.exact_cache import ExactCache, normalize, prompt_hash
from chimera_core.cache.guard import consistent
from chimera_core.cache.pgvector_cache import PgVectorCache
from chimera_core.cache.semantic_cache import SemanticCache
from chimera_core.router import Events, RouterConfig, SpeculativeCascadeRouter

text = st.text(max_size=60)
ns = st.text(max_size=8)
ASCII_WORDS = st.lists(st.text(alphabet="abcdefXYZ0189", min_size=1, max_size=6), min_size=1, max_size=6)


# P1 (R1.1): normalize is idempotent
@PBT
@given(text)
def test_normalize_is_idempotent(s):
    assert normalize(normalize(s)) == normalize(s)


# P2 (R1.1): prompts that differ only in case and whitespace share one key
@PBT
@given(ASCII_WORDS, st.lists(st.sampled_from([" ", "  ", "\t", "\n", " \r\n "]), min_size=6, max_size=6), ns)
def test_equal_normalized_prompts_share_a_key(words, seps, namespace):
    a = " ".join(words)
    b = "".join(w.upper() + s for w, s in zip(words, seps))
    assert normalize(a) == normalize(b)
    assert prompt_hash(a, namespace) == prompt_hash(b, namespace)


@PBT
@given(text, text, ns)
def test_different_normalized_prompts_get_different_keys(a, b, namespace):
    if normalize(a) != normalize(b):
        assert prompt_hash(a, namespace) != prompt_hash(b, namespace)


# P3 (R1.5): a namespace (tenant) never reads another's answer
@PBT
@given(text, ns, ns)
def test_exact_cache_namespaces_are_isolated(prompt, n1, n2):
    c = ExactCache()
    c.put(prompt, "A", n1)
    if n1 != n2:
        assert c.get(prompt, n2) is None
    assert c.get(prompt, n1) == "A"


def _keys_differ(n1, p1, n2, p2):
    if (n1, normalize(p1)) != (n2, normalize(p2)):
        assert prompt_hash(p1, n1) != prompt_hash(p2, n2)


no_nul = st.text(alphabet=st.characters(blacklist_characters="\x00"), max_size=8)


@PBT
@given(no_nul, text, no_nul, text)
def test_exact_cache_keys_differ_when_namespace_or_prompt_differ(n1, p1, n2, p2):
    """Two (namespace, prompt) pairs that differ must hash differently (namespaces without NUL)."""
    _keys_differ(n1, p1, n2, p2)


@pytest.mark.xfail(strict=True, reason="FOUND: prompt_hash joins namespace and prompt with NUL, so namespace 'a' + prompt "
                   "'b\\x00c' collides with namespace 'a\\x00b' + prompt 'c'. Owner: cache/exact_cache.py. "
                   "Fix: length-prefix the namespace or reject NUL in namespace.")
@PBT
@given(ns, text, ns, text)
@example("a", "b\x00c", "a\x00b", "c")
def test_exact_cache_keys_collide_when_namespace_holds_nul(n1, p1, n2, p2):
    _keys_differ(n1, p1, n2, p2)


@PBT
@given(text, st.text(alphabet="abc", max_size=3), st.text(alphabet="abc", max_size=3))
def test_pgvector_tenants_never_share_a_hit(prompt, t1, t2):
    store = FakeStore()
    a = PgVectorCache(_Vec(), store, tenant="ta" + t1)
    b = PgVectorCache(_Vec(), store, tenant="ta" + t2)
    a.put(prompt, "answer-a")
    settle(a)
    if t1 != t2:
        assert b.get(prompt) is None
    assert a.get(prompt)[0] == "answer-a"


class _Vec:
    """Embedder with a constant direction: every prompt looks identical to the semantic search."""
    def embed(self, text):
        return [1.0, 0.0, 0.0]


class Table:
    """Embedder that returns whatever vector the test registered for a text."""
    def __init__(self):
        self.v = {}

    def embed(self, text):
        return self.v[text]


def _cos(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


vec = st.lists(st.floats(-1, 1), min_size=3, max_size=3).filter(lambda v: sum(x * x for x in v) > 1e-3)
noise = st.sampled_from([0.0, 0.01, 0.05, 0.2, 1.0])


# P4 (R1.2): a semantic hit has cosine >= threshold, is the best one, and none is missed above threshold
@PBT
@given(st.lists(vec, min_size=1, max_size=6), vec, noise, st.integers(0, 5))
def test_semantic_cache_never_hits_below_threshold(stored, q, eps, pick):
    emb = Table()
    cache = SemanticCache(emb, threshold=0.97)
    for i, v in enumerate(stored):
        emb.v[f"s{i}"] = v
        cache.put(f"s{i}", f"r{i}")
    base = stored[pick % len(stored)]
    emb.v["q"] = [x + eps * y for x, y in zip(base, q)] if sum(x * x for x in [b + eps * c for b, c in zip(base, q)]) > 1e-3 else q
    sims = [_cos(emb.v["q"], v) for v in stored]
    hit = cache.get("q")
    if hit is not None:
        assert hit[1] >= 0.97 - 1e-6
        assert sims[int(hit[0][1:])] >= 0.97 - 1e-4
        assert hit[1] >= max(sims) - 1e-4  # the best match, not just a match
    if max(sims) >= 0.97 + 1e-4:
        assert hit is not None


# P5 (R1.2): the exact cache answers before the semantic cache
@PBT
@given(st.text(min_size=1, max_size=30).filter(lambda s: s.strip()), ns)
def test_exact_beats_semantic(prompt, namespace):
    exact, sem = ExactCache(), SemanticCache(_Vec(), threshold=0.97)
    exact.put(prompt, "EXACT", namespace)
    sem.put(prompt, "SEMANTIC", namespace)
    r = SpeculativeCascadeRouter(local=None, exact=exact, semantic=sem, config=RouterConfig(namespace=namespace))
    text_, tier, _ = r._lookup(prompt, Events())
    assert (text_, tier) == ("EXACT", "exact_cache")


# P6 (R1.4): the semantic path keeps the namespace boundary
@PBT
@given(ns, ns)
def test_semantic_cache_namespaces_are_isolated(n1, n2):
    c = SemanticCache(_Vec(), threshold=0.97)
    c.put("p", "A", n1)
    assert (c.get("p", n2) is None) == (n1 != n2)


# P7 (R1.6): the guard rejects prompts that differ only in a number, a negation or a named entity
ints = st.integers(0, 10**6)


@PBT
@given(ints, ints, st.sampled_from(["Add {} and {}", "What is {} plus {} in Python", "Sort {} items then take {}"]))
def test_guard_rejects_number_only_changes(a, b, tpl):
    if a != b:
        assert not consistent(tpl.format(a, 5), tpl.format(b, 5))
    assert consistent(tpl.format(a, 5), tpl.format(a, 5))


@PBT
@given(st.sampled_from(["Explain how to sort a list", "Write a function that reads a file", "List the planets in order"]),
       st.sampled_from(["not", "never", "without", "don't"]))
def test_guard_rejects_negation_only_changes(base, neg):
    words = base.split()
    negated = " ".join(words[:2] + [neg] + words[2:])
    assert not consistent(base, negated) and not consistent(negated, base)


names = st.text(alphabet="abcdefghijklmnop", min_size=3, max_size=8).map(str.capitalize)


@PBT
@given(names, names, st.sampled_from(["Explain sorting in {}", "Is {} faster than Java", "Write a loop for {} users"]))
def test_guard_rejects_entity_only_changes(n1, n2, tpl):
    if n1.lower() != n2.lower():
        assert not consistent(tpl.format(n1), tpl.format(n2))


@PBT
@given(text, text)
def test_guard_is_symmetric(a, b):
    assert consistent(a, b) == consistent(b, a)


@pytest.mark.xfail(strict=True, reason="FOUND: consistent(a, a) is False when a capitalised word holds an apostrophe, because "
                   "the entity keeps the apostrophe but the word set strips it. A cosine hit on the same prompt is then "
                   "guard-rejected. Owner: cache/guard.py _signature(). Counterexample: \"What is Python's GIL\".")
@PBT
@example("What is Python's GIL")
@given(text)
def test_guard_is_reflexive(a):
    assert consistent(a, a)
