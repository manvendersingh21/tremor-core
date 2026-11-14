"""N+1 training data: the 763B solves TRAIN-split problems, only answers that pass their tests are kept.

    .venv/bin/python bench/distill/build_data.py heldout          # write bench/.scratch/distill/heldout.jsonl
    .venv/bin/python bench/distill/build_data.py problems [N]     # sample train problems (MBPP train/val/prompt + AceCode-87K)
    .venv/bin/python bench/distill/build_data.py solve            # Crusoe solves, tests grade, writes teacher.jsonl + cost
    .venv/bin/python bench/distill/build_data.py overlap          # train vs held-out overlap report (json)

Store: JSONL under bench/.scratch/distill/ (git-ignored scratch), not memory.store(): that writes the shared Supabase
`teacher_pairs` and Aura graph, and 2,000 bulk pairs would swamp the retrieval chat's data it is compared against.
The key comes from CRUSOE_API_KEY (env or .env). Nothing is printed from .env.
"""
from __future__ import annotations

import json
import pathlib
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench" / "datasets"))
sys.path.insert(0, str(ROOT / "bench"))
import fetch  # noqa: E402
import grade  # noqa: E402
from run_bench import load_env  # noqa: E402

OUT = ROOT / "bench" / ".scratch" / "distill"
MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"
PRICE = (0.29, 0.007, 1.20)  # $/M input, cached input, output (bench/results_ladder.md)
TAIL = "Reply with only the Python code in one ```python code block."
ACE = "TIGER-Lab/AceCode-87K"
SEED = 7


def _write(name: str, rows: list[dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text("".join(json.dumps(r) + "\n" for r in rows))


def _read(name: str) -> list[dict]:
    return [json.loads(x) for x in (OUT / name).read_text().splitlines() if x.strip()]


def mbpp_prompt(text: str, tests: list[str]) -> str:
    return f"{text}\nYour code must pass these tests:\n" + "\n".join(tests[:3]) + "\n\n" + TAIL


# ---------------------------------------------------------------------------------------------- held-out
def heldout() -> None:
    """HumanEval (all 164) + MBPP sanitized test + the cost-case custom tasks (bench/cost_case/tasks.jsonl)."""
    rows = []
    for r in fetch.all_rows("humaneval"):
        rows.append({"id": r["task_id"].replace("/", "-").lower(), "cat": "humaneval",
                     "prompt": "Complete this Python function. " + TAIL + "\n\n" + r["prompt"],
                     "grader": "unit_test", "data": {"kind": "humaneval", "prompt": r["prompt"], "test": r["test"],
                                                     "entry_point": r["entry_point"]}, "text": r["prompt"]})
    for r in fetch.all_rows("mbpp"):
        rows.append({"id": f"mbpp-{r['task_id']}", "cat": "mbpp_test", "prompt": mbpp_prompt(r["prompt"], r["test_list"]),
                     "grader": "unit_test", "data": {"kind": "mbpp", "imports": r["test_imports"], "tests": r["test_list"]},
                     "text": r["prompt"] + " " + " ".join(r["test_list"])})
    for x in (json.loads(l) for l in (ROOT / "bench/cost_case/tasks.jsonl").read_text().splitlines()):
        if x["source"] == "custom":  # the HumanEval/MBPP items of the cost case are already in the two sets above
            x["cat"] = f"cost_case_{x['difficulty']}"
            x["text"] = x["prompt"] + " " + " ".join(x["data"]["tests"])
            rows.append(x)
    _write("heldout.jsonl", rows)
    from collections import Counter
    print(len(rows), dict(Counter(r["cat"] for r in rows)))


# ---------------------------------------------------------------------------------------------- train problems
def ace_rows(off: int) -> list[dict]:
    """One AceCode page, trimmed to id/question/test_cases (a raw page is 6 MB of model completions)."""
    f = OUT / "ace" / f"{off}.json"
    if f.exists():
        return json.loads(f.read_text())
    for attempt in range(2):
        try:
            r = httpx.get(f"{fetch.API}/rows", params={"dataset": ACE, "config": "default", "split": "train",
                                                       "offset": off, "length": 100}, timeout=60)
            r.raise_for_status()
            out = [{k: x["row"][k] for k in ("id", "question", "test_cases")} for x in r.json()["rows"]]
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(out))
            return out
        except (httpx.HTTPError, ValueError):
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"AceCode page {off} failed")


