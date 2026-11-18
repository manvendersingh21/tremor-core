"""skeleton/apps/coder/classroom.py: student 1 pays, students 2..N get the checked cached answer (demo, offline)."""
import random

from skeleton.apps.coder.classroom import ASSIGNMENTS, READINGS, Classroom, class_mix, summary_ok, text


def test_first_student_pays_the_rest_hit_the_cache():
    room = Classroom()
    try:
        q = ASSIGNMENTS["a3-palindrome"]["questions"][0][0]
        first, *rest = [room.ask("a3-palindrome", q) for _ in range(4)]
        assert not first["cache_hit"] and first["tokens"] > 0 and first["verified"]
        assert all(a["cache_hit"] and a["tokens"] == 0 and a["verified"] and a["dollars_saved"] > 0 for a in rest)
        s1, s2 = room.ask("paper", "Summarize this paper"), room.ask("paper", "Summarize this paper")
        assert not s1["cache_hit"] and s2["cache_hit"] and s2["answer"] == s1["answer"]
    finally:
        room.close()


def test_rewording_hits_only_through_normalize_and_guard():
    room = Classroom()
    try:
        room.ask("a3-palindrome", "Assignment 3: write is_palindrome(s) in palindrome.py")
        assert room.ask("a3-palindrome", "Please write is_palindrome(s) in palindrome.py, assignment 3")["cache_hit"]
        # "without" flips the ask: the guard refuses the cached answer, the model writes a new one
        a = room.ask("a3-palindrome", "Assignment 3: write is_palindrome(s) in palindrome.py without slicing")
        assert not a["cache_hit"] and a["verified"]
        room.ask("paper", "Summarize this paper")
        assert not room.ask("paper", "Summarize this paper in 3 bullet points")["cache_hit"]  # a number was added
        assert not room.ask("chapter", "Summarize this paper")["cache_hit"]  # other text: other cache section
    finally:
        room.close()


def test_failing_patch_climbs_and_is_not_what_students_get():
    room = Classroom()
    try:
        q = ASSIGNMENTS["a4-fizzbuzz"]["questions"][0][0]
        a = room.ask("a4-fizzbuzz", q)
        assert a["tried"] == ["gpu-small", "cloud-deepseek"] and a["verified"]
        b = room.ask("a4-fizzbuzz", q)
        assert b["cache_hit"] and b["answer"] == a["answer"] and "range(1, n + 1)" in b["answer"]
    finally:
        room.close()


def test_summary_check():
    src = text("paper")
    assert summary_ok("Bees near street lights kept returning for 38 minutes after sunset.", src)
    assert not summary_ok("Bees kept returning for 45 minutes.", src)  # a number the paper does not have
    assert not summary_ok(src, src) and not summary_ok("", src)
    assert summary_ok("1. Lights keep bees out late.\n2. Late bees carry less pollen.\n3. Hives did not grow faster.", src)


def test_class_mix_is_reproducible_and_heavy_on_repeats():
    a = class_mix(150, random.Random(7))
    assert a == class_mix(150, random.Random(7))
    assert len({(i, q) for i, q, _, _ in a}) <= sum(len(x["questions"]) for x in (*ASSIGNMENTS.values(), *READINGS.values()))
