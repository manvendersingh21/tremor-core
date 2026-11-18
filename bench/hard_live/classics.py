"""Five classic moderately-hard coding asks for bench/results_hard_live.md, graded by running their tests.

The sixth classic, an LRU cache, is `multi-lru` from bench/cost_case/tasks.jsonl, so it is not repeated here.
Reference solutions that pass these tests (and the buggy code that must fail) are in tests/test_hard_live.py.
"""
from __future__ import annotations

TAIL = "\n\nReply with only the Python code in one ```python code block."


def _q(qid: str, prompt: str, tests: list[str], imports: list[str] | None = None) -> dict:
    return {"id": qid, "difficulty": "hard", "source": "classic", "prompt": prompt + TAIL, "grader": "unit_test",
            "data": {"kind": "mbpp", "imports": imports or [], "tests": tests}}


RAISES = ("for bad in {bad!r}:\n    try:\n        {call}(bad)\n    except ValueError:\n        continue\n"
          "    raise AssertionError('no ValueError for ' + repr(bad))")

BUGGY_TRANSFER = '''import threading

class Account:
    def __init__(self, balance):
        self.balance = balance
        self.lock = threading.Lock()

def transfer(a, b, amount):
    with a.lock:
        with b.lock:
            if a.balance < amount:
                return False
            a.balance -= amount
            b.balance += amount
            return True'''

