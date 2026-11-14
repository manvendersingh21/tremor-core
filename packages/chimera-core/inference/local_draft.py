"""Tier 2: local draft model (llama.cpp / Ollama-compatible) with an entropy gate."""
from __future__ import annotations

import json
import math
import urllib.request
from typing import Protocol

from pydantic import BaseModel


class DraftResult(BaseModel):
    text: str
    token_ids: list[int | None] = []
    logprobs: list[float] = []
    mean_confidence: float = 0.0
    mean_entropy: float = 0.0

    @property
    def n_tokens(self) -> int:
        return len(self.logprobs)


class DraftBackend(Protocol):
    def complete(self, prompt: str, max_tokens: int, system: str | None = None) -> DraftResult: ...


def confidence_stats(
    logprobs: list[float], top_logprobs: list[list[float]] | None = None
) -> tuple[float, float]:
    """Return (mean probability of chosen tokens, mean Shannon entropy over the top-k)."""
    if not logprobs:
        return 0.0, 0.0
    conf = sum(math.exp(lp) for lp in logprobs) / len(logprobs)
    entropy = 0.0
    if top_logprobs:
        per_token = []
        for tops in top_logprobs:
            probs = [math.exp(x) for x in tops]
            total = sum(probs) or 1.0
            per_token.append(-sum((p / total) * math.log(p / total + 1e-12) for p in probs))
        entropy = sum(per_token) / len(per_token)
    return conf, entropy


def should_escalate(result: DraftResult, min_confidence: float = 0.85) -> bool:
    return result.mean_confidence < min_confidence


def chatml(prompt: str, system: str | None = None) -> str:
    sys_part = f"<|im_start|>system\n{system}<|im_end|>\n" if system else ""
    return f"{sys_part}<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"


class LlamaCppBackend:
    """Talks to a llama.cpp server (`llama-server`) using its native /completion endpoint.

    `cache_prompt=True` keeps the prompt prefix KV cache warm between calls.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8080", n_probs: int = 5, timeout: float = 120,
                 chatml: bool = True) -> None:
        # chatml: /completion takes a raw prompt, so instruct models (Qwen) need the ChatML wrapper.
        self.chatml = chatml
        self.base_url = base_url.rstrip("/")
        self.n_probs = n_probs
        self.timeout = timeout

    def complete(self, prompt: str, max_tokens: int = 256, system: str | None = None) -> DraftResult:
        full = chatml(prompt, system) if self.chatml else (f"{system}\n\n{prompt}" if system else prompt)
        body = json.dumps(
            {"prompt": full, "n_predict": max_tokens, "n_probs": self.n_probs,
             "cache_prompt": True, "temperature": 0.2}
        ).encode()
        req = urllib.request.Request(
            f"{self.base_url}/completion", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (local URL)
            data = json.load(resp)
        probs = data.get("completion_probabilities", [])
        ids: list[int | None] = []
        lps: list[float] = []
        tops: list[list[float]] = []
        for p in probs:
            ids.append(p.get("id"))
            lp = p.get("logprob")
            if lp is None and p.get("prob") is not None:
                lp = math.log(max(p["prob"], 1e-12))
            lps.append(lp if lp is not None else 0.0)
            cands = p.get("top_logprobs") or p.get("probs") or []
            tops.append([c.get("logprob", math.log(max(c.get("prob", 1e-12), 1e-12))) for c in cands])
        conf, ent = confidence_stats(lps, tops if any(tops) else None)
        return DraftResult(
            text=data.get("content", ""), token_ids=ids, logprobs=lps,
            mean_confidence=conf, mean_entropy=ent,
        )
