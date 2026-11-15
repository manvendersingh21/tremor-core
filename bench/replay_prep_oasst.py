"""OpenAssistant/oasst1 (Apache-2.0, ungated) first-turn prompts -> OpenAI-style request log for `chimera replay`.

    .venv/bin/python bench/replay_prep_oasst.py [--lang en|all]
Downloads the ready trees file once (34 MB) into bench/.scratch/replay/. No usage fields: oasst1 has no token counts.
Output is git-ignored (bench/.scratch).
"""
from __future__ import annotations

import argparse
import gzip
import json
import pathlib
import urllib.request

OUT = pathlib.Path(__file__).resolve().parent / ".scratch" / "replay"
URL = "https://huggingface.co/datasets/OpenAssistant/oasst1/resolve/main/2023-04-12_oasst_ready.trees.jsonl.gz"

ap = argparse.ArgumentParser()
ap.add_argument("--lang", default="en")
a = ap.parse_args()
OUT.mkdir(parents=True, exist_ok=True)
gz = OUT / "oasst1.trees.jsonl.gz"
if not gz.exists():
    urllib.request.urlretrieve(URL, gz)  # noqa: S310  fixed https URL
n = 0
with gzip.open(gz, "rt", encoding="utf-8") as fh, open(OUT / f"oasst1_first_turn_{a.lang}.jsonl", "w") as out:
    for line in fh:
        p = json.loads(line)["prompt"]
        if a.lang in ("all", p.get("lang")) and p.get("role") == "prompter" and not p.get("deleted") and p["text"].strip():
            out.write(json.dumps({"id": p["message_id"], "model": "unknown", "messages": [{"role": "user", "content": p["text"]}]}) + "\n")
            n += 1
print(n, "first-turn prompts ->", OUT / f"oasst1_first_turn_{a.lang}.jsonl")
