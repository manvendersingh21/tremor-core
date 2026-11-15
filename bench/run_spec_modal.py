"""Driver for the Modal speculative-decoding runs (deploy/modal/spec_modal.py). Results stay in the git-ignored
bench/.scratch/spec_modal/; the committed report is bench/results_spec_modal.md.

  python bench/run_spec_modal.py prompts          # offline: 48 measured prompts + 2 warm-up prompts
  python bench/run_spec_modal.py job JOB          # one `modal run` (ephemeral app), then stop-and-prove
  python bench/run_spec_modal.py stop             # stop any live chimera-spec-modal app by ID, save the proof
  python bench/run_spec_modal.py report           # tables + lossless check from the saved runs (offline)

JOB: download | smoke | cross | eagle3 | ngram | draft4b | suffix | coder480 (see JOBS in the Modal file).
Every job ends with `modal app list` saved to bench/.scratch/spec_modal/applist_<job>.txt, also when it fails.
"""
import json
import os
import pathlib
import random
import statistics
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "bench" / ".scratch" / "spec_modal"
MODAL = str(ROOT / ".venv" / "bin" / "modal")
APP = "chimera-spec-modal"
JOB_ENV = {"coder480": {"SPEC_BIG_MODEL": "coder480", "SPEC_BIG_MODE": "plain", "SPEC_BIG_GPUS": "4"},
           **{m: {"SPEC_BIG_MODE": m} for m in ("eagle3", "ngram", "draft4b", "suffix")}}
# (file, field, value, how many): 28 code + 20 chat, reasoning and short answers
MIX = [("bench/cost_case/tasks.jsonl", "difficulty", "trivial", 10), ("bench/cost_case/tasks.jsonl", "difficulty", "everyday", 8),
       ("bench/cost_case/tasks.jsonl", "difficulty", "hard", 4), ("bench/datasets/suite.jsonl", "source", "humaneval", 3),
       ("bench/datasets/suite.jsonl", "source", "mbpp", 3), ("bench/datasets/suite.jsonl", "source", "dolly", 10),
       ("bench/datasets/suite.jsonl", "source", "gsm8k", 5), ("bench/datasets/suite.jsonl", "source", "mmlu", 5)]
KIND = {"dolly": "chat", "gsm8k": "math", "mmlu": "short"}


def pick_prompts(seed: int = 7) -> dict:
    rnd, out, warm = random.Random(seed), [], []
    for f, key, val, n in MIX:
        rows = [json.loads(line) for line in (ROOT / f).read_text().splitlines() if line.strip()]
        rows = [r for r in rows if r.get(key) == val]
        picked = rnd.sample(rows, n + 1)  # one extra per group feeds the warm-up pool
        for r in picked[:n]:
            out.append({"id": r["id"], "kind": KIND.get(val, "code"), "messages": [{"role": "user", "content": r["prompt"]}]})
        warm.append({"id": "warm-" + picked[n]["id"], "kind": "warm", "messages": [{"role": "user", "content": picked[n]["prompt"]}]})
    return {"prompts": out, "warm": [warm[0], warm[5]]}  # one code, one chat


def modal_json(*args):
    return json.loads(subprocess.run([MODAL, *args, "--json"], capture_output=True, text=True, check=True).stdout)


def ensure_stopped(tag: str) -> int:
    """Stop every live chimera-spec-modal app by ID, then save `modal app list` as proof. Returns how many are live."""
    live = []
    for _ in range(12):
        live = [a for a in modal_json("app", "list") if a.get("Description") == APP and a.get("State") != "stopped"]
        if not live:
            break
        for a in live:
            if a.get("State") != "stopping":
                subprocess.run([MODAL, "app", "stop", "-y", a["App ID"]], check=False)
        time.sleep(5)
    table = subprocess.run([MODAL, "app", "list"], capture_output=True, text=True).stdout
    proof = f"{time.strftime('%Y-%m-%d %H:%M:%S %Z')}  live {APP} apps: {len(live)}\n{table}"
    (OUT / f"applist_{tag}.txt").write_text(proof)
    print(proof, flush=True)
    return len(live)


def job(spec: str) -> int:
    """spec: a job name, or download:KEY,KEY for weights only."""
    name, _, keys = spec.partition(":")
    env = {**os.environ, "SPEC_BIG_MODEL": "big", "SPEC_BIG_MODE": "plain", "SPEC_BIG_GPUS": "2", **JOB_ENV.get(name, {})}
    cmd = [MODAL, "run", "-q", str(ROOT / "deploy" / "modal" / "spec_modal.py"), "--job", name, *(["--keys", keys] if keys else [])]
    log = OUT / f"job_{name}.log"
    code = 1
    try:
        with log.open("a") as fh:
            fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} {' '.join(cmd[1:])}\n")
            fh.flush()
            code = subprocess.run(cmd, env=env, stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT).returncode
    finally:  # success, failure or Ctrl-C: stop first, then prove it
        live = ensure_stopped(name)
    print(f"job {spec}: exit {code}, live apps after stop: {live}, log {log}")
    return code or live


