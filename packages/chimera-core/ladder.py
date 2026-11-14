"""LadderRouter: caches -> local 3B -> mid (GPU 30B) -> top (big Crusoe model).

Each tier answers what it can. Climb rules:
  3B -> mid : 3B logprob confidence < min_confidence, or `check(answer)` fails, or the task is heavy.
  mid -> top: heavy task (complexity_score), mid self-check says ESCALATE, or `check` fails.
On a climb to the top the mid model writes a short brief (<= brief_max_tokens) unless use_brief=False.
Heavy tasks skip the 3B and the mid's own answer: mid only writes the brief.
"""
from __future__ import annotations

import time
from typing import Callable, Protocol

from .inference.cloud_verifier import CrusoeBackend
from .inference.local_draft import should_escalate
from .inference.telemetry import Telemetry
from .router import GenerateResult, RouterConfig, SpeculativeCascadeRouter, complexity_score

BRIEF_PROMPT = (
    "Write a brief for a stronger engineer model that will solve the task below. Max 120 words: "
    "key requirements, pitfalls, expected output format. Do NOT solve the task.\n\nTASK:\n{task}"
)
CHECK_PROMPT = (
    "Task:\n{task}\n\nProposed answer:\n{answer}\n\nIs the answer correct and complete? "
    "Reply with exactly one word: OK or ESCALATE."
)


class TextBackend(Protocol):
    def complete(self, prompt: str, max_tokens: int) -> str: ...


class LadderConfig(RouterConfig):
    use_brief: bool = True
    brief_max_tokens: int = 200
    max_mid_tokens: int = 1500
    max_top_tokens: int = 2500
    top_usd_per_m_in: float = 0.05  # gpt-oss-120b list price on Crusoe; used for dollars_saved
    top_usd_per_m_out: float = 0.25


class TopBackend(CrusoeBackend):
    """Crusoe chat with caller-chosen chat_template_kwargs (gpt-oss: reasoning_effort, DeepSeek: thinking)."""

    def __init__(self, model: str, template_kwargs: dict | None = None, **kw) -> None:
        super().__init__(model=model, **kw)
        self.template_kwargs = template_kwargs or {}

    def complete(self, prompt: str, max_tokens: int = 2500) -> str:
        data = self._post(
            "/v1/chat/completions",
            {"model": self.model, "max_tokens": max_tokens, "chat_template_kwargs": self.template_kwargs,
             "messages": [{"role": "user", "content": prompt}]},
        )
        u = data.get("usage", {})
        self.last_usage = {
            "prompt_tokens": u.get("prompt_tokens", 0), "completion_tokens": u.get("completion_tokens", 0),
            "cached_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
        }
        self.usage_log.append(self.last_usage)
        msg = data["choices"][0]["message"]
        return (msg.get("content") or "").strip()


class LadderRouter(SpeculativeCascadeRouter):
    def __init__(self, local, mid: TextBackend, top: TextBackend, config: LadderConfig | None = None, **kw):
        super().__init__(local, cloud=None, config=config or LadderConfig(), **kw)
        self.mid, self.top = mid, top

    def generate(self, prompt: str, context: str = "", check: Callable[[str], bool] | None = None) -> GenerateResult:
        t0 = time.perf_counter()
        cfg = self.cfg
        ns = cfg.namespace
        hit = self.exact.get(prompt, ns)
        if hit is not None:
            return self._emit(prompt, "exact_cache", hit, t0)
        if self.semantic is not None and (sem := self.semantic.get(prompt, ns)) is not None:
            return self._emit(prompt, "semantic_cache", sem[0], t0)

        local_tokens = 0
        if complexity_score(prompt) < cfg.heavy_threshold:
            draft = self.local.complete(prompt, cfg.max_local_tokens)
            local_tokens = draft.n_tokens
            if not should_escalate(draft, cfg.min_confidence) and (check is None or check(draft.text)):
                return self._emit(prompt, "local", draft.text, t0, local_tokens=local_tokens)
            mid_text = self.mid.complete(prompt, cfg.max_mid_tokens)
            if check(mid_text) if check else not self._mid_says_escalate(prompt, mid_text):
                return self._emit(prompt, "gpu", mid_text, t0, local_tokens=local_tokens)

        brief = self.mid.complete(BRIEF_PROMPT.format(task=prompt), cfg.brief_max_tokens) if cfg.use_brief else ""
        top_prompt = f"Brief from an assistant:\n{brief}\n\nTask:\n{prompt}" if brief else prompt
        text = self.top.complete(top_prompt, cfg.max_top_tokens)
        return self._emit(prompt, "top", text, t0, local_tokens=local_tokens)

    def _mid_says_escalate(self, prompt: str, answer: str) -> bool:
        return "ESCALATE" in self.mid.complete(CHECK_PROMPT.format(task=prompt, answer=answer), 8).upper()

    def _emit(self, prompt: str, tier: str, text: str, t0: float, local_tokens: int = 0) -> GenerateResult:
        """tokens_saved/dollars_saved = top-model tokens this call did not use (estimated, len/4)."""
        if not tier.endswith("_cache"):
            self._remember(prompt, text)
        est_out = len(text) // 4
        saved_in, saved_out = (max(len(prompt) // 4, 1), est_out) if tier != "top" else (0, 0)
        tel = Telemetry(
            tier_used=tier, tokens_saved=saved_in + saved_out,
            latency_ms=(time.perf_counter() - t0) * 1000,
            dollars_saved=(saved_in * self.cfg.top_usd_per_m_in + saved_out * self.cfg.top_usd_per_m_out) / 1e6,
            local_tokens=local_tokens, gpu_tokens=est_out if tier == "gpu" else 0,
            cloud_tokens=est_out if tier == "top" else 0,
        )
        self.tracker.emit(tel)
        return GenerateResult(text=text, telemetry=tel)
