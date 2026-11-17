"""Same-box speculative decoding check on the A6000 (minor result in bench/results_a6000.md). Runs on the box, stdlib only.

    python3 spec_run.py <llama-server url> <prompts.jsonl> <n> <out.jsonl> <label>

Greedy (temperature 0), 256 tokens per prompt, one request at a time. Keeps the text and llama.cpp's timings
(predicted tokens/s, draft tokens made and accepted) so the plain and the speculative run can be compared word for word.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request


def main() -> None:
    url, prompts, n, out, label = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
    rows = [json.loads(x) for x in open(prompts)][:n]
    with open(out, "a") as fh:
        for r in rows:
            body = json.dumps({"messages": [{"role": "user", "content": r["prompt"]}], "temperature": 0,
                               "max_tokens": 256, "seed": 1}).encode()
            req = urllib.request.Request(url + "/v1/chat/completions", data=body, headers={"Content-Type": "application/json"})
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=600) as resp:  # noqa: S310 (loopback)
                d = json.load(resp)
            t = d.get("timings", {})
            fh.write(json.dumps({"id": r["id"], "label": label, "ms": round((time.perf_counter() - t0) * 1000),
                                 "text": d["choices"][0]["message"]["content"],
                                 "tok_s": t.get("predicted_per_second"), "n": t.get("predicted_n"),
                                 "draft_n": t.get("draft_n"), "draft_ok": t.get("draft_n_accepted")}) + "\n")
            fh.flush()


if __name__ == "__main__":
    main()
