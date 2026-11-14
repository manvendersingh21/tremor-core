"""Graders for bench/datasets/suite.jsonl rows. grade(row, answer) -> 1, 0, or None (not graded here).

unit_test: the answer's code runs in a subprocess with a timeout, an empty environment (no API keys), a
           scratch cwd, and no network (macOS sandbox-exec when present, plus a socket block in the child).
exact:     last number of the answer (or after "Answer:") equals the expected number.
choice:    the chosen letter equals the expected letter.
pair:      graded in run_suite.py from cache behaviour, not from text; returns None here.
llm:       graded by `llm_scores` below (a model that wrote none of the answers); returns None here.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import zlib

TIMEOUT_S = 10
SBPL = "(version 1)(allow default)(deny network*)"
SANDBOX_EXEC = shutil.which("sandbox-exec")
# sandbox-exec cannot nest (fails inside another sandbox), so use it only if a probe works.
if SANDBOX_EXEC and subprocess.run([SANDBOX_EXEC, "-p", SBPL, "true"], capture_output=True).returncode:
    SANDBOX_EXEC = None
# Runs first in the child: any socket use raises, so code that slips past sandbox-exec still has no network.
NO_NET = (
    "import socket\n"
    "def _no(*a, **k):\n    raise OSError('network disabled')\n"
    "socket.socket.connect = _no; socket.create_connection = _no; socket.getaddrinfo = _no\n"
)


def code_of(text: str) -> str:
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    return next((b for b in blocks if "def " in b), blocks[0] if blocks else text)


def run_sandboxed(source: str) -> bool:
    with tempfile.TemporaryDirectory(dir=os.environ.get("KIROCREW_SCRATCH")) as d:
        p = pathlib.Path(d) / "t.py"
        p.write_text(NO_NET + source + "\n")
        cmd = [sys.executable, "-I", str(p)]
        if SANDBOX_EXEC:
            cmd = [SANDBOX_EXEC, "-p", SBPL, *cmd]
        try:
            return subprocess.run(cmd, cwd=d, env={}, capture_output=True, timeout=TIMEOUT_S).returncode == 0
        except subprocess.TimeoutExpired:
            return False


def unit_test(data: dict, answer: str) -> int:
    code = code_of(answer)
    if data["kind"] == "humaneval":
        # The stub (imports, helpers, signature, docstring) comes first; the answer redefines the function.
        if f"def {data['entry_point']}" not in code:  # body-only answer: continue the stub
            code = data["prompt"] + code
        src = f"{data['prompt']}\n    pass\n\n{code}\n\n{data['test']}\n\ncheck({data['entry_point']})"
    else:  # mbpp
        src = "\n".join(json.loads(data["imports"]) if isinstance(data["imports"], str) else data["imports"])
        src += f"\n{code}\n\n" + "\n".join(data["tests"])
    return int(run_sandboxed(src))


def _num(s: str) -> float | None:
    s = s.replace(",", "").replace("$", "")
    try:
        return float(s)
    except ValueError:
        return None


def exact(data: dict, answer: str) -> int:
    m = re.findall(r"answer\s*(?:is|:)\s*\**\s*\$?\s*(-?[\d,]*\.?\d+)", answer, re.I)
    nums = m or re.findall(r"-?\d[\d,]*\.?\d*", answer)
    got = _num(nums[-1].rstrip(".")) if nums else None
    return int(got is not None and abs(got - float(data["expected"])) < 1e-6)


def choice(data: dict, answer: str) -> int:
    t = answer.strip()
    m = (re.search(r"answer\s*(?:is|:)\s*\**\(?([A-D])\b", t, re.I)
         or re.match(r"^\W*([A-D])\b", t) or re.search(r"\b([A-D])\b", t))
    return int(bool(m) and m.group(1).upper() == data["expected"])


def grade(row: dict, answer: str) -> int | None:
    g = row["grader"]
    if g == "unit_test":
        return unit_test(row["data"], answer)
    if g == "exact":
        return exact(row["data"], answer)
    if g == "choice":
        return choice(row["data"], answer)
    return None  # pair and llm are graded elsewhere


def llm_scores(judge, question: str, reference: str, answers: dict[str, str]) -> dict[str, int]:
    """1-5 score per answer. `judge` is a backend with .complete(prompt, max_tokens). Answers are unlabeled."""
    keys = sorted(answers, key=lambda k: zlib.crc32((k + question).encode()))  # arbitrary but unrelated to mode name
    body = "\n\n".join(f"### Answer {i + 1}\n{answers[k]}" for i, k in enumerate(keys))
    q = (f"Question:\n{question}\n\nReference answer (one acceptable answer, not the only one):\n{reference}\n\n"
         f"Score each answer 1-5 for correctness and helpfulness (5 best). "
         f"Reply with ONLY JSON like {{\"1\": 3, \"2\": 4}}.\n\n{body}")
    txt = judge.complete(q, 300)
    try:
        j = json.loads(re.search(r"\{[^{}]*\}", txt).group(0))
        return {k: int(j[str(i + 1)]) for i, k in enumerate(keys)}
    except Exception:
        return {}
