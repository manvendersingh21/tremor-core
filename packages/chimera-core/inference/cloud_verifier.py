"""Tier 3: cloud target model (vLLM / SGLang, OpenAI-compatible API).

Two modes:
  * handoff: send a text brief, get a full answer (any model pair).
  * verify:  lossless speculative verification of local draft tokens (same model family only).
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import urllib.request
from typing import Protocol

from pydantic import BaseModel


class VerifyResult(BaseModel):
    accepted_ids: list[int]
    correction_id: int | None = None  # token sampled from the target at the first rejection
    alpha: float = 0.0  # accepted / drafted

    @property
    def n_accepted(self) -> int:
        return len(self.accepted_ids)


def rejection_sample(
    draft_ids: list[int],
    draft_logprobs: list[float],
    target_logprobs: list[float],
    rng: random.Random | None = None,
) -> tuple[int, float]:
    """Walk the draft left to right. Accept token i with probability min(1, p_t / p_d).

    Returns (number accepted, alpha). Stops at the first rejection.
    """
    rng = rng or random.Random()
    accepted = 0
    for lp_d, lp_t in zip(draft_logprobs, target_logprobs):
        ratio = min(1.0, math.exp(lp_t - lp_d))
        if rng.random() < ratio:
            accepted += 1
        else:
            break
    alpha = accepted / len(draft_ids) if draft_ids else 0.0
    return accepted, alpha


class CloudBackend(Protocol):
    def complete(self, prompt: str, max_tokens: int) -> str: ...

    def score_tokens(self, prompt_ids: list[int], draft_ids: list[int]) -> list[float]:
        """Target-model logprob of each draft token given prompt + preceding draft tokens."""
        ...

    def sample_next(self, context_ids: list[int]) -> int: ...


class VllmBackend:
    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def _post(self, path: str, payload: dict) -> dict:
        headers = {"Content-Type": "application/json", "User-Agent": "chimera/0.1"}  # GMI 403s the default urllib agent
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=json.dumps(payload).encode(), headers=headers
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            return json.load(resp)

    def complete(self, prompt: str, max_tokens: int = 1024) -> str:
        data = self._post(
            "/v1/chat/completions",
            {"model": self.model, "max_tokens": max_tokens,
             "messages": [{"role": "user", "content": prompt}]},
        )
        return data["choices"][0]["message"]["content"]

    def score_tokens(self, prompt_ids: list[int], draft_ids: list[int]) -> list[float]:
        # vLLM: echo prompt logprobs for the whole sequence in one forward pass.
        data = self._post(
            "/v1/completions",
            {"model": self.model, "prompt": prompt_ids + draft_ids, "max_tokens": 1,
             "echo": True, "logprobs": 0},
        )
        lps = data["choices"][0]["logprobs"]["token_logprobs"]
        return [float(x) for x in lps[len(prompt_ids): len(prompt_ids) + len(draft_ids)]]

    def sample_next(self, context_ids: list[int]) -> int:
        data = self._post(
            "/v1/completions",
            {"model": self.model, "prompt": context_ids, "max_tokens": 1,
             "return_tokens_as_token_ids": True, "logprobs": 0},
        )
        tok = data["choices"][0]["logprobs"]["tokens"][0]  # "token_id:123"
        return int(str(tok).split(":")[-1])


class SpecVerifierBackend:
    """Client for bench/verify_server.py (llama.cpp target on the GPU box, reached via ssh tunnel).

    One POST per round trip: only token ids go up and logprobs/token ids come back. The reply
    also holds a target sample for every position, so `sample_next` is served from it with no
    second request. `last` is that reply; `bytes_up`/`bytes_down` count the last request.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:18101", temperature: float = 1.0,
                 timeout: float = 120) -> None:
        self.base_url, self.temperature, self.timeout = base_url.rstrip("/"), temperature, timeout
        self.last: dict = {}
        self._n_prompt = 0
        self.bytes_up = self.bytes_down = 0

    def complete(self, prompt: str, max_tokens: int) -> str:
        raise NotImplementedError("verify-only backend")

    def score_tokens(self, prompt_ids: list[int], draft_ids: list[int]) -> list[float]:
        body = json.dumps({"prompt_ids": prompt_ids, "draft_ids": draft_ids,
                           "temperature": self.temperature}).encode()
        req = urllib.request.Request(f"{self.base_url}/verify", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
            raw = resp.read()
        self.bytes_up, self.bytes_down = len(body), len(raw)
        self.last, self._n_prompt = json.loads(raw), len(prompt_ids)
        return [float(x) for x in self.last["logprobs"]]

    def sample_next(self, context_ids: list[int]) -> int:
        return int(self.last["next_ids"][len(context_ids) - self._n_prompt])


class CrusoeBackend(VllmBackend):
    """Crusoe serverless (OpenAI-compatible). Key comes from the CRUSOE_API_KEY env var only.

    Qwen3.8 emits `reasoning_content` and can leave `content` empty at small max_tokens, so
    `complete` falls back to the reasoning text. Real usage of the last call is in `last_usage`
    and every call is appended to `usage_log`.
    """

    def __init__(self, model: str = "Qwen/Qwen3.8-27B", api_key: str | None = None,
                 base_url: str = "https://api.inference.crusoecloud.com", timeout: float = 300,
                 thinking: bool = False) -> None:
        key = api_key if api_key is not None else os.environ.get("CRUSOE_API_KEY", "")
        if not key:
            raise RuntimeError("CRUSOE_API_KEY is not set")
        super().__init__(base_url, model, key, timeout)
        self.thinking = thinking  # False sends enable_thinking=false: no reasoning tokens billed
        self.last_usage: dict[str, int] = {}
        self.usage_log: list[dict[str, int]] = []

    def complete(self, prompt: str, max_tokens: int = 4096) -> str:
        data = self._post(
            "/v1/chat/completions",
            {"model": self.model, "max_tokens": max_tokens,
             "chat_template_kwargs": {"enable_thinking": self.thinking},
             "messages": [{"role": "user", "content": prompt}]},
        )
        u = data.get("usage", {})
        self.last_usage = {
            "prompt_tokens": u.get("prompt_tokens", 0),
            "completion_tokens": u.get("completion_tokens", 0),
            "reasoning_tokens": u.get("reasoning_tokens", 0),
            "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
        }
        self.usage_log.append(self.last_usage)
        msg = data["choices"][0]["message"]
        return (msg.get("content") or "").strip() or (msg.get("reasoning_content") or "")


class OllamaBackend(VllmBackend):
    """Ollama native /api/chat (handoff only; no echo scoring). Real counts go to `usage_log`.

    Sends think=false; any `<think>` block still present in the text is stripped.
    Same usage keys as CrusoeBackend so the router and bench treat both alike.
    """

    def __init__(self, model: str = "qwen3:30b-instruct", base_url: str = "http://127.0.0.1:11435",
                 timeout: float = 600, thinking: bool = False, options: dict | None = None,
                 keep_alive: int | str | None = None) -> None:
        super().__init__(base_url, model, "", timeout)
        self.thinking = thinking
        self.options = dict(options or {})  # Ollama runtime options, e.g. num_thread (a 4-CPU box: 4, not the host's core count)
        self.keep_alive = keep_alive
        self.last_usage: dict[str, int] = {}
        self.usage_log: list[dict[str, int]] = []

    def complete(self, prompt: str, max_tokens: int = 4096) -> str:
        body = {"model": self.model, "stream": False, "think": self.thinking, "logprobs": True,
                "options": {**self.options, "num_predict": max_tokens},
                "messages": [{"role": "user", "content": prompt}]}
        if self.keep_alive is not None:
            body["keep_alive"] = self.keep_alive
        data = self._post("/api/chat", body)
        lps = [x["logprob"] for x in data.get("logprobs") or [] if x.get("logprob") is not None]
        # Mean token probability, the same gate signal as the llama.cpp tier. None when Ollama sends no logprobs.
        self.last_confidence = sum(math.exp(x) for x in lps) / len(lps) if lps else None
        self.last_usage = {
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "completion_tokens": data.get("eval_count", 0),
            "cached_tokens": data.get("prompt_eval_cached_count", 0),
            "total_duration_ms": round(data.get("total_duration", 0) / 1e6),
            "load_duration_ms": round(data.get("load_duration", 0) / 1e6),
        }
        self.usage_log.append(self.last_usage)
        text = (data.get("message") or {}).get("content") or ""
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


class CloudVerifier:
    def __init__(self, backend: CloudBackend, rng: random.Random | None = None) -> None:
        self.backend = backend
        self._rng = rng

    def handoff(self, prompt: str, max_tokens: int = 1024) -> str:
        return self.backend.complete(prompt, max_tokens)

    def verify(
        self, prompt_ids: list[int], draft_ids: list[int], draft_logprobs: list[float]
    ) -> VerifyResult:
        target_lps = self.backend.score_tokens(prompt_ids, draft_ids)
        n, alpha = rejection_sample(draft_ids, draft_logprobs, target_lps, self._rng)
        correction = None
        if n < len(draft_ids):
            # Sample from the target at the rejection point (approximation of the residual).
            correction = self.backend.sample_next(prompt_ids + draft_ids[:n])
        return VerifyResult(accepted_ids=draft_ids[:n], correction_id=correction, alpha=alpha)
