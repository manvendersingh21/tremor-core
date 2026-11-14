"""Head-to-head: one local tier + Crusoe DeepSeek-V4.1-Flash (763B) as the big model, same prompts, same caches.

  A  763B only          B  Mac 3B -> 763B          C  Ollama 30B -> 763B
  D  H200 122B -> 763B  E  3B -> 30B -> 122B -> 763B (full ladder)

Per run: exact + semantic cache (0.97) first, then a TierPool of the listed tiers. A non-top answer climbs to the
763B when its asserts fail (prompts with tests) or its tier's self-check says ESCALATE (30B and 122B only).
Rows go to $KIROCREW_SCRATCH/pairs_<run>.json. Needs the Mac llama-server, the 30B tunnel (--gpu-small-url),
MODAL_VLLM_URL/MODAL_VLLM_TOKEN and CRUSOE_API_KEY.

  .venv/bin/python bench/run_pairs.py A B C D E   |   report
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import random
import re
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))
import conftest  # noqa: E402,F401
from chimera_core.cache.exact_cache import ExactCache  # noqa: E402
from chimera_core.cache.semantic_cache import OnnxMiniLMEmbedder, SemanticCache  # noqa: E402
from chimera_core.config import load_config  # noqa: E402
from chimera_core.inference.cloud_verifier import CrusoeBackend  # noqa: E402
from chimera_core.ladder import CHECK_PROMPT  # noqa: E402
from chimera_core.router import complexity_score  # noqa: E402
from chimera_core.tiers import TierPool  # noqa: E402
from run_bench import load_env, run_tests  # noqa: E402

STORE = pathlib.Path(os.environ.get("KIROCREW_SCRATCH") or ROOT / "bench")
BIG = "cloud-deepseek"
RUNS = {"A": [BIG], "B": ["mac-3b", BIG], "C": ["gpu-small", BIG], "D": ["gpu-large", BIG],
        "E": ["mac-3b", "gpu-small", "gpu-large", BIG]}
SELF_CHECK = {"gpu-small", "gpu-large"}
PRICE = (0.29, 0.007, 1.20)  # DeepSeek-V4.1-Flash $/M: input, cached input, output (Crusoe /v1/models)
GRADER = "Qwen/Qwen3.8-27B"  # wrote none of the answers
MAX_TOKENS = 1500


def quality(p: dict, ans: str):
    if "expect" in p:
        return int(any(e in ans.lower() for e in p["expect"]))
    if "tests" in p:
        return int(run_tests(ans, p["tests"]))
    return ""


def usd(u: dict) -> float:
    return ((u["prompt_tokens"] - u["cached_tokens"]) * PRICE[0] + u["cached_tokens"] * PRICE[1]
            + u["completion_tokens"] * PRICE[2]) / 1e6


def run(name: str, urls: dict) -> None:
    cfg = load_config(ROOT / "chimera.example.toml")
    tiers = [t.model_copy(update={"url": urls.get(t.name, t.url)}) for t in cfg.tiers if t.name in RUNS[name]]
    pool = TierPool(tiers, min_confidence=0.85, max_tokens=MAX_TOKENS)
    exact, sem = ExactCache(), SemanticCache(OnnxMiniLMEmbedder(), threshold=0.97)
    prompts = [json.loads(x) for x in (ROOT / "bench/prompts.jsonl").read_text().splitlines() if x.strip()]
    # warm every tier once so model load is not timed (the H200 cold start is measured separately)
    for t in pool.tiers:
        pool._backends[t.name] = pool._factory(t)
        pool._backends[t.name].complete("Say hi.", 4)
    big = pool._backends[BIG].raw
    big.usage_log.clear()
    rows, answers = [], {}
    for p in prompts:
        q, t0 = p["prompt"], time.perf_counter()
        n_big = len(big.usage_log)
        tier, text, loc_in, loc_out, extra = "cache", exact.get(q), 0, 0, {}
        if text is None and (s := sem.get(q)) is not None:
            text = s[0]
        if text is None:
            r = pool.generate(q, complexity_score(q))
            tier, text = r.tier, r.text
            for n, u in r.per_tier.items():
                if n != BIG:
                    loc_in, loc_out = loc_in + u.tokens_in, loc_out + u.tokens_out
            if tier != BIG:
                bad = "tests" in p and not run_tests(text, p["tests"])
                if tier in SELF_CHECK and "tests" not in p:
                    c = pool._backends[tier].complete(CHECK_PROMPT.format(task=q, answer=text), 8)
                    loc_in, loc_out = loc_in + c[1], loc_out + c[2]
                    bad = "ESCALATE" in c[0].upper()
                if bad:  # climb to the big model
                    b = pool._backends[BIG].complete(q, MAX_TOKENS)
                    tier, text = BIG, b[0]
            if not (tier == "cache"):
                exact.put(q, text)
                sem.put(q, text)
        ms = (time.perf_counter() - t0) * 1000
        calls = big.usage_log[n_big:]
        rows.append({"run": name, "id": p["id"], "cat": p["cat"], "tier": tier, "latency_ms": round(ms),
                     "big_calls": len(calls), "big_in": sum(u["prompt_tokens"] for u in calls),
                     "big_out": sum(u["completion_tokens"] for u in calls),
                     "big_cached": sum(u["cached_tokens"] for u in calls),
                     "big_usd": round(sum(usd(u) for u in calls), 7), "local_in": loc_in, "local_out": loc_out,
                     "quality": quality(p, text), **extra})
        answers[p["id"]] = text
        print(name, p["id"], tier, round(ms), rows[-1]["big_in"], rows[-1]["big_out"], flush=True)
    (STORE / f"pairs_{name}.json").write_text(json.dumps({"rows": rows, "answers": answers}, indent=1))


def grade(prompts: dict) -> dict:
    path = STORE / "pairs_grades.json"
    if path.exists():
        return json.loads(path.read_text())
    runs = [r for r in RUNS if (STORE / f"pairs_{r}.json").exists()]
    data = {r: json.loads((STORE / f"pairs_{r}.json").read_text())["answers"] for r in runs}
    g, rng, out = CrusoeBackend(model=GRADER), random.Random(5), {}
    for pid, p in prompts.items():
        if p["cat"] != "code_heavy":
            continue
        order = list(runs)
        rng.shuffle(order)
        body = "\n\n".join(f"### Answer {i + 1}\n{data[r][pid]}" for i, r in enumerate(order))
        q = (f"Task:\n{p['prompt']}\n\nGrade each answer for correctness, completeness and clarity, 1-5 (5 best). "
             f"Reply with ONLY JSON like {{\"1\": 3, \"2\": 4}}.\n\n{body}")
        txt = g.complete(q, 1500)
        try:
            j = json.loads(re.search(r"\{[^{}]*\}", txt).group(0))
            out[pid] = {r: int(j[str(i + 1)]) for i, r in enumerate(order)}
        except Exception:
            out[pid] = {"error": txt[-200:]}
    path.write_text(json.dumps({"grades": out, "usage": g.usage_log}))
    return {"grades": out, "usage": g.usage_log}


def pct(x, q):
    x = sorted(x)
    return x[min(len(x) - 1, int(q * len(x)))]


def report() -> None:
    load_env()
    prompts = {p["id"]: p for p in (json.loads(x) for x in (ROOT / "bench/prompts.jsonl").read_text().splitlines() if x.strip())}
    runs = [r for r in RUNS if (STORE / f"pairs_{r}.json").exists()]
    rows = {r: json.loads((STORE / f"pairs_{r}.json").read_text())["rows"] for r in runs}
    gr = grade(prompts)
    with open(ROOT / "bench/results_modal.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, ["run", "id", "cat", "tier", "latency_ms", "big_calls", "big_in", "big_out", "big_cached",
                                "big_usd", "local_in", "local_out", "quality", "heavy_grade"])
        w.writeheader()
        for r in runs:
            for x in rows[r]:
                w.writerow({**x, "heavy_grade": gr["grades"].get(x["id"], {}).get(r, "")})
    out = ["| run | 763B calls | 763B in | 763B out | 763B cached | 763B $ | local tokens (in+out) | median ms | p90 ms | asserts+keywords | heavy grade (mean 1-5) |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in runs:
        rs = rows[r]
        lat = [x["latency_ms"] for x in rs]
        scored = [x for x in rs if x["quality"] != ""]
        hg = [gr["grades"][x["id"]][r] for x in rs if x["cat"] == "code_heavy" and r in gr["grades"].get(x["id"], {})]
        out.append(f"| {r} | {sum(x['big_calls'] for x in rs)} | {sum(x['big_in'] for x in rs)} | {sum(x['big_out'] for x in rs)} | "
                   f"{sum(x['big_cached'] for x in rs)} | ${sum(x['big_usd'] for x in rs):.5f} | "
                   f"{sum(x['local_in'] + x['local_out'] for x in rs)} | {statistics.median(lat):.0f} | {pct(lat, .9):.0f} | "
                   f"{sum(x['quality'] for x in scored)}/{len(scored)} | {statistics.mean(hg):.2f} |" if hg else
                   f"| {r} | ... |")
    (STORE / "pairs_table.md").write_text("\n".join(out))
    print("\n".join(out))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--gpu-small-url", default="http://127.0.0.1:11436")
    a = ap.parse_args()
    load_env()
    for x in a.runs:
        report() if x == "report" else run(x, {"gpu-small": a.gpu_small_url})
