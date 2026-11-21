"""Head to head: huggingface/pybot (rules only) vs our skeleton apps (cache, then Crusoe 763B; no GPU).

    python skeleton/bench/vs_pybot.py pybot  helpdesk|coder     # needs the PyBot clone in bench/.scratch/pybot/repo
    python skeleton/bench/vs_pybot.py ours   helpdesk|coder [--rules]   # live: Supabase cache + Crusoe, keys from .env
    python skeleton/bench/vs_pybot.py judge                      # Crusoe grades the help-desk answers
    python skeleton/bench/vs_pybot.py report                     # markdown tables from the rows

Same question list for both systems. Rows (one JSON per ask) go to bench/.scratch/pybot/<system>_<app>.jsonl, and a
rerun skips ids already there. PyBot is third-party code: it runs in a child process with an empty environment (no keys,
no network use), one process per question, so no turn sees another turn's memory.
Help desk: Crusoe judges each answer (correct / miss / wrong) against the knowledge base. Code: unit tests judge.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import random
import re
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SCRATCH = ROOT / "bench/.scratch/pybot"
PYBOT = SCRATCH / "repo"
QUESTIONS = ROOT / "skeleton/apps/helpdesk/questions.json"

# ---- help-desk set: 60 asks ------------------------------------------------------------------------------------
GENERAL = [  # what PyBot is built for: small talk and everyday facts. `expect` tells the judge what is right.
    ("hi there", "a friendly greeting"),
    ("thanks, that helped!", "a polite you're-welcome"),
    ("bye", "a goodbye"),
    ("What is the capital of France?", "Paris"),
    ("How long should I boil an egg?", "about 8 to 12 minutes for hard-boiled (or 3 to 6 soft)"),
    ("Why is the sky blue?", "Rayleigh scattering: air scatters short blue light more than red"),
    ("Who wrote Romeo and Juliet?", "William Shakespeare"),
]


def helpdesk_set(seed: int = 7) -> list[dict]:
    """30 asks of 14 seed questions (asked, then asked again), 15 reworded, 10 new, 7 general. First asks come first."""
    rng = random.Random(seed)
    q = json.loads(QUESTIONS.read_text())
    seeds = rng.sample(q["seed"], 14)
    first = [{"q": s, "kind": "seed", "means": s} for s in seeds]
    first += [{"q": s, "kind": "novel", "means": s} for s in q["novel"]]
    first += [{"q": s, "kind": "general", "means": s, "expect": e} for s, e in GENERAL]
    later = [{"q": s, "kind": "repeat", "means": s} for s in seeds]
    later += [{"q": p, "kind": "reworded", "means": s} for p, s in q["paraphrases"]]
    rng.shuffle(first)
    rng.shuffle(later)
    rows = first + later
    for i, r in enumerate(rows):
        r["id"] = f"h{i:02d}"
    return rows


# ---- coder set: 40 asks = 10 problems x (original, repeat, 2 rewordings) -----------------------------------------
PROBLEMS = [  # (function, wording 1, wording 2, wording 3, tests as [args, expected])
    ("is_palindrome", "Write a Python function is_palindrome(s) that returns True if the string s reads the same forwards and backwards, ignoring case.",
     "Python: define is_palindrome(s). It should be True when s is the same reversed, not caring about upper or lower case.",
     "I need is_palindrome(s) in Python; True for a palindrome (case does not matter), otherwise False.",
     [(["Level"], True), (["abc"], False), (["a"], True), (["Aa"], True), ([""], True)]),
    ("fizzbuzz", "Write a Python function fizzbuzz(n) that returns a list of strings for 1..n: 'Fizz' for multiples of 3, 'Buzz' for multiples of 5, 'FizzBuzz' for both, else the number as a string.",
     "Python function fizzbuzz(n): for each number 1 to n give 'Fizz' (divisible by 3), 'Buzz' (by 5), 'FizzBuzz' (both) or the number as text. Return a list.",
     "Please write fizzbuzz(n) in Python that returns a list: numbers 1..n as strings, with Fizz, Buzz and FizzBuzz rules.",
     [([5], ["1", "2", "Fizz", "4", "Buzz"]), ([15], None), ([0], [])]),
    ("count_vowels", "Write a Python function count_vowels(s) that returns how many vowels (a, e, i, o, u, any case) are in the string s.",
     "Python: count_vowels(s) should give the number of a, e, i, o, u letters in s, upper or lower case.",
     "Define count_vowels(s) in Python returning the count of vowels in s (case-insensitive).",
     [(["Hello"], 2), (["xyz"], 0), (["AEIOU"], 5), ([""], 0)]),
    ("factorial", "Write a Python function factorial(n) that returns n! for a non-negative integer n, and raises ValueError if n is negative.",
     "Python: factorial(n) returns n factorial; for a negative n it must raise ValueError.",
     "Give me factorial(n) in Python. n >= 0 returns n!, a negative n raises ValueError.",
     [([0], 1), ([5], 120), ([10], 3628800)]),
    ("two_sum", "Write a Python function two_sum(nums, target) that returns the indices [i, j] with i < j of two numbers in nums adding up to target, or None if there are none.",
     "Python: two_sum(nums, target) gives [i, j], i < j, where nums[i] + nums[j] == target; return None when no pair exists.",
     "I need two_sum(nums, target) in Python returning the two indices (smaller first) whose values sum to target, else None.",
     [([[2, 7, 11, 15], 9], [0, 1]), ([[3, 2, 4], 6], [1, 2]), ([[1, 2], 10], None)]),
    ("merge_sorted", "Write a Python function merge_sorted(a, b) that merges two sorted lists of numbers into one new sorted list.",
     "Python: merge_sorted(a, b) takes two sorted lists and returns a single sorted list with all items.",
     "Define merge_sorted(a, b) in Python: combine two already-sorted lists into one sorted list.",
     [([[1, 3], [2, 4]], [1, 2, 3, 4]), ([[], [1]], [1]), ([[1, 1], [1]], [1, 1, 1]), ([[], []], [])]),
    ("word_count", "Write a Python function word_count(text) that returns a dict mapping each lowercase word in text to how many times it appears. Words are separated by whitespace.",
     "Python: word_count(text) returns a dictionary of lowercase word -> count, splitting on whitespace.",
     "I want word_count(text) in Python giving a dict of how often each word occurs (lowercased, split on spaces).",
     [(["a b a"], {"a": 2, "b": 1}), (["A a"], {"a": 2}), ([""], {})]),
    ("fib", "Write a Python function fib(n) that returns the n-th Fibonacci number with fib(0) = 0 and fib(1) = 1.",
     "Python: fib(n) gives the n-th Fibonacci number, where fib(0) is 0 and fib(1) is 1.",
     "Define fib(n) in Python for Fibonacci numbers, starting fib(0)=0, fib(1)=1.",
     [([0], 0), ([1], 1), ([10], 55), ([30], 832040)]),
    ("flatten", "Write a Python function flatten(x) that flattens a list nested to any depth into one flat list, keeping order.",
     "Python: flatten(x) turns a list with lists inside lists (any depth) into one flat list in the same order.",
     "I need flatten(x) in Python: nested lists of any depth in, one flat ordered list out.",
     [([[1, [2, [3, 4]], 5]], [1, 2, 3, 4, 5]), ([[]], []), ([[[], [[]]]], [])]),
    ("is_prime", "Write a Python function is_prime(n) that returns True if the integer n is prime, else False. 0, 1 and negatives are not prime.",
     "Python: is_prime(n) is True for prime integers; 0, 1 and negative numbers are not prime.",
     "Define is_prime(n) in Python: True when n is a prime number, False for everything else including 0, 1 and negatives.",
     [([2], True), ([1], False), ([97], True), ([91], False), ([-7], False)]),
]


def _fizz(n: int) -> list[str]:
    return ["FizzBuzz" if i % 15 == 0 else "Fizz" if i % 3 == 0 else "Buzz" if i % 5 == 0 else str(i) for i in range(1, n + 1)]


def coder_set(seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    firsts = [{"fn": p[0], "q": p[1], "kind": "seed"} for p in PROBLEMS]
    later = [{"fn": p[0], "q": p[1], "kind": "repeat"} for p in PROBLEMS]
    later += [{"fn": p[0], "q": w, "kind": "reworded"} for p in PROBLEMS for w in p[2:4]]
    rng.shuffle(firsts)
    rng.shuffle(later)
    rows = firsts + later
    for i, r in enumerate(rows):
        r["id"] = f"c{i:02d}"
    return rows


def run_tests(code: str, fn: str) -> tuple[bool, str]:
    """Run the problem's unit tests on the code in a child process with a timeout. True only when all pass."""
    tests = next(p[4] for p in PROBLEMS if p[0] == fn)
    tests = [(a, _fizz(a[0]) if (fn == "fizzbuzz" and e is None) else e) for a, e in tests]
    harness = (f"{code}\n\nimport json, sys\nT = json.loads(sys.stdin.read())\nbad = []\nfor a, e in T:\n"
               f"    try:\n        r = {fn}(*a)\n    except Exception as x:\n        r = 'raised ' + type(x).__name__\n"
               "    r = list(r) if isinstance(r, tuple) else r\n    if r != e:\n        bad.append([a, e, r])\n")
    if fn == "factorial":  # a negative n must raise ValueError
        harness += ("try:\n    factorial(-1)\n    bad.append('no ValueError')\nexcept ValueError:\n    pass\n"
                    "except Exception as x:\n    bad.append(type(x).__name__)\n")
    harness += "print(json.dumps(bad))\nsys.exit(1 if bad else 0)\n"
    with tempfile.TemporaryDirectory() as d:
        f = pathlib.Path(d) / "t.py"
        f.write_text(harness)
        try:
            p = subprocess.run([sys.executable, str(f)], input=json.dumps(tests), capture_output=True, text=True,
                               timeout=10, cwd=d, env={"PATH": os.environ.get("PATH", "")})
        except subprocess.TimeoutExpired:
            return False, "timeout"
    return p.returncode == 0, (p.stdout + p.stderr)[-300:]