CLASSICS = [
    _q("classic-median-two",
       "Write a function `median_two(a, b)` that returns the median, as a float, of all numbers in two sorted lists of "
       "integers `a` and `b`, in O(log(min(len(a), len(b)))) time without merging the lists. Either list may be empty; "
       "if both are empty raise ValueError. The lists may hold duplicates and negative numbers.",
       ["assert median_two([1, 3], [2]) == 2.0",
        "assert median_two([1, 2], [3, 4]) == 2.5",
        "assert median_two([], [5]) == 5.0",
        "assert median_two([0, 0], [0, 0]) == 0.0",
        "assert median_two([-5, -3, -1], [-2]) == -2.5",
        "assert median_two([1, 2, 3, 4, 5, 6, 7, 8], []) == 4.5",
        "try:\n    median_two([], [])\nexcept ValueError:\n    pass\nelse:\n    raise AssertionError('no ValueError')",
        "import random\nrandom.seed(7)\nfor _ in range(400):\n"
        "    a = sorted(random.randint(-50, 50) for _ in range(random.randint(0, 25)))\n"
        "    b = sorted(random.randint(-50, 50) for _ in range(random.randint(0, 25)))\n"
        "    if not a and not b:\n        continue\n"
        "    m = sorted(a + b); n = len(m)\n"
        "    want = float(m[n // 2]) if n % 2 else (m[n // 2 - 1] + m[n // 2]) / 2\n"
        "    assert median_two(a, b) == want, (a, b)"]),
    _q("classic-word-break",
       "Write a function `word_break(s, words)` that returns every way to split the string `s` into a sequence of words "
       "from the list `words` (a word may be used many times). Return the splits as strings with the words joined by "
       "single spaces, sorted alphabetically, or [] when there is none. It must finish in well under a second for "
       "strings of up to 50 characters, also when no split exists.",
       ["assert word_break('catsanddog', ['cat', 'cats', 'and', 'sand', 'dog']) == ['cat sand dog', 'cats and dog']",
        "assert word_break('pineapplepenapple', ['apple', 'pen', 'applepen', 'pine', 'pineapple']) == "
        "['pine apple pen apple', 'pine applepen apple', 'pineapple pen apple']",
        "assert word_break('catsandog', ['cats', 'dog', 'sand', 'and', 'cat']) == []",
        "assert len(word_break('a' * 12, ['a', 'aa'])) == 233",
        "assert word_break('a' * 40 + 'b', ['a' * i for i in range(1, 11)]) == []"]),
    _q("classic-sql-window",
       "Write a function `top_reps_sql()` that returns one SQLite query as a string. The table is "
       "`sales(region TEXT, rep TEXT, amount INTEGER)` with many rows per rep. The query returns the columns "
       "`region, rep, total, rnk`: each rep's total amount within their region, ranked inside the region by total "
       "from highest to lowest with DENSE_RANK (ties share a rank), keeping only rows with rnk <= 2, ordered by "
       "region, then rnk, then rep.",
       ["db = sqlite3.connect(':memory:')\n"
        "db.execute('create table sales(region text, rep text, amount integer)')\n"
        "db.executemany('insert into sales values (?, ?, ?)', [('E', 'ann', 5), ('E', 'ann', 5), ('E', 'bob', 10), "
        "('E', 'cat', 7), ('E', 'dan', 3), ('W', 'eve', 4), ('W', 'fay', 4), ('W', 'gus', 1), ('W', 'hal', 2), "
        "('N', 'ivy', 9)])\n"
        "rows = [tuple(r) for r in db.execute(top_reps_sql()).fetchall()]",
        "assert rows == [('E', 'ann', 10, 1), ('E', 'bob', 10, 1), ('E', 'cat', 7, 2), ('N', 'ivy', 9, 1), "
        "('W', 'eve', 4, 1), ('W', 'fay', 4, 1), ('W', 'hal', 2, 2)], rows"],
       imports=["import sqlite3"]),
    _q("classic-regex-duration",
       "Write a function `parse_duration(s)` that turns a duration string into a whole number of seconds, using the `re` "
       "module. A valid string is one or more parts such as `1d`, `2h`, `30m`, `15s` (days, hours, minutes, seconds): "
       "units in the order d, h, m, s, each unit at most once, at most one space between parts, letters in any case, "
       "no space at the start or end, and numbers made only of digits. Anything else (empty string, a unit twice, "
       "units out of order, an unknown unit, a number without a unit, a sign, a decimal point) raises ValueError.",
       ["assert parse_duration('1h30m') == 5400",
        "assert parse_duration('2h') == 7200",
        "assert parse_duration('45s') == 45",
        "assert parse_duration('1d 2h 3m 4s') == 93784",
        "assert parse_duration('90M') == 5400",
        "assert parse_duration('0s') == 0",
        RAISES.format(bad=['', ' 1h', '1h ', '1h1h', '1m1h', '1x', '10', '-1h', '+1h', 'h', '1h  2m', '1.5h', '1h 1h'],
                      call="parse_duration")]),
    _q("classic-deadlock-fix",
       "The code below deadlocks when two threads move money between the same two accounts in opposite directions at "
       "the same time. Fix it. Keep the `Account(balance)` class with its `balance` attribute and the "
       "`transfer(a, b, amount)` function, which returns True when the money moved and False when `a` has too little. "
       "Many threads may call transfer at once: the total must never change and no balance may go below zero. "
       "A transfer from an account to itself returns True if the balance allows it and changes nothing. "
       "Return the whole fixed code.\n\n```python\n" + BUGGY_TRANSFER + "\n```",
       ["a, b = Account(5), Account(0)",
        "assert transfer(a, b, 10) is False and a.balance == 5",
        "assert transfer(a, b, 5) is True and (a.balance, b.balance) == (0, 5)",
        "assert transfer(b, b, 1) is True and b.balance == 5",
        "sys.setswitchinterval(1e-6)\n"
        "accts = [Account(1000) for _ in range(3)]\n"
        "def worker(seed):\n    r = random.Random(seed)\n    for _ in range(2000):\n"
        "        transfer(r.choice(accts), r.choice(accts), r.randint(1, 50))\n"
        "ts = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(8)]\n"
        "for t in ts:\n    t.start()\n"
        "end = time.time() + 6\n"
        "for t in ts:\n    t.join(max(0.0, end - time.time()))\n"
        "assert not any(t.is_alive() for t in ts), 'deadlock'\n"
        "assert sum(x.balance for x in accts) == 3000\n"
        "assert all(x.balance >= 0 for x in accts)"],
       imports=["import random", "import sys", "import threading", "import time"]),
]
