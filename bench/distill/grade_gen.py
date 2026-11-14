"""Grade the base and tuned generations of deploy/modal/distill.py::evaluate on the held-out set.

    .venv/bin/modal volume get -f chimera-distill /out/gen_base.jsonl bench/.scratch/distill/gen_base.jsonl   (and gen_tuned)
    .venv/bin/python bench/distill/grade_gen.py        # writes summary.json and eval_log.jsonl next to the generations

Each answer runs through bench/datasets/grade.py (sandboxed subprocess, no network). Rows go to the eval log
(bench/evallog.py reads bench/.scratch/distill/eval_log.jsonl), so the Evals tab shows them.
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench" / "datasets"))
sys.path.insert(0, str(ROOT / "bench"))
import evallog  # noqa: E402
import grade  # noqa: E402

D = ROOT / "bench" / ".scratch" / "distill"
MODELS = {"base": "Qwen3-30B-A3B-Instruct-2507 (base)", "tuned": "Qwen3-30B-A3B-Instruct-2507 + LoRA (N+1)"}


def main() -> None:
    held = {r["id"]: r for r in map(json.loads, (D / "heldout.jsonl").read_text().splitlines())}
    res: dict[str, dict[str, int]] = {}
    log = []
    for which in ("base", "tuned"):
        f = D / f"gen_{which}.jsonl"
        if not f.exists():
            continue
        gens = [json.loads(x) for x in f.read_text().splitlines()]
        with ThreadPoolExecutor(6) as ex:
            marks = list(ex.map(lambda g: grade.grade(held[g["id"]], g["text"]), gens))
        res[which] = {g["id"]: m for g, m in zip(gens, marks)}
        for g, m in zip(gens, marks):
            log.append(evallog.EvalRow(run_id="distill-v1", dataset=held[g["id"]]["cat"], item_id=g["id"], mode=f"n1-{which}",
                                       tier="modal-h200", model=MODELS[which], tokens_in=g["tokens_in"], tokens_out=g["tokens_out"],
                                       passed=bool(m), grader="bench/datasets/grade.py", notes="temp 0, thinking off, vLLM offline"))
    (D / "eval_log.jsonl").write_text("".join(r.model_dump_json() + "\n" for r in log))
    cats: dict[str, list[str]] = defaultdict(list)
    for i, h in held.items():
        cats[h["cat"]].append(i)
    out = {"n": len(held), "per_cat": {}, "paired": {}}
    for c, ids in {**cats, "ALL": list(held)}.items():
        out["per_cat"][c] = {"n": len(ids), **{w: round(sum(res[w][i] for i in ids) / len(ids), 4) for w in res},
                             **{f"{w}_pass": sum(res[w][i] for i in ids) for w in res}}
    if len(res) == 2:
        b, t = res["base"], res["tuned"]
        out["paired"] = {"tuned_only": sum(t[i] and not b[i] for i in held), "base_only": sum(b[i] and not t[i] for i in held),
                         "both": sum(t[i] and b[i] for i in held), "neither": sum(not t[i] and not b[i] for i in held)}
    (D / "summary.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