def problems(n_ace_pages: int = 45) -> None:
    rows = []
    for split in ("train", "validation", "prompt"):  # MBPP full: ids 601-974, 511-600, 1-10. Test is 11-510 (held out).
        for r in fetch.rows("google-research-datasets/mbpp", "full", split, 0, 100) + \
                (fetch.rows("google-research-datasets/mbpp", "full", split, 100, 100) if split == "train" else []) + \
                (fetch.rows("google-research-datasets/mbpp", "full", split, 200, 100) if split == "train" else []) + \
                (fetch.rows("google-research-datasets/mbpp", "full", split, 300, 100) if split == "train" else []):
            rows.append({"id": f"mbpp-{split}-{r['task_id']}", "src": f"mbpp_{split}", "text": r["text"],
                         "prompt": mbpp_prompt(r["text"], r["test_list"]),
                         "imports": r.get("test_imports") or [], "tests": r["test_list"]})
    n = fetch.total(ACE, "default", "train")
    offs = random.Random(SEED).sample(range(0, n - 100, 100), min(n_ace_pages * 2, (n - 100) // 100))
    pages = []
    for off in offs:  # some pages are too big for the rows API and fail: skip them, take the next offset
        if len(pages) == n_ace_pages:
            break
        try:
            pages.append(ace_rows(off))
        except RuntimeError:
            print("skip page", off, flush=True)
    for page in pages:
        for r in page:
            t = r["test_cases"]
            if not t or len(t) > 40 or len(r["question"]) > 1500:
                continue
            rows.append({"id": f"ace-{r['id']}", "src": "acecode", "text": r["question"],
                         "prompt": mbpp_prompt(r["question"], t), "imports": [], "tests": t})
    _write("problems.jsonl", rows)
    from collections import Counter
    print(len(rows), dict(Counter(r["src"] for r in rows)))


# ---------------------------------------------------------------------------------------------- overlap
def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9_]+", s.lower())


def _grams(s: str, n: int = 8) -> set:
    w = _words(s)
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def _names(s: str) -> set:
    return set(re.findall(r"assert\s+(?:not\s+)?([A-Za-z_]\w*)\s*\(", s))


def overlap_ids(train: list[dict], held: list[dict]) -> dict[str, str]:
    """train id -> reason, for every train problem that shares an 8-gram, a word-set Jaccard >= 0.6, or a
    tested function name together with its first test string with a held-out problem."""
    hg: dict = {}
    for h in held:
        for g in _grams(h["text"]):
            hg.setdefault(g, h["id"])
    hw = [(h["id"], set(_words(h["text"]))) for h in held]
    first_tests = {h["data"]["tests"][0].strip() for h in held if h["data"].get("tests")}
    bad: dict[str, str] = {}
    for t in train:
        g = next((hg[x] for x in _grams(t["text"]) if x in hg), None)
        if g:
            bad[t["id"]] = f"8-gram with {g}"
            continue
        if t["tests"][0].strip() in first_tests:
            bad[t["id"]] = "same first test"
            continue
        w = set(_words(t["text"]))
        j = next((hid for hid, s in hw if w and s and len(w & s) / len(w | s) >= 0.6), None)
        if j:
            bad[t["id"]] = f"jaccard>=0.6 with {j}"
    return bad


def overlap() -> None:
    train, held = _read("problems.jsonl"), _read("heldout.jsonl")
    bad = overlap_ids(train, held)
    from collections import Counter
    rep = {"train_problems": len(train), "heldout_problems": len(held), "flagged": len(bad),
           "by_src": dict(Counter(t["src"] for t in train if t["id"] in bad)),
           "by_reason": dict(Counter(v.split(" ")[0] for v in bad.values()))}
    (OUT / "overlap.json").write_text(json.dumps({**rep, "ids": bad}, indent=1))
    print(json.dumps(rep))


# ---------------------------------------------------------------------------------------------- solve
_lock = threading.Lock()
_usage = {"prompt": 0, "cached": 0, "completion": 0, "calls": 0}


def crusoe(client: httpx.Client, key: str, prompt: str) -> str:
    for attempt in range(4):
        try:
            r = client.post("https://api.inference.crusoecloud.com/v1/chat/completions",
                            headers={"Authorization": f"Bearer {key}"},
                            json={"model": MODEL, "max_tokens": 1500, "temperature": 0,
                                  "chat_template_kwargs": {"thinking": False},
                                  "messages": [{"role": "user", "content": prompt}]})
            r.raise_for_status()
            d = r.json()
            u = d.get("usage", {})
            with _lock:
                _usage["prompt"] += u.get("prompt_tokens", 0)
                _usage["cached"] += (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
                _usage["completion"] += u.get("completion_tokens", 0)
                _usage["calls"] += 1
            return d["choices"][0]["message"].get("content") or ""
        except (httpx.HTTPError, KeyError):
            if attempt == 3:
                return ""
    return ""


def solve() -> None:
    import os
    load_env()
    key = os.environ["CRUSOE_API_KEY"]
    train, held = _read("problems.jsonl"), _read("heldout.jsonl")
    bad = overlap_ids(train, held)
    todo = [t for t in train if t["id"] not in bad]
    done = {r["id"] for r in _read("teacher.jsonl")} if (OUT / "teacher.jsonl").exists() else set()
    todo = [t for t in todo if t["id"] not in done]
    print(f"{len(train)} problems, {len(bad)} dropped for overlap, {len(todo)} to solve")
    fails = 0
    out = (OUT / "teacher.jsonl").open("a")
    with httpx.Client(timeout=120) as client:
        def one(t: dict):
            ans = crusoe(client, key, t["prompt"])
            code = grade.code_of(ans) if ans else ""
            ok = bool(code.strip()) and grade.run_sandboxed("\n".join(t["imports"]) + f"\n{code}\n\n" + "\n".join(t["tests"]))
            return t, code, ok
        with ThreadPoolExecutor(12) as ex:
            for i, (t, code, ok) in enumerate(ex.map(one, todo), 1):
                if ok:
                    out.write(json.dumps({"id": t["id"], "src": t["src"], "prompt": t["prompt"],
                                          "response": f"```python\n{code.strip()}\n```", "model": MODEL,
                                          "tests_passed": True}) + "\n")
                    out.flush()
                else:
                    fails += 1
                if i % 200 == 0:
                    print(i, "solved so far", i - fails, flush=True)
    usd = ((_usage["prompt"] - _usage["cached"]) * PRICE[0] + _usage["cached"] * PRICE[1] + _usage["completion"] * PRICE[2]) / 1e6
    prev = json.loads((OUT / "crusoe_cost.json").read_text()) if (OUT / "crusoe_cost.json").exists() else {"usd": 0, "calls": 0}
    cost = {"usd": round(prev["usd"] + usd, 4), "calls": prev["calls"] + _usage["calls"], "this_run": _usage}
    (OUT / "crusoe_cost.json").write_text(json.dumps(cost))
    print("failed tests:", fails, "cost:", cost["usd"])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"heldout": heldout, "problems": lambda: problems(int(sys.argv[2]) if len(sys.argv) > 2 else 45),
     "solve": solve, "overlap": overlap}[cmd]()
