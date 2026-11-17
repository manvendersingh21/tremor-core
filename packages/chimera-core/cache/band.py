"""Paraphrase help for the shared cache: prompt normalizing and the tier 0b yes/no check.

normalize_prompt("Tell me the capital of France, please!") == normalize_prompt("What is the capital of France?")
== "capital of france". The cache compares normalized prompts as well as raw ones (pgvector_cache.py).

A cosine score in the middle band (band_low <= score < threshold) is served only when the guard passes AND, if a
checker is set, the self-hosted 30B answers YES to "does the cached answer fully answer the new question?".
Measured in bench/results_paraphrase_cache.md.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Callable

log = logging.getLogger("chimera.band")

# Polite lead-ins that do not change what is asked. Stripped from the start, longest first, again and again.
LEAD = sorted([
    "please", "kindly", "hey", "hi", "hello", "ok", "okay", "so", "quick question", "question",
    "can you", "could you", "would you", "will you", "can u", "could u", "pls", "plz",
    "tell me", "let me know", "i want to know", "i would like to know", "id like to know", "i wonder",
    "do you know", "show me", "give me", "what is", "whats", "what are", "what re",
], key=len, reverse=True)
TAIL = sorted(["please", "pls", "plz", "thanks", "thank you", "thx"], key=len, reverse=True)
ARTICLES = ("the ", "a ", "an ")
# Letters, digits, decimals and math operators survive: "2+2" and "2-2" must stay different.
_KEEP = re.compile(r"\d+(?:[.,]\d+)*|[a-z0-9]+|[+\-*/=<>%^]")


def normalize_prompt(text: str) -> str:
    """Lowercase, drop punctuation and apostrophes, strip polite lead-ins and tails. Idempotent."""
    s = " ".join(_KEEP.findall(text.lower().replace("'", "").replace("\u2019", "")))
    changed = True
    while changed:
        changed = False
        for p in LEAD:
            if s == p or s.startswith(p + " "):
                s, changed = s[len(p):].lstrip(), True
                break
        for p in TAIL:
            if s.endswith(" " + p):
                s, changed = s[: -len(p)].rstrip(), True
                break
        for a in ARTICLES:
            if s.startswith(a):
                s, changed = s[len(a):], True
                break
    return s


# The stricter of two wordings measured (bench/results_paraphrase_cache.md): the first, "Does the answer to A fully
# and correctly answer question B?", said YES to "raw chicken" vs "cooked chicken".
CHECK_PROMPT = ("Question A: {old}\nAnswer to A: {answer}\nQuestion B: {new}\n"
                "Is question B asking for exactly the same information as question A, so that the answer to A is a "
                "complete and correct answer to B? Reply with one word: YES or NO.")


def make_checker(complete: Callable[[str, int], str], *, max_answer_chars: int = 800, cooldown_s: float = 60.0,
                 usage: Callable[[], dict] | None = None, clock: Callable[[], float] = time.monotonic):
    """(new_q, old_q, old_answer) -> (ok, info). Any error, timeout or reply other than YES is a NO.

    complete(prompt, max_tokens) -> text: the 30B backend. After an error the check is skipped (NO) for cooldown_s,
    so a dead tunnel costs one timeout, not one per lookup.
    shortcut: the cached answer is cut to max_answer_chars; long code answers are judged on their start only.
    """
    state = {"down_until": 0.0}

    def check(new: str, old: str, answer: str) -> tuple[bool, dict]:
        if clock() < state["down_until"]:
            return False, {"verdict": "skipped"}
        t0 = time.perf_counter()
        try:
            reply = complete(CHECK_PROMPT.format(old=old, answer=answer[:max_answer_chars], new=new), 3)
        except Exception as e:  # noqa: BLE001  never serve on a failed check
            state["down_until"] = clock() + cooldown_s
            log.warning("cache check failed: %s", type(e).__name__)
            return False, {"verdict": "error", "error": type(e).__name__, "ms": round((time.perf_counter() - t0) * 1000, 1)}
        ok = re.sub(r"[^A-Z]", "", (reply or "").upper()).startswith("YES")
        info = {"verdict": "yes" if ok else "no", "ms": round((time.perf_counter() - t0) * 1000, 1)}
        u = usage() if usage else {}
        info["tokens_in"], info["tokens_out"] = int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))
        return ok, info

    return check
