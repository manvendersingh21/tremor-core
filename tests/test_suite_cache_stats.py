import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "bench"), str(ROOT / "bench" / "datasets")]

from run_suite import cache_stats  # noqa: E402


def _pair(i, role, dup=None, a=None):
    d = {"role": role, "duplicate": dup, "a_id": a}
    return {"id": i, "grader": "pair", "data": d}


def test_cache_stats_counts_true_wrong_and_stray_hits():
    suite = [_pair("a1", "a"), _pair("b1", "b", True, "a1"), _pair("a2", "a"), _pair("b2", "b", False, "a2"),
             {"id": "m1", "grader": "choice", "data": {}}]
    pool = {"a1": {"tier": "gpu-small", "answer": "X"}, "b1": {"tier": "semantic_cache", "answer": "X"},
            "a2": {"tier": "gpu-small", "answer": "Y"}, "b2": {"tier": "semantic_cache", "answer": "Y"},
            "m1": {"tier": "exact_cache", "answer": "Z"}}
    s = cache_stats(suite, pool)
    assert (s["dup_true_hit"], s["neg_hit"], s["other_hit"]) == (1, 1, 1)