def code_of(answer: str) -> str:
    m = re.findall(r"```(?:python|py)?\n(.*?)```", answer, re.S)
    return max(m, key=len) if m else answer


# ---- rows --------------------------------------------------------------------------------------------------------
def _done(path: pathlib.Path) -> set[str]:
    return {json.loads(l)["id"] for l in path.read_text().splitlines() if l.strip()} if path.exists() else set()


def _append(path: pathlib.Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")


def _rows(path: pathlib.Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def pybot_reply(text: str, timeout: int = 120) -> tuple[str, float | None, str]:
    """(reply, PyBot's own turn time in ms, module). Child process, empty environment, cwd = the clone."""
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "PYTHONDONTWRITEBYTECODE": "1"}
    p = subprocess.run([sys.executable, "-m", "pybot", "-s", "0", "-v", "-p", text], cwd=PYBOT, env=env,
                       capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    m = re.search(r"\[module: (.*?) \| (\d+) ms\]", p.stderr + p.stdout)
    return p.stdout.split("\n[module")[0].strip(), (float(m.group(2)) if m else None), (m.group(1) if m else "")


def run_pybot(app: str) -> None:
    out = SCRATCH / f"pybot_{app}.jsonl"
    done = _done(out)
    for r in helpdesk_set() if app == "helpdesk" else coder_set():
        if r["id"] in done:
            continue
        t0 = time.perf_counter()
        reply, ms, module = pybot_reply(r["q"])
        row = {**r, "system": "pybot", "answer": reply, "ms": ms, "wall_ms": round((time.perf_counter() - t0) * 1000),
               "module": module, "dollars": 0.0, "tokens": 0, "cache_hit": False}
        if app == "coder":
            row["pass"], row["test_out"] = run_tests(code_of(reply), r["fn"])
        _append(out, row)
        print(row["id"], row["module"], row["ms"], flush=True)


CODER_INSTRUCTIONS = ("You write Python for students. Reply with one ```python code block that defines the requested function "
                      "and nothing else. No prints, no input(), no explanation.")


def run_ours(app: str, rules: bool, namespace: str | None = None) -> None:
    tag = "ours_rules" if rules else "ours"
    out = SCRATCH / f"{tag}_{app}.jsonl"
    done = _done(out)
    ns = namespace or f"pybot-bench-{app}-{tag}-{(SCRATCH / 'run_id').read_text().strip()}"
    if app == "helpdesk":
        from skeleton.apps.helpdesk import helpdesk as hd
        bot = hd.make_assistant(live=True, no_gpu=True, rules=rules)
        inner = getattr(bot, "bot", bot)
        inner.cfg.namespace = ns  # fresh cache rows for this run: the first asker pays, the rest hit
        rows = helpdesk_set()
    else:
        from skeleton.core import Assistant
        bot = Assistant({"mode": "live", "namespace": ns, "ladder": ["cloud-deepseek"], "max_tokens": 700,
                         "instructions": CODER_INSTRUCTIONS})
        rows = coder_set()
    for r in rows:
        if r["id"] in done:
            continue
        verify = (lambda ans, fn=r.get("fn"): run_tests(code_of(ans), fn)[0]) if app == "coder" else None
        try:
            a = bot.ask(r["q"], verify=verify)
        except Exception as e:  # noqa: BLE001  a tier outage is a row, not a crash
            _append(out, {**r, "system": tag, "answer": "", "error": type(e).__name__, "ms": None, "dollars": 0.0,
                          "tokens": 0, "cache_hit": False, "tier": "error"})
            continue
        row = {**r, "system": tag, "answer": a["answer"], "ms": a["latency_ms"], "dollars": a["dollars"], "tokens": a["tokens"],
               "cache_hit": a["cache_hit"], "tier": a["tier"], "tried": a["tried"], "verified": a["verified"]}
        if app == "coder":
            row["pass"], row["test_out"] = run_tests(code_of(a["answer"]), r["fn"])
        _append(out, row)
        print(row["id"], row["tier"], row["ms"], flush=True)


# ---- judge (help desk) ----------------------------------------------------------------------------------------------
JUDGE = """You grade a customer-support chatbot. Facts the company published (may be unrelated to the question):
{kb}

Question: {q}
{expect}Chatbot answer: {a}

Grade with ONE word:
CORRECT: the answer is right and addresses the question. If the published facts do not cover the question, an honest 'I don't know' / hand-off to a person is CORRECT, and an invented specific answer is WRONG.
MISS: the facts DO answer the question but the chatbot did not give it (it said it cannot help, deflected, or answered a different thing without a false claim).
WRONG: the answer states something false, contradicts the facts, or invents details.
Reply with the single word only."""


def judge(app: str = "helpdesk") -> None:
    import skeleton.core  # noqa: F401  registers chimera_core
    from chimera_core.config import load_config
    load_config()  # reads .env into the environment (never printed)
    from chimera_core.inference.cloud_verifier import CrusoeBackend
    from skeleton.apps.helpdesk.helpdesk import KnowledgeBase
    kb = KnowledgeBase().text
    be = CrusoeBackend("deepseek-ai/DeepSeek-V4.1-Flash")
    for path in sorted(SCRATCH.glob(f"*_{app}.jsonl")):
        rows, changed = _rows(path), False
        for r in rows:
            if r.get("grade") in ("CORRECT", "MISS", "WRONG") and not (
                    r["kind"] == "general" and r["grade"] == "CORRECT" and re.search(r"\bi don'?t know\b", r["answer"], re.I)):
                continue
            general = r["kind"] == "general"
            if general and re.search(r"\bi don'?t know\b", r["answer"], re.I):  # no judge call: an abstention is a miss
                r["grade"], r["judge_tokens"], changed = "MISS", 0, True
                continue
            prompt = JUDGE.format(kb="(not about this question: judge general correctness)" if general else kb, q=r["q"],
                                  expect=f"Right answer: {r['expect']}\n" if general else "", a=r["answer"] or "(no answer)")
            word = be.complete(prompt, max_tokens=1200).strip().upper()
            r["grade"] = next((w for w in ("CORRECT", "MISS", "WRONG") if w in word), "UNGRADED")
            r["judge_tokens"] = sum(be.last_usage.get(k, 0) for k in ("prompt_tokens", "completion_tokens"))
            changed = True
        if changed:
            path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        print(path.name, "graded")


# ---- report -----------------------------------------------------------------------------------------------------------
def _p50(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def summarize(rows: list[dict], app: str) -> dict:
    n = len(rows)
    out = {"n": n, "hit": sum(bool(r.get("cache_hit")) for r in rows), "rules": sum(r.get("tier") == "rules" for r in rows),
           "dollars": sum(r.get("dollars", 0.0) for r in rows), "tokens": sum(r.get("tokens", 0) for r in rows),
           "p50_ms": _p50([r.get("ms") for r in rows]), "errors": sum(r.get("tier") == "error" for r in rows)}
    out["per_1000"] = round(out["dollars"] / n * 1000, 4) if n else 0.0
    if app == "coder":
        out["correct"] = sum(bool(r.get("pass")) for r in rows)
        out["wrong"] = n - out["correct"]
        out["miss"] = 0
    else:
        g = [r.get("grade") for r in rows]
        out["correct"], out["miss"], out["wrong"] = g.count("CORRECT"), g.count("MISS"), g.count("WRONG")
    return out


def fmt_row(name: str, s: dict, app: str) -> str:
    n = s["n"]
    extra = f" ({s['rules']} by rules)" if s["rules"] else ""
    return (f"| {name} | {s['correct']}/{n} | {s['wrong']}{'' if app == 'coder' else f' (+{s['miss']} missed)'} | "
            f"{s['hit']}/{n}{extra} | {s['p50_ms']} | ${s['per_1000']:.2f} |")


def report() -> str:
    parts = []
    for app in ("helpdesk", "coder"):
        head = ["| System | Correct | Wrong | Cache hits | Median ms | $ per 1,000 asks |", "|---|---|---|---|---|---|"]
        lines, groups = [], []
        for tag, name in (("pybot", "PyBot"), ("ours", "Skeleton (cache, then 763B)"), ("ours_rules", "Skeleton + rules first")):
            rows = _rows(SCRATCH / f"{tag}_{app}.jsonl")
            if rows:
                lines.append(fmt_row(name, summarize(rows, app), app))
                groups.append((name, rows))
        parts += [f"### {app}", "", *head, *lines, ""]
        kinds = ["seed", "repeat", "reworded", "novel", "general"] if app == "helpdesk" else ["seed", "repeat", "reworded"]
        key = (lambda r: r.get("grade") == "CORRECT") if app == "helpdesk" else (lambda r: bool(r.get("pass")))
        parts += ["Correct by kind of ask:", "", "| System | " + " | ".join(kinds) + " |", "|---|" + "---|" * len(kinds)]
        for name, rows in groups:
            cells = []
            for k in kinds:
                sub = [r for r in rows if r["kind"] == k]
                cells.append(f"{sum(map(key, sub))}/{len(sub)}" if sub else "-")
            parts.append(f"| {name} | " + " | ".join(cells) + " |")
        parts.append("")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pybot", "ours", "judge", "report"])
    ap.add_argument("app", nargs="?", default="helpdesk", choices=["helpdesk", "coder"])
    ap.add_argument("--rules", action="store_true")
    a = ap.parse_args(argv)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    rid = SCRATCH / "run_id"
    if not rid.exists():
        rid.write_text(str(int(time.time())))
    if a.cmd == "pybot":
        run_pybot(a.app)
    elif a.cmd == "ours":
        run_ours(a.app, a.rules)
    elif a.cmd == "judge":
        judge(a.app)
    else:
        md = report()
        (SCRATCH / "results.md").write_text(md)
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
