import pytest

from chimera_core.cache.guard import consistent, make_guard
from chimera_core.cache.semantic_cache import SemanticCache


class Same:
    """Embedder that maps every text to the same vector, so cosine is always 1.0."""

    def embed(self, text):
        return [1.0, 0.0]


@pytest.mark.parametrize("a,b,ok", [
    ("How do I sort a list in Python?", "How can I sort a list in python?", True),
    ("Add 17 and 25", "Add 17 and 26", False),
    ("Is Paris the capital of France?", "Is Paris not the capital of France?", False),
    ("Convert this to Kotlin", "Convert this to Rust", False),
    ("Find the largest element", "Find the smallest element", False),
    ("What is user_id for?", "What is order_id for?", False),
])
def test_consistent(a, b, ok):
    assert consistent(a, b) is ok


def test_semantic_cache_guard_turns_false_hit_into_miss():
    plain = SemanticCache(Same(), 0.9)
    guarded = SemanticCache(Same(), 0.9, guard=make_guard())
    for c in (plain, guarded):
        c.put("Add 17 and 25", "42")
    assert plain.get("Add 17 and 26") is not None  # the false hit the guard exists for
    assert guarded.get("Add 17 and 26") is None and guarded.guarded_out == 1
    assert guarded.get("add 17 and 25") is not None


def test_apostrophe_entity_is_reflexive_but_still_compared():
    assert consistent("What is Python's GIL", "What is Python's GIL") is True
    assert consistent("What is Python's GIL", "What is Ruby's GIL") is False


def test_entity_order_and_non_prefix():
    """Wrong hits found by bench/run_paraphrase_cache.py (t10 and a QQP pair)."""
    assert not consistent("Convert 100 degrees Celsius to Fahrenheit.", "Convert 100 degrees Fahrenheit to Celsius.")
    assert not consistent("best relationship (romantic) you've had", "best relationship (non-romantic) you've had")
    assert consistent("What is the capital of France?", "Tell me the capital of France")
    assert consistent("What is the capital of Japan?", "Tell me Japan's capital city.")  # possessive
    assert consistent("How do I check my Python version?", "how to check python version")  # "I" is no entity
    assert not consistent("What is the capital of Japan?", "Tell me China's capital city.")
