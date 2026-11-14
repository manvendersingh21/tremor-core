"""Pull 2-5 concepts and a one-line "why it works" out of a verified solution.

`llm_extractor(complete)` asks a model (the 30B itself in the benchmark; any `complete(prompt) -> str`).
`heuristic_extract` is the no-model fallback: it names concepts from the code's own constructs.
"""
from __future__ import annotations

import json
import re
from typing import Callable

PROMPT = """You label a verified solution for a memory of reusable ideas.

PROBLEM:
{problem}

SOLUTION:
{solution}

Reply with ONLY a JSON object: {{"concepts": [2 to 5 short algorithm or technique names, lowercase, e.g. "two-pointer", "sliding window", "string parsing"], "why": "one sentence on why this solution works"}}"""

_HEUR = [
    (r"\bwhile\b.*\n.*\b(left|lo|i)\b.*\b(right|hi|j)\b|\bleft\b.*\bright\b", "two-pointer"),
    (r"\bsorted\(|\.sort\(", "sorting"), (r"\brecurs|def (\w+)\(.*\n(?:.*\n)*?.*\b\1\(", "recursion"),
    (r"\bre\.(?:match|search|sub|findall|compile)", "regex"), (r"\bdict\b|\{\}|Counter|defaultdict", "hash map"),
    (r"\bset\(", "set membership"), (r"\bdeque\b|\bheapq\b", "queue or heap"), (r"%|\bmod\b|\bgcd\b", "modular arithmetic"),
    (r"\.split\(|\.join\(|\.strip\(", "string parsing"), (r"\bfor\b.*\bfor\b", "nested loops"),
    (r"\[.*\bfor\b.*\bin\b.*\]", "list comprehension"), (r"\bdp\b|\bmemo\b|lru_cache", "dynamic programming"),
    (r"\bclass\b", "class design"), (r"\bdatetime\b", "date and time"), (r"\bint\(|\bbin\(|>>|<<", "number conversion"),
]


def heuristic_extract(problem: str, solution: str) -> tuple[list[str], str]:
    found = [name for rx, name in _HEUR if re.search(rx, solution)]
    return (found[:5] or ["basic function"]), "Matches the stated behaviour; it passed the problem's tests."


def parse(text: str) -> tuple[list[str], str] | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        cs = [re.sub(r"\s+", " ", str(c).strip().lower())[:60] for c in d.get("concepts", []) if str(c).strip()]
        why = str(d.get("why", "")).strip()[:300]
    except (ValueError, AttributeError):
        return None
    return (cs[:5], why) if len(cs) >= 1 and why else None


def llm_extractor(complete: Callable[[str], str]) -> Callable[[str, str], tuple[list[str], str]]:
    def run(problem: str, solution: str) -> tuple[list[str], str]:
        try:
            got = parse(complete(PROMPT.format(problem=problem[:1500], solution=solution[:2500])))
        except Exception:  # noqa: BLE001  extractor must never block a store
            got = None
        return got or heuristic_extract(problem, solution)
    return run
