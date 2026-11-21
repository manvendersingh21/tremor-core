"""The coder for a class: many students ask the same things, so the first one pays and the rest get the cache.

Two kinds of student question, both on the same skeleton:
- assignment: "Assignment 3: write is_palindrome(s) in palindrome.py". Coder.ask with the starter files as context
  and the assignment tests as the check. A patch is cached only after its tests pass, and the tests run again on
  every cached patch before a student sees it.
- reading: "Summarize this paper". Assistant.ask with the paper as context. The check: the summary is short and
  every number in it is in the text.

Other wording reaches the cached answer only through the cache's own rules: the same words after normalizing
(case, punctuation, "please", "can you"), or cosine >= 0.97 that the guard passes (same numbers, names, no added
"not"/"without"). Anything else is a new question and goes to the models.

    python -m skeleton.apps.coder class            # demo: 5 students per item, stub models
"""
from __future__ import annotations

import pathlib
import random
import re
import shlex
import sys
import tempfile
import tomllib

from skeleton.core import Assistant

from .coder import CONFIG, Coder

HERE = pathlib.Path(__file__).resolve().parent / "classroom"
PY = shlex.quote(sys.executable)
SUMMARY_RULES = ("Summarize the text below for a student in at most four short sentences. Use only facts from the "
                 "text. Answer the student's question about it.")

ASSIGNMENTS = {
    "a3-palindrome": {
        "file": "palindrome.py",
        "starter": 'def is_palindrome(s):\n    """Assignment 3: True if s reads the same both ways, ignoring case, '
                   'spaces and punctuation."""\n    raise NotImplementedError\n',
        "tests": "from palindrome import is_palindrome\nassert is_palindrome('Never odd or even')\n"
                 "assert is_palindrome('A man, a plan, a canal: Panama')\nassert not is_palindrome('assignment')\n"
                 "assert is_palindrome('')\n",
        "good": "    t = [c.lower() for c in s if c.isalnum()]\n    return t == t[::-1]",
        "bad": None,
        "questions": [("Assignment 3: write is_palindrome(s) in palindrome.py", "same"),
                      ("assignment 3: write is_palindrome(s) in palindrome.py", "same"),
                      ("Please write is_palindrome(s) in palindrome.py, assignment 3", "reworded"),
                      ("Can you write is_palindrome(s) in palindrome.py for assignment 3?", "reworded"),
                      ("Assignment 3: write is_palindrome(s) in palindrome.py without slicing", "different")],
    },
    "a4-fizzbuzz": {
        "file": "fizzbuzz.py",
        "starter": 'def fizzbuzz(n):\n    """Assignment 4: the strings for 1..n: "Fizz" for multiples of 3, "Buzz" for 5, '
                   '"FizzBuzz" for both, else the number."""\n    raise NotImplementedError\n',
        "tests": "from fizzbuzz import fizzbuzz\nassert fizzbuzz(5) == ['1', '2', 'Fizz', '4', 'Buzz']\n"
                 "assert fizzbuzz(15)[-1] == 'FizzBuzz'\nassert fizzbuzz(0) == []\n",
        "good": "    return ['FizzBuzz' if i % 15 == 0 else 'Fizz' if i % 3 == 0 else 'Buzz' if i % 5 == 0 else str(i)\n"
                "            for i in range(1, n + 1)]",
        "bad": "    return ['FizzBuzz' if i % 15 == 0 else 'Fizz' if i % 3 == 0 else 'Buzz' if i % 5 == 0 else str(i)\n"
               "            for i in range(n)]",  # the demo 30B's off-by-one: tests fail, the task climbs
        "questions": [("Assignment 4: write fizzbuzz(n) in fizzbuzz.py", "same"),
                      ("assignment 4 - write fizzbuzz(n) in fizzbuzz.py", "same"),
                      ("Could you write fizzbuzz(n) in fizzbuzz.py for assignment 4", "reworded"),
                      ("Assignment 4: write fizzbuzz(n) in fizzbuzz.py and explain it", "different")],
    },
    "a5-wordcount": {
        "file": "wordcount.py",
        "starter": 'def word_count(text):\n    """Assignment 5: a dict of lowercase word -> count; punctuation is not '
                   'part of a word."""\n    raise NotImplementedError\n',
        "tests": "from wordcount import word_count\nassert word_count('The cat, the hat.') == {'the': 2, 'cat': 1, 'hat': 1}\n"
                 "assert word_count('') == {}\n",
        "good": "    import re\n    out = {}\n    for w in re.findall(r\"[a-z']+\", text.lower()):\n"
                "        out[w] = out.get(w, 0) + 1\n    return out",
        "bad": None,
        "questions": [("Assignment 5: write word_count(text) in wordcount.py", "same"),
                      ("Assignment 5: Write word_count(text) in wordcount.py.", "same"),
                      ("please write word_count(text) in wordcount.py for assignment 5", "reworded")],
    },
}
READINGS = {
    "paper": {"file": "paper.md",
              "questions": [("Summarize this paper", "same"), ("summarize this paper.", "same"),
                            ("Please summarize this paper", "reworded"), ("Can you summarize this paper?", "reworded"),
                            ("Give me a summary of this paper", "reworded"),
                            ("What are the main findings of this paper?", "different"),
                            ("Summarize this paper in 3 bullet points", "different")]},
    "chapter": {"file": "chapter.md",
                "questions": [("Summarize this chapter", "same"), ("Summarize this chapter!", "same"),
                              ("Could you summarize this chapter", "reworded"),
                              ("What is the most common bug in this chapter's method?", "different")]},
}
WEIGHTS = {"a3-palindrome": 30, "a4-fizzbuzz": 20, "a5-wordcount": 15, "paper": 25, "chapter": 10}
KIND = {"same": 70, "reworded": 20, "different": 10}  # most students paste the assignment line as given


