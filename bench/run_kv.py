"""KV / prompt-cache reuse. KV tensors cannot move between different models, so test what does work:
a byte-identical prefix with the variable part last, so the serving side reuses its own cache.

The 6 heavy prompts go to Crusoe DeepSeek-V4.1-Flash twice: FIXED (shared system prefix, prompt last) and
SHUFFLED (same text, prompt first so no shared prefix). Then the FIXED set goes to the H200 (vLLM prefix caching)
and the hit rate is read from /metrics before and after. Writes $KIROCREW_SCRATCH/kv.json.

  .venv/bin/python bench/run_kv.py
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))
import conftest  # noqa: E402,F401
from chimera_core.ladder import TopBackend  # noqa: E402
from run_bench import load_env  # noqa: E402

STORE = pathlib.Path(os.environ.get("KIROCREW_SCRATCH") or ROOT / "bench")
RULES = "\n".join(f"{i}. {r}" for i, r in enumerate([
    "Write Python 3.11 with type hints and no third-party packages unless the task names one.",
    "State assumptions in one short list before the code.", "Prefer the standard library.",
    "Validate input at the boundary and raise ValueError with a clear message.",
    "Keep functions under 40 lines; name things for what they do.", "Add one docstring line per public function.",
    "Never swallow exceptions; catch the narrowest type.", "No global mutable state.",
    "Include a short usage example in a final code block.", "Do not print secrets or tokens.",
    "Use pathlib for paths and context managers for files.", "Prefer dataclasses or pydantic models for records.",
    "Explain complexity in one sentence when it matters.", "Keep the reply under 400 words.",
] * 6, 1))  # ~1.6k tokens, deterministic
PREFIX = "You are a senior engineer on the CHIMERA team. House rules:\n" + RULES + "\n\nTask follows.\n"
PRICE_IN, PRICE_CACHED = 0.29, 0.007  # $/M, Crusoe DeepSeek-V4.1-Flash


def metric(url: str, name: str) -> float:
    txt = urllib.request.urlopen(url.rstrip("/") + "/metrics", timeout=30).read().decode()  # noqa: S310
    return sum(float(m.group(1)) for m in re.finditer(rf"^{re.escape(name)}(?:{{[^}}]*}})? ([0-9.e+]+)", txt, re.M))


def main() -> None:
    load_env()
    heavy = [json.loads(x)["prompt"] for x in (ROOT / "bench/prompts.jsonl").read_text().splitlines()
             if x.strip() and json.loads(x)["cat"] == "code_heavy"]
    big = TopBackend("deepseek-ai/DeepSeek-V4.1-Flash", {"thinking": False})
    out = {}
    for variant, nonce in (("fixed", "A"), ("shuffled", "B")):
        calls = []
        for p in heavy:
            if variant == "fixed":
                prompt = PREFIX.replace("CHIMERA", f"CHIMERA-{nonce}") + p  # nonce keeps variants from sharing a cache
            else:
                prompt = p + "\n\n" + PREFIX.replace("CHIMERA", f"CHIMERA-{nonce}")
            big.complete(prompt, 200)
            calls.append(dict(big.last_usage))
        out[variant] = calls
        print(variant, [(c["prompt_tokens"], c["cached_tokens"]) for c in calls], flush=True)
    url, tok = os.environ["MODAL_VLLM_URL"], os.environ["MODAL_VLLM_TOKEN"]
    q0, h0 = metric(url, "vllm:prefix_cache_queries_total"), metric(url, "vllm:prefix_cache_hits_total")
    h200 = []
    for p in heavy:
        body = {"model": "openai/gpt-oss-120b", "max_tokens": 200, "reasoning_effort": "low",
                "messages": [{"role": "system", "content": PREFIX.replace("CHIMERA", "CHIMERA-H")}, {"role": "user", "content": p}]}
        req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {tok}"})
        u = json.load(urllib.request.urlopen(req, timeout=300))["usage"]  # noqa: S310
        h200.append({"prompt_tokens": u["prompt_tokens"], "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens")})
    q1, h1 = metric(url, "vllm:prefix_cache_queries_total"), metric(url, "vllm:prefix_cache_hits_total")
    out["h200"] = {"calls": h200, "queries": q1 - q0, "hits": h1 - h0}
    out["price"] = {"in": PRICE_IN, "cached": PRICE_CACHED}
    (STORE / "kv.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out["h200"]))


if __name__ == "__main__":
    main()
