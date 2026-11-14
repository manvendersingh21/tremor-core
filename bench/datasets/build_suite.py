"""Build bench/datasets/suite.jsonl (1000 rows: the original 300, then 700 more) from the public datasets in fetch.py. Seeded: same output every run.

    .venv/bin/python bench/datasets/build_suite.py

Mix: 40% easy (MMLU choice, Dolly open/general QA), 20% repeats (30 real Quora/QQP pairs: 24 duplicates,
6 non-duplicates, each pair is an A row then a later B row), 25% small code (HumanEval, MBPP),
15% hard (GSM8K with the most steps, the longest HumanEval prompts).
"""
from __future__ import annotations

import json
import pathlib
import random
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import fetch  # noqa: E402

OUT = pathlib.Path(__file__).parent / "suite.jsonl"
SEED = 20261114
rng = random.Random(SEED)

CODE_HEAD = "Complete the following Python function. Reply with the complete function in one ```python code block.\n\n"
LETTERS = "ABCD"


def humaneval(r: dict, type_: str) -> dict:
    return {"id": r["task_id"].replace("/", "-").lower(), "source": "humaneval", "type": type_,
            "prompt": CODE_HEAD + r["prompt"], "grader": "unit_test",
            "data": {"kind": "humaneval", "prompt": r["prompt"], "test": r["test"], "entry_point": r["entry_point"]}}


def mbpp(r: dict) -> dict:
    tests = r["test_list"]
    prompt = (f"{r['prompt']}\nYour code must pass these tests:\n" + "\n".join(tests)
              + "\n\nReply with the Python code in one ```python code block.")
    return {"id": f"mbpp-{r['task_id']}", "source": "mbpp", "type": "code", "prompt": prompt, "grader": "unit_test",
            "data": {"kind": "mbpp", "imports": r["test_imports"], "tests": tests}}


def gsm8k(i: int, r: dict) -> dict:
    prompt = ("Solve the problem. Think step by step, then give the final answer on the last line as "
              f"'Answer: <number>'.\n\n{r['question']}")
    return {"id": f"gsm8k-{i}", "source": "gsm8k", "type": "hard", "prompt": prompt, "grader": "exact",
            "data": {"expected": r["answer"].split("####")[-1].strip().replace(",", "")}}


def mmlu(i: int, r: dict) -> dict:
    opts = "\n".join(f"{LETTERS[k]}. {c}" for k, c in enumerate(r["choices"]))
    prompt = f"Answer the multiple-choice question. Reply with only the letter (A, B, C or D).\n\n{r['question']}\n{opts}"
    return {"id": f"mmlu-{i}", "source": "mmlu", "type": "easy", "prompt": prompt, "grader": "choice",
            "data": {"expected": LETTERS[r["answer"]], "subject": r["subject"]}}


def dolly(i: int, r: dict) -> dict:
    return {"id": f"dolly-{i}", "source": "dolly", "type": "easy", "prompt": r["instruction"], "grader": "llm",
            "data": {"reference": r["response"]}}


def norm(s: str) -> str:
    return re.sub(r"\W+", " ", s.lower()).strip()


def pairs(n_dup: int, n_neg: int, skip: frozenset = frozenset()) -> list[dict]:
    qs = [r for r in fetch.sample_rows("qqp", 6, 7)
          if r["idx"] not in skip and 25 <= len(r["question1"]) <= 200 and 25 <= len(r["question2"]) <= 200
          and norm(r["question1"]) != norm(r["question2"])]
    rng.shuffle(qs)
    dup = [r for r in qs if r["label"] == 1][:n_dup]
    neg = [r for r in qs if r["label"] == 0][:n_neg]
    out = []
    for r in dup + neg:
        k = r["idx"]
        out.append({"id": f"qqp-{k}-a", "source": "qqp", "type": "repeat", "prompt": r["question1"],
                    "grader": "pair", "data": {"role": "a"}})
        out.append({"id": f"qqp-{k}-b", "source": "qqp", "type": "repeat", "prompt": r["question2"],
                    "grader": "pair", "data": {"role": "b", "a_id": f"qqp-{k}-a", "duplicate": bool(r["label"])}})
    return out


def place_pairs(rows: list[dict], ps: list[dict]) -> None:
    for p in ps:  # a pair's B row always lands after its A row
        if p["data"]["role"] == "a":
            rows.insert(rng.randrange(len(rows) + 1), p)
    for p in ps:
        if p["data"]["role"] == "b":
            at = next(i for i, r in enumerate(rows) if r["id"] == p["data"]["a_id"])
            rows.insert(rng.randrange(at + 1, len(rows) + 1), p)


def main() -> None:
    he = fetch.all_rows("humaneval")
    he_by_len = sorted(he, key=lambda r: -len(r["prompt"]))
    he_long, he_rest = he_by_len[:15], he_by_len[15:]
    rng.shuffle(he_rest)
    gs = fetch.all_rows("gsm8k")
    gs_hard = [(i, r) for i, r in enumerate(gs) if r["answer"].count("<<") >= 5]
    mb = fetch.all_rows("mbpp")
    rng.shuffle(mb)
    mm = list(enumerate(fetch.mmlu_rows()))
    rng.shuffle(mm)
    dl = [(i, r) for i, r in enumerate(fetch.sample_rows("dolly", 6, 7))
          if r["category"] in ("open_qa", "general_qa") and not r["context"] and len(r["instruction"]) <= 300
          and len(r["response"]) <= 1200]
    rng.shuffle(dl)
    rng.shuffle(gs_hard)

    rows = ([mmlu(i, r) for i, r in mm[:60]] + [dolly(i, r) for i, r in dl[:60]]
            + [humaneval(r, "code") for r in he_rest[:40]] + [mbpp(r) for r in mb[:35]]
            + [gsm8k(i, r) for i, r in gs_hard[:30]] + [humaneval(r, "hard") for r in he_long])
    rng.shuffle(rows)
    ps = pairs(24, 6)
    place_pairs(rows, ps)
    # Extra block (rows 301-1000): same sources, items not used above, same mix. Appended after the first 300,
    # so the first 300 rows (and finished runs on them) stay valid.
    used = frozenset(int(p["id"].split("-")[1]) for p in ps)
    extra = ([mmlu(i, r) for i, r in mm[60:200]] + [dolly(i, r) for i, r in dl[60:200]]
             + [humaneval(r, "code") for r in he_rest[40:100]] + [mbpp(r) for r in mb[35:150]]
             + [gsm8k(i, r) for i, r in gs_hard[30:135]])
    rng.shuffle(extra)
    place_pairs(extra, pairs(56, 14, used))
    rows += extra
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    kinds = {}
    for r in rows:
        kinds[r["type"]] = kinds.get(r["type"], 0) + 1
    print(len(rows), "rows,", OUT.stat().st_size // 1024, "KiB", kinds)


if __name__ == "__main__":
    main()
