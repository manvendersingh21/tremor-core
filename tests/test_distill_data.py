"""bench/distill/build_data.py: the train/held-out overlap filter (offline, no network)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bench" / "distill"))
import build_data as bd  # noqa: E402

HELD = [{"id": "h1", "text": "Write a function to find the longest common prefix of a list of strings. assert lcp(['ab','a']) == 'a'",
         "data": {"tests": ["assert lcp(['ab','a']) == 'a'"]}}]


def _t(i, text, test):
    return {"id": i, "text": text, "tests": [test]}


def test_overlap_flags_shared_8gram_same_first_test_and_near_duplicate():
    train = [
        _t("a", "Write a function to find the longest common prefix of a list of strings in python.", "assert f(1) == 1"),
        _t("b", "Totally different words about sorting numbers quickly please now", "assert lcp(['ab','a']) == 'a'"),
        _t("c", "Compute the nth fibonacci number with memoization for small n values only", "assert fib(5) == 5"),
    ]
    bad = bd.overlap_ids(train, HELD)
    assert set(bad) == {"a", "b"}
    assert bad["a"].startswith("8-gram") and bad["b"] == "same first test"
