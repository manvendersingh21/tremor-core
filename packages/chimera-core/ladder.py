"""LadderRouter: caches -> local 3B -> mid (GPU 30B) -> top (big Crusoe model).

Each tier answers what it can. Climb rules:
  3B -> mid : 3B logprob confidence < min_confidence, or `check(answer)` fails, or the task is heavy.
  mid -> top: heavy task (complexity_score), mid self-check says ESCALATE, or `check` fails.
On a climb to the top the mid model writes a short brief (<= brief_max_tokens) unless use_brief=False.
Heavy tasks skip the 3B and the mid's own answer: mid only writes the brief.
"""
from __future__ import annotations

import math
import time
from typing import Callable, Protocol

from .inference.cloud_verifier import CrusoeBackend
from .inference.local_draft import should_escalate
from .inference.telemetry import Telemetry
from .router import Events, GenerateResult, RouterConfig, SpeculativeCascadeRouter, complexity_score

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
    use_brief: bool = False  # bench: a 30B brief was slower and no better; cap 200 tokens when on
    brief_max_tokens: int = 200
    learned_router: str = ""  # path to router_weights.json (bench/train_router.py); "" = keyword complexity_score + confidence gate
    max_mid_tokens: int = 1500
    max_top_tokens: int = 2500
    top_usd_per_m_in: float = 0.05  # gpt-oss-120b list price on Crusoe; used for dollars_saved
    top_usd_per_m_out: float = 0.25


class TopBackend(CrusoeBackend):
    """Crusoe chat with caller-chosen chat_template_kwargs (gpt-oss: reasoning_effort, DeepSeek: thinking)."""

    def __init__(self, model: str, template_kwargs: dict | None = None, logprobs: bool = False, **kw) -> None:
        super().__init__(model=model, **kw)
        self.template_kwargs = template_kwargs or {}
        self.logprobs = logprobs  # vLLM: mean token probability of the answer -> last_confidence (the 30B gate)
        self.last_confidence: float | None = None

    def complete(self, prompt: str, max_tokens: int = 2500) -> str:
        body = {"model": self.model, "max_tokens": max_tokens, "chat_template_kwargs": self.template_kwargs,
                "messages": [{"role": "user", "content": prompt}]}
        if "reasoning_effort" in self.template_kwargs:  # vLLM gpt-oss reads it top-level, not from the template
            body["reasoning_effort"] = self.template_kwargs["reasoning_effort"]
        if self.logprobs:
            body["logprobs"] = True
        data = self._post("/v1/chat/completions", body)
        lps = [x["logprob"] for x in ((data["choices"][0].get("logprobs") or {}).get("content") or [])
               if x.get("logprob") is not None]
        self.last_confidence = sum(math.exp(x) for x in lps) / len(lps) if lps else None
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
        self.learned = None
        if self.cfg.learned_router:
            from .learned_router import LearnedRouter
            self.learned = LearnedRouter.load(self.cfg.learned_router)

    def generate(self, prompt: str, context: str = "", check: Callable[[str], bool] | None = None,
                 on_event=None) -> GenerateResult:
        t0 = time.perf_counter()
        cfg = self.cfg
        ev = Events(on_event)
        if (hit := self._lookup(prompt, ev)) is not None:
            return self._emit(prompt, hit[1], hit[0], t0, source=hit[2])

        local_tokens, ms, mid_ok = 0, {}, True
        if (not self.learned.skip_local(prompt)) if self.learned else complexity_score(prompt) < cfg.heavy_threshold:
            t = time.perf_counter()
            draft = self.local.complete(prompt, cfg.max_local_tokens)
            ms["local"] = (time.perf_counter() - t) * 1000
            local_tokens = draft.n_tokens
            keep = (self.learned.keep_local(prompt, draft.logprobs, draft.mean_confidence, draft.mean_entropy)
                    if self.learned else not should_escalate(draft, cfg.min_confidence))
            if keep and (check is None or check(draft.text)):
                return self._emit(prompt, "local", draft.text, t0, local_tokens=local_tokens, ms=ms,
                                  cache=draft.mean_confidence >= cfg.min_cache_confidence, ev=ev)
            t = time.perf_counter()
            try:
                mid_text = self.mid.complete(prompt, cfg.max_mid_tokens)
                ms["mid"] = (time.perf_counter() - t) * 1000
                if check(mid_text) if check else not self._mid_says_escalate(prompt, mid_text):
                    return self._emit(prompt, "gpu", mid_text, t0, local_tokens=local_tokens, ms=ms, ev=ev)
            except OSError:  # timeout / tunnel down: skip the mid tier for this call
                mid_ok = False
                ms["mid"] = (time.perf_counter() - t) * 1000

        brief = ""
        if cfg.use_brief and mid_ok:
            try:
                t = time.perf_counter()
                brief = self.mid.complete(BRIEF_PROMPT.format(task=prompt), cfg.brief_max_tokens)
                ms["brief"] = (time.perf_counter() - t) * 1000
            except OSError:
                pass
        top_prompt = f"Brief from an assistant:\n{brief}\n\nTask:\n{prompt}" if brief else prompt
        t = time.perf_counter()
        text = self.top.complete(top_prompt, cfg.max_top_tokens)
        ms["top"] = (time.perf_counter() - t) * 1000
        return self._emit(prompt, "top", text, t0, local_tokens=local_tokens, ms=ms, ev=ev)

    def _mid_says_escalate(self, prompt: str, answer: str) -> bool:
        return "ESCALATE" in self.mid.complete(CHECK_PROMPT.format(task=prompt, answer=answer), 8).upper()

    def _emit(self, prompt: str, tier: str, text: str, t0: float, local_tokens: int = 0,
              ms: dict | None = None, cache: bool = True, ev: Events | None = None,
              source: str | None = None) -> GenerateResult:
        """tokens_saved/dollars_saved = top-model tokens this call did not use (estimated, len/4)."""
        if cache and not tier.endswith("_cache"):
            self._remember(prompt, text)
        est_out = len(text) // 4
        saved_in, saved_out = (max(len(prompt) // 4, 1), est_out) if tier != "top" else (0, 0)
        ev = ev or Events()
        saved, dollars = saved_in + saved_out, (saved_in * self.cfg.top_usd_per_m_in + saved_out * self.cfg.top_usd_per_m_out) / 1e6
        lat = (time.perf_counter() - t0) * 1000
        ev("final", {"tier": tier, "model": "", "tokens_in": 0, "tokens_out": est_out, "cached_tokens": 0, "dollars": 0.0,
                     "dollars_saved": round(dollars, 6), "ms": round(lat, 1), "tokens_kept_off_big": saved, "cache": source})
        tel = Telemetry(
            tier_used=tier, tokens_saved=saved, latency_ms=lat, dollars_saved=dollars,
            gpu_tokens=est_out if tier == "gpu" else 0, local_tokens=local_tokens,
            cloud_tokens=est_out if tier == "top" else 0, tier_ms=ms or {}, cache_source=source, events=ev.log,
        )
        self.tracker.emit(tel)
        return GenerateResult(text=text, telemetry=tel)
