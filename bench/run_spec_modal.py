"""Driver for the Modal speculative-decoding runs. Needs the app deployed (deploy/modal/spec_modal.py) and a go-ahead.

  python bench/run_spec_modal.py prompts                       # write the 48-prompt set (offline)
  python bench/run_spec_modal.py run NAME DRAFT_MODEL MODE [k] [adaptive] [big_mode]
      DRAFT_MODEL: mid | small | mid+small     MODE: draft_alone | big_alone | spec
Each run writes bench/.scratch/spec_modal/NAME.json (git-ignored, resumable: an existing file is skipped).
  python bench/run_spec_modal.py report                        # lossless check + table from the saved runs
"""
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "bench" / ".scratch" / "spec_modal"
MAX_TOKENS = 256
# (file, field, value, how many): 28 code + 20 chat/reasoning
MIX = [("bench/cost_case/tasks.jsonl", "difficulty", "trivial", 10), ("bench/cost_case/tasks.jsonl", "difficulty", "everyday", 8),
       ("bench/cost_case/tasks.jsonl", "difficulty", "hard", 4), ("bench/datasets/suite.jsonl", "source", "humaneval", 3),
       ("bench/datasets/suite.jsonl", "source", "mbpp", 3), ("bench/datasets/suite.jsonl", "source", "dolly", 10),
       ("bench/datasets/suite.jsonl", "source", "gsm8k", 5), ("bench/datasets/suite.jsonl", "source", "mmlu", 5)]


def pick_prompts(seed: int = 7) -> list[dict]:
    rnd, out = random.Random(seed), []
    for f, key, val, n in MIX:
        rows = [json.loads(line) for line in (ROOT / f).read_text().splitlines() if line.strip()]
        rows = [r for r in rows if r.get(key) == val]
        for r in rnd.sample(rows, n):
            out.append({"id": r["id"], "kind": "code" if key == "difficulty" or val in ("humaneval", "mbpp") else "chat",
                        "messages": [{"role": "user", "content": r["prompt"]}]})
    return out


def lossless(big: dict, spec: dict) -> tuple[int, int]:
    """(prompts whose token ids equal big-alone, prompts compared)."""
    sys.path.insert(0, str(ROOT / "bench"))
    from spec_modal_core import first_diff

    a = {r["id"]: r["out"] for r in big["rows"]}
    cmp = [(a[r["id"]], r["out"]) for r in spec["rows"] if r["id"] in a]
    return sum(first_diff(x, y) == -1 for x, y in cmp), len(cmp)


def summarize(run: dict) -> dict:
    rows = run["rows"]
    toks, wall = sum(len(r["out"]) for r in rows), sum(r["wall_s"] for r in rows)
    s = {"tok_s": toks / wall, "tokens": toks, "wall_s": wall}
    if "alpha" in rows[0]:
        d = sum(r["rounds"] for r in rows)
        s["alpha"] = sum(r["alpha"] * r["rounds"] for r in rows) / d
        s["tok_per_round"] = toks / d
    rtt = rows[0].get("rtt_ms_all")
    if rtt:
        rtt = sorted(rtt)
        s["rtt_p50_ms"], s["rtt_p90_ms"] = rtt[len(rtt) // 2], rtt[int(len(rtt) * 0.9)]
        s["server_p50_ms"] = sorted(rows[0]["server_ms_all"])[len(rtt) // 2]
    return s


def main(argv):
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = argv[1] if len(argv) > 1 else "prompts"
    if cmd == "prompts":
        ps = pick_prompts()
        (OUT / "prompts.json").write_text(json.dumps(ps))
        print(len(ps), "prompts", sum(p["kind"] == "code" for p in ps), "code")
    elif cmd == "run":
        name, model, mode = argv[2:5]
        f = OUT / f"{name}.json"
        if f.exists():
            return print("exists, skipped", f)
        import modal

        plan = {"mode": mode, "max_tokens": MAX_TOKENS, "k": int(argv[5]) if len(argv) > 5 else 4,
                "adaptive": (argv[6] == "1") if len(argv) > 6 else False, "big_mode": argv[7] if len(argv) > 7 else "plain"}
        ps = json.loads((OUT / "prompts.json").read_text())
        rows = modal.Cls.from_name("chimera-spec-modal", "Draft")(model=model).run.remote(ps, plan)
        f.write_text(json.dumps({"name": name, "draft_model": model, "plan": plan, "rows": rows}))
        print(name, summarize({"rows": rows}))
    elif cmd == "report":
        runs = {p.stem: json.loads(p.read_text()) for p in OUT.glob("*.json") if p.stem != "prompts"}
        base = runs.get("big_alone")
        for n, r in sorted(runs.items()):
            s = summarize(r)
            if base and n != "big_alone" and r["plan"]["mode"] == "spec":
                s["lossless"] = "%d/%d" % lossless(base, r)
            print(n, {k: round(v, 2) if isinstance(v, float) else v for k, v in s.items()})


if __name__ == "__main__":
    main(sys.argv)