# ---------- offline report ----------
def lossless(base: dict, run: dict) -> tuple[int, int]:
    sys.path.insert(0, str(ROOT / "bench"))
    from spec_modal_core import first_diff

    a = {r["id"]: r["out"] for r in base["rows"]}
    cmp = [(a[r["id"]], r["out"]) for r in run["rows"] if r["id"] in a]
    return sum(first_diff(x, y) == -1 for x, y in cmp), len(cmp)


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))] if xs else float("nan")


def summarize(run: dict) -> dict:
    rows = run["rows"]
    toks, wall = sum(len(r["out"]) for r in rows), sum(r["wall_s"] for r in rows)
    s = {"tok_s": toks / wall, "tokens": toks, "wall_s": wall,
         "median_tok_s": statistics.median(len(r["out"]) / r["wall_s"] for r in rows if r["wall_s"] > 0)}
    for kind in ("code", "chat", "math", "short"):
        sub = [r for r in rows if r.get("kind") == kind]
        if sub:
            s[f"tok_s_{kind}"] = sum(len(r["out"]) for r in sub) / sum(r["wall_s"] for r in sub)
    if "rounds" in rows[0]:
        rounds, drafted, acc = (sum(r[k] for r in rows) for k in ("rounds", "drafted", "accepted"))
        misses = sum(r["misses"] for r in rows)
        s.update(alpha=acc / drafted if drafted else 0, alpha_tested=acc / (acc + misses) if acc + misses else 0,
                 tok_per_round=toks / rounds, k_mean=statistics.mean(k for r in rows for k in r["ks"]),
                 draft_ms_per_round=sum(r["draft_ms"] for r in rows) / rounds,
                 free_accepted=sum(r["free_accepted"] for r in rows), reused=sum(r["reused"] for r in rows))
    if run.get("rtt_ms"):
        net = [a - b for a, b in zip(run["rtt_ms"], run["server_ms"])]
        s.update(rtt_p50_ms=pct(run["rtt_ms"], 0.5), rtt_p90_ms=pct(run["rtt_ms"], 0.9),
                 server_p50_ms=pct(run["server_ms"], 0.5), net_p50_ms=pct(net, 0.5))
    c = (run.get("spec_counters") or {}).get("run_delta") or {}
    acc_k = next((k for k in c if "accepted_tokens" in k), None)
    drf_k = next((k for k in c if "draft_tokens" in k), None)
    if acc_k and drf_k and c[drf_k]:
        s["server_spec_acceptance"] = c[acc_k] / c[drf_k]
    return s


def report():
    runs = {p.stem: json.loads(p.read_text()) for p in sorted(OUT.glob("*.json"))
            if p.stem not in ("prompts",) and not p.stem.startswith(("meta_", "margins"))}
    for n, r in runs.items():
        if not r.get("rows") or "out" not in r["rows"][0]:
            continue
        s = summarize(r)
        base = runs.get("c480_alone" if n.startswith("c480") else "big_alone")
        if base and n not in ("big_alone", "c480_alone") and r["plan"]["mode"] in ("spec", "big_alone"):
            s["lossless"] = "%d/%d" % lossless(base, r)
        print(n, json.dumps({k: round(v, 3) if isinstance(v, float) else v for k, v in s.items()}))
    for p in sorted(OUT.glob("margins*.json")):
        rows = json.loads(p.read_text())["rows"]
        gaps = [round(r["top2"][0][1] - r["top2"][1][1], 3) for r in rows if len(r.get("top2", [])) == 2]
        print(p.stem, len(rows), "mismatches; top-2 logprob gaps at the first difference:", sorted(gaps))


def main(argv):
    OUT.mkdir(parents=True, exist_ok=True)
    cmd = argv[1] if len(argv) > 1 else "prompts"
    if cmd == "prompts":
        ps = pick_prompts()
        (OUT / "prompts.json").write_text(json.dumps(ps))
        print(len(ps["prompts"]), "prompts,", sum(p["kind"] == "code" for p in ps["prompts"]), "code,",
              len(ps["warm"]), "warm-up")
    elif cmd == "job":
        sys.exit(job(argv[2]))
    elif cmd == "stop":
        sys.exit(ensure_stopped("manual"))
    elif cmd == "report":
        report()


if __name__ == "__main__":
    main(sys.argv)
