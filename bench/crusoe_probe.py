"""One short chat call per Crusoe model with the flags we ship. Appends a row to
bench/.scratch/crusoe_tiers/probe.jsonl. The key comes from the env or .env and is never printed.

    python3 bench/crusoe_probe.py [model ...]     # default: every model in PROBES
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "bench" / ".scratch" / "crusoe_tiers" / "probe.jsonl"
URL = "https://api.inference.crusoecloud.com"
PROMPT = "Write a Python function fizzbuzz(n) that returns the FizzBuzz string for n. Code only."
# model -> (chat_template_kwargs, top-level reasoning_effort or None)
PROBES = {
    "nvidia/Nemotron-3.5-Lightning-30B-A3B": ({"enable_thinking": False}, None),
    "openai/gpt-oss-120b": ({"reasoning_effort": "low"}, "low"),
    "nvidia/NVIDIA-Nemotron-3.5-Super-VL": ({"enable_thinking": False}, None),
    "google/gemma-4-31b-it": ({}, None),
    "zai-org/GLM-5.3-Flash": ({"thinking": False}, None),
    "nvidia/Nemotron-3-Nano-Omni-Reasoning-30B-A3B": ({"enable_thinking": False}, None),
    "Qwen/Qwen3.8-27B": ({"enable_thinking": False}, None),
    "deepseek-ai/DeepSeek-V4.1-Flash": ({"thinking": False}, None),
}


def _key() -> str:
    k = os.environ.get("CRUSOE_API_KEY", "")
    env = ROOT / ".env"
    if not k and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("CRUSOE_API_KEY="):
                k = line.split("=", 1)[1].strip().strip("\"'")
    return k


def probe(model: str, kwargs: dict, effort: str | None, key: str, max_tokens: int = 400) -> dict:
    body = {"model": model, "max_tokens": max_tokens, "logprobs": True, "chat_template_kwargs": kwargs,
            "messages": [{"role": "user", "content": PROMPT}]}
    if effort:
        body["reasoning_effort"] = effort
    row = {"model": model, "flags": {**kwargs, **({"reasoning_effort_top": effort} if effort else {})},
           "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    req = urllib.request.Request(URL + "/v1/chat/completions", json.dumps(body).encode(), {
        "Content-Type": "application/json", "Authorization": f"Bearer {key}", "User-Agent": "chimera/0.1"})
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        return {**row, "error": f"HTTP {e.code}", "ms": round((time.perf_counter() - t) * 1000)}
    except Exception as e:  # noqa: BLE001
        return {**row, "error": type(e).__name__, "ms": round((time.perf_counter() - t) * 1000)}
    ch, u = d["choices"][0], d.get("usage", {})
    content = (ch["message"].get("content") or "").strip()
    return {**row, "non_empty": bool(content), "tokens_in": u.get("prompt_tokens"), "tokens_out": u.get("completion_tokens"),
            "ms": round((time.perf_counter() - t) * 1000), "logprobs": bool((ch.get("logprobs") or {}).get("content")),
            "has_reasoning_field": bool(ch["message"].get("reasoning_content") or ch["message"].get("reasoning")),
            "finish": ch.get("finish_reason")}


def main() -> None:
    key = _key()
    if not key:
        sys.exit("CRUSOE_API_KEY is not set")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for m in sys.argv[1:] or PROBES:
        kw, eff = PROBES[m]
        row = probe(m, kw, eff, key)
        with OUT.open("a") as f:
            f.write(json.dumps(row) + "\n")
        print(json.dumps(row))


if __name__ == "__main__":
    main()