def text(reading: str) -> str:
    return (HERE / READINGS[reading]["file"]).read_text()


def summary_ok(summary: str, source: str) -> bool:
    """Short, sure, and every number in it appears in the source text."""
    nums = set(re.findall(r"\d[\d,.]*\d|\d", source))
    body = re.sub(r"(?m)^\s*\d+[.)]\s+", "", summary)  # list markers "1." are not facts
    return (bool(summary.strip()) and len(summary) < len(source) / 2 and "i don't know" not in summary.lower()
            and all(n in nums for n in re.findall(r"\d[\d,.]*\d|\d", body)))


# ---- demo stand-ins for the 30B and the 763B -------------------------------------------------------------
def _sentences(src: str) -> list[str]:
    body = "\n".join(line for line in src.splitlines() if line.strip() and not line.startswith(("#", "*")))
    return re.split(r"(?<=[.!?])\s+", body.strip())


def _coding(prompt: str, big: bool) -> str:
    for a in ASSIGNMENTS.values():
        if f"FILE: {a['file']}" in prompt:
            body = a["good"] if big or not a["bad"] else a["bad"]
            if "without slicing" in prompt.rsplit("Question:", 1)[-1]:
                body = body.replace("t == t[::-1]", "t == list(reversed(t))")
            head = a["starter"].rsplit("    raise NotImplementedError", 1)[0]
            return f"FILE: {a['file']}\n{head}{body}\nEND FILE"
    return ""


def _summary(prompt: str) -> str:
    q = prompt.rsplit("Question:", 1)[-1].lower()
    s = _sentences(prompt.rsplit("Question:", 1)[0].split("\n\n", 1)[-1])
    if "finding" in q:
        return " ".join(x for x in s if x.startswith(("Bees near", "We found")))
    if "bug" in q:
        return next((x for x in s if "bug" in x), "")
    if "bullet" in q:
        return "\n".join("- " + x for x in s[1:4])
    return " ".join([s[0], s[-1]])


def demo_models(big: bool):
    return lambda p: _coding(p, big) if "FILE: " in p else _summary(p)


DEMO_MODELS = {"gpu-small": demo_models(False), "cloud-deepseek": demo_models(True)}


