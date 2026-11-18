"""bench/hard_live: the classic questions' tests accept a correct answer and reject a wrong one; the summary counts."""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench" / "hard_live"))
sys.path.insert(0, str(ROOT / "bench" / "datasets"))
import classics  # noqa: E402
import grade  # noqa: E402

F = "```python\n{}\n```"

GOOD = {
    "classic-median-two": '''
def median_two(a, b):
    if len(a) > len(b):
        a, b = b, a
    m, n = len(a), len(b)
    if m + n == 0:
        raise ValueError("empty")
    lo, hi, half = 0, m, (m + n + 1) // 2
    while lo <= hi:
        i = (lo + hi) // 2
        j = half - i
        al = a[i - 1] if i > 0 else float("-inf")
        ar = a[i] if i < m else float("inf")
        bl = b[j - 1] if j > 0 else float("-inf")
        br = b[j] if j < n else float("inf")
        if al <= br and bl <= ar:
            left = max(al, bl)
            return float(left) if (m + n) % 2 else (left + min(ar, br)) / 2
        if al > br:
            hi = i - 1
        else:
            lo = i + 1
''',
    "classic-word-break": '''
from functools import lru_cache
def word_break(s, words):
    ws = set(words)
    @lru_cache(None)
    def go(i):
        if i == len(s):
            return [[]]
        out = []
        for j in range(i + 1, len(s) + 1):
            if s[i:j] in ws:
                out += [[s[i:j]] + rest for rest in go(j)]
        return out
    return sorted(" ".join(x) for x in go(0)) if s else []
''',
    "classic-sql-window": '''
def top_reps_sql():
    return """
    with t as (select region, rep, sum(amount) as total from sales group by region, rep),
         r as (select region, rep, total, dense_rank() over (partition by region order by total desc) as rnk from t)
    select region, rep, total, rnk from r where rnk <= 2 order by region, rnk, rep
    """
''',
    "classic-regex-duration": '''
import re
def parse_duration(s):
    if not re.fullmatch(r"\\d+[dhms](?: ?\\d+[dhms])*", s, re.I):
        raise ValueError(s)
    units = re.findall(r"(\\d+)([dhms])", s, re.I)
    seen = ["dhms".index(u.lower()) for _, u in units]
    if seen != sorted(set(seen)):  # strictly increasing: in order, each unit once
        raise ValueError(s)
    mult = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return sum(int(n) * mult[u.lower()] for n, u in units)
''',
    "classic-deadlock-fix": '''
import threading

class Account:
    def __init__(self, balance):
        self.balance = balance
        self.lock = threading.Lock()

def transfer(a, b, amount):
    if a is b:
        with a.lock:
            return a.balance >= amount
    first, second = (a, b) if id(a) < id(b) else (b, a)
    with first.lock:
        with second.lock:
            if a.balance < amount:
                return False
            a.balance -= amount
            b.balance += amount
            return True
''',
}

BAD = {  # plausible wrong answers each question's tests must catch
    "classic-median-two": "def median_two(a, b):\n    m = sorted(a + b)\n    return float(m[len(m) // 2])",
    "classic-word-break": '''
def word_break(s, words):  # greedy: finds at most one split
    out, i = [], 0
    while i < len(s):
        w = next((w for w in sorted(words, key=len, reverse=True) if s.startswith(w, i)), None)
        if w is None:
            return []
        out.append(w)
        i += len(w)
    return [" ".join(out)]
''',
    "classic-sql-window": '''
def top_reps_sql():
    return "select region, rep, sum(amount) as total, rank() over (partition by region order by sum(amount) desc) as rnk " \\
           "from sales group by region, rep order by region, rnk, rep"
''',
    "classic-regex-duration": '''
import re
def parse_duration(s):
    units = re.findall(r"(\\d+)([dhms])", s, re.I)
    if not units:
        raise ValueError(s)
    return sum(int(n) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[u.lower()] for n, u in units)
''',
    "classic-deadlock-fix": classics.BUGGY_TRANSFER,
}

Q = {q["id"]: q for q in classics.CLASSICS}


@pytest.mark.parametrize("qid", sorted(Q))
def test_classic_tests_accept_a_correct_answer(qid):
    assert grade.grade(Q[qid], F.format(GOOD[qid])) == 1


@pytest.mark.parametrize("qid", sorted(Q))
def test_classic_tests_reject_a_wrong_answer(qid):
    assert grade.grade(Q[qid], F.format(BAD[qid])) == 0


def test_summary_counts_recovery_and_wrong_served():
    import summary as H
    assert H.pct([3, 1, 2, 4], 0.5) == 2 and H.pct([3, 1, 2, 4], 0.9) == 4 and H.pct([], 0.5) == 0.0
    qs = [{"id": i} for i in "abcd"]
    rows = {
        "PLAIN": [{"id": "a", "grade": 1, "tier": "gpu-small"}, {"id": "b", "grade": 0, "tier": "gpu-small"},
                  {"id": "c", "grade": 0, "tier": "gpu-small"}, {"id": "d", "grade": 1, "tier": "gpu-small"}],
        "POOL": [{"id": "a", "grade": 1, "tier": "gpu-small"}, {"id": "b", "grade": 1, "tier": "cloud-deepseek", "climbed": True},
                 {"id": "c", "grade": 0, "tier": "cloud-deepseek", "climbed": True}, {"id": "d", "grade": 1, "tier": "bank"}],
    }
    s = H.recovery(qs, rows["PLAIN"], rows["POOL"])
    assert s == {"plain_missed": 2, "ladder_recovered": 1, "ladder_still_wrong": 1, "ladder_lost": 0,
                 "wrong_no_climb": 0}
