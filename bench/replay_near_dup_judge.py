"""Measure the wrong-cache-hit rate of the near-repeat class on a log, with a cheap GMI judge (grader only, no ladder call).

    .venv/bin/python bench/replay_near_dup_judge.py <log> --sample 5000 [--rates live.rates.json] --out rates.json
For every request the estimate would serve from the cache at cosine >= 0.97 + guard, the judge is asked whether the earlier
prompt's answer would also be a correct answer to the new prompt. Writes a rates file: the live rates with wrong_hit replaced.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import conftest  # noqa: E402,F401
from chimera_core.config import load_env  # noqa: E402

from apps.replay import estimate, live, logs  # noqa: E402

Q = ("Prompt A:\n{a}\n\nPrompt B:\n{b}\n\nWould one answer that is correct for Prompt A also be a correct, complete answer to Prompt B? "
     "Reply with only YES or NO.")

ap = argparse.ArgumentParser()
ap.add_argument("log")
ap.add_argument("--sample", type=int)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--rates", help="live .rates.json to carry over")
ap.add_argument("--out", required=True)
a = ap.parse_args()
load_env()
reqs, _ = logs.load(a.log, a.sample, a.seed)
from chimera_core.cache.semantic_cache import OnnxMiniLMEmbedder  # noqa: E402
pairs: dict[int, int] = {}
estimate.classify(reqs, OnnxMiniLMEmbedder().embed, pairs=pairs)
judge = live.Judge()
res = []
for i, j in pairs.items():
    if estimate._norm(reqs[i].prompt) == estimate._norm(reqs[j].prompt):
        continue  # an exact repeat is classed 'repeat', not a semantic hit
    txt, u = judge.ask(Q.format(a=reqs[j].prompt[:1500], b=reqs[i].prompt[:1500]), 1500)
    res.append({"new": reqs[i].id, "old": reqs[j].id, "ok": "YES" in txt.upper(), "judge": u})
    print(len(res), len(pairs), res[-1]["ok"], flush=True)
rates = json.loads(pathlib.Path(a.rates).read_text())["rates"] if a.rates else dict(estimate.DEFAULT_RATES)
wrong = sum(not r["ok"] for r in res)
rates["wrong_hit"] = wrong / len(res) if res else rates.get("wrong_hit", 0.0)
rates["wrong_hit_source"] = f"judged {len(res)} near-repeat pairs: {wrong} not interchangeable"
pathlib.Path(a.out).write_text(json.dumps({"rates": rates, "near_pairs": res}, indent=1))
print(rates["wrong_hit_source"])