# ---- one class ------------------------------------------------------------------------------------------
class Classroom:
    """One shared cache for the whole class: an assignment bot (the coder) and a reading bot."""

    def __init__(self, live: bool = False, root: pathlib.Path | None = None, no_gpu: bool = False) -> None:
        base = tomllib.loads(CONFIG.read_text())
        mode: dict = {"mode": "live"} if live else {}
        if no_gpu:
            mode["ladder"] = ["cloud-deepseek"]
        self.coder_bot = Assistant({**base, **mode, "namespace": "skeleton-class-code"}, demo_models=DEMO_MODELS)
        self.read_bot = Assistant({**base, **mode, "namespace": "skeleton-class-read", "instructions": SUMMARY_RULES,
                                   "max_tokens": 400}, demo_models=DEMO_MODELS)
        self._tmp = None if root else tempfile.TemporaryDirectory(prefix="skeleton-class-")
        self.root = root or pathlib.Path(self._tmp.name)
        self.repos: dict[str, pathlib.Path] = {}

    def repo(self, name: str) -> pathlib.Path:
        """The starter repo every student gets (same files, so the same cache section)."""
        if name not in self.repos:
            a, r = ASSIGNMENTS[name], self.root / name
            r.mkdir(parents=True, exist_ok=True)
            (r / a["file"]).write_text(a["starter"])
            (r / "check.py").write_text(a["tests"])
            self.repos[name] = r
        return self.repos[name]

    def ask(self, item: str, question: str) -> dict:
        if item in ASSIGNMENTS:
            return Coder(self.repo(item), [ASSIGNMENTS[item]["file"]], f"{PY} check.py",
                         assistant=self.coder_bot).ask(question).answer
        src = text(item)
        return self.read_bot.ask(question, context=src, verify=lambda s: summary_ok(s, src))

    def stats(self) -> dict:
        a, b = self.coder_bot.stats(), self.read_bot.stats()
        keys = ("questions", "cache_hits", "exact", "cosine", "model_calls", "climbs", "unverified", "tokens",
                "tokens_saved", "dollars", "dollars_saved")
        s = {k: a[k] + b[k] for k in keys}
        s["hit_rate"] = round(s["cache_hits"] / s["questions"], 4) if s["questions"] else 0.0
        return s

    def close(self) -> None:
        if self._tmp:
            self._tmp.cleanup()


def class_mix(n: int, rng: random.Random) -> list[tuple[str, str, str, str]]:
    """(item, question, kind, the question it means) for n students. No warm-up: student 1 of each pays."""
    items = list(WEIGHTS)
    out = []
    for _ in range(n):
        item = rng.choices(items, [WEIGHTS[i] for i in items])[0]
        qs = (ASSIGNMENTS.get(item) or READINGS[item])["questions"]
        kind = rng.choices(list(KIND), list(KIND.values()))[0]
        pool = [q for q, k in qs if k == kind]
        if not pool:  # this item has no question of that kind
            kind, pool = "same", [q for q, k in qs if k == "same"]
        q = rng.choice(pool)
        out.append((item, q, kind, q if kind == "different" else qs[0][0]))
    return out


def line(who: str, a: dict) -> str:
    kind = next((s["kind"] for s in a["steps"] if s.get("kind")), None)
    how = f"cache ({'cosine' if kind == 'semantic' else kind})" if a["cache_hit"] else " -> ".join(a["tried"])
    ok = {True: "checked", False: "FAILED check", None: "-"}[a["verified"]]
    return (f"  {who:<11} {how:<28} {a['tokens']:>5} tokens  spent ${a['dollars']:.6f}  "
            f"saved ${a['dollars_saved']:.6f}  {a['latency_ms']:>6.0f} ms  {ok}")


def main(live: bool = False, students: int = 5, no_gpu: bool = False) -> int:
    room = Classroom(live, no_gpu=no_gpu)
    try:
        for item, (a_name, q) in {"assignment": ("a3-palindrome", ASSIGNMENTS["a3-palindrome"]["questions"][0][0]),
                                  "reading": ("paper", READINGS["paper"]["questions"][0][0])}.items():
            print(f"\n{item}: \"{q}\" asked by {students} students")
            for i in range(1, students + 1):
                print(line(f"student {i}", room.ask(a_name, q)))
        print("\nother wording, then a really different question:")
        for a_name, q in (("a3-palindrome", "Please write is_palindrome(s) in palindrome.py, assignment 3"),
                          ("paper", "Can you summarize this paper?"),
                          ("a3-palindrome", "Assignment 3: write is_palindrome(s) in palindrome.py without slicing")):
            a = room.ask(a_name, q)
            print(f"  \"{q}\"\n{line('', a)}")
        s = room.stats()
        print(f"\n{s['questions']} questions: {s['cache_hits']} from the cache ({s['hit_rate'] * 100:.0f}%), "
              f"{s['model_calls']} model calls, {s['tokens_saved']:,} tokens kept off the 763B, "
              f"saved ${s['dollars_saved']:.6f}  ({'live' if live else 'demo: stub models'})")
    finally:
        room.close()
    return 0
