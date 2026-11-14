"""SpeculativeCascadeRouter: every LLM call goes through generate().

Order: exact cache -> semantic cache -> (heavy task? hand off) -> local draft ->
confident? return : escalate (verify if same-family tokenizer, else handoff).
"""
from __future__ import annotations

import re
import time
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from .cache.exact_cache import ExactCache
from .cache.semantic_cache import SemanticCache
from .inference.cloud_verifier import CloudVerifier
from .inference.handoff import build_brief, cloud_prompt
from .inference.local_draft import DraftBackend, DraftResult, chatml, should_escalate
from .inference.telemetry import Telemetry, TelemetryTracker

HEAVY_HINTS = re.compile(
    r"\b(refactor|architecture|migrate|redesign|implement|debug|optimi[sz]e|concurrency|"
    r"across (the )?(repo|codebase)|multi-?file|design)\b",
    re.I,
)


def complexity_score(prompt: str) -> float:
    """0..1 heuristic. Long prompts, code fences and heavy keywords push it up."""
    score = min(len(prompt) / 4000, 0.5)
    score += 0.2 * min(prompt.count("```") // 2, 2)
    score += 0.15 * min(len(HEAVY_HINTS.findall(prompt)), 3)
    return min(score, 1.0)


class Tokenizer(Protocol):
    def encode(self, text: str) -> list[int]: ...
    def decode(self, ids: list[int]) -> str: ...


class RouterConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    min_confidence: float = 0.85
    heavy_threshold: float = 0.6
    max_local_tokens: int = 512
    max_cloud_tokens: int = 2048
    cloud_dollars_per_1k_tokens: float = 0.002
    namespace: str = ""


class GenerateResult(BaseModel):
    text: str
    telemetry: Telemetry


class SpeculativeCascadeRouter:
    def __init__(
        self,
        local: DraftBackend,
        cloud: CloudVerifier | None = None,
        exact: ExactCache | None = None,
        semantic: SemanticCache | None = None,
        tracker: TelemetryTracker | None = None,
        config: RouterConfig | None = None,
        tokenizer: Tokenizer | None = None,
    ) -> None:
        self.local, self.cloud = local, cloud
        self.exact = exact or ExactCache()
        self.semantic = semantic
        self.tracker = tracker or TelemetryTracker()
        self.cfg = config or RouterConfig()
        self.tokenizer = tokenizer

    # ---- public API -------------------------------------------------------
    def generate(self, prompt: str, context: str = "") -> GenerateResult:
        t0 = time.perf_counter()
        est_tokens = max(len(prompt) // 4, 1)
        ns = self.cfg.namespace

        hit = self.exact.get(prompt, ns)
        if hit is not None:
            return self._done(hit, "exact_cache", t0, tokens_saved=est_tokens + len(hit) // 4)

        if self.semantic is not None:
            sem = self.semantic.get(prompt, ns)
            if sem is not None:
                return self._done(sem[0], "semantic_cache", t0, tokens_saved=est_tokens + len(sem[0]) // 4)

        heavy = complexity_score(prompt) >= self.cfg.heavy_threshold
        if heavy and self.cloud is not None:
            return self._handoff(prompt, context, t0, draft=None)

        draft = self.local.complete(prompt, self.cfg.max_local_tokens)
        if not should_escalate(draft, self.cfg.min_confidence) or self.cloud is None:
            return self._store_local(prompt, draft, t0)

        if self.tokenizer is not None and draft.token_ids and all(i is not None for i in draft.token_ids):
            return self._verify(prompt, draft, t0)
        return self._handoff(prompt, context, t0, draft=draft)

    # ---- paths --------------------------------------------------------------
    def _store_local(self, prompt: str, draft: DraftResult, t0: float) -> GenerateResult:
        self._remember(prompt, draft.text)
        return self._done(
            draft.text, "local", t0, tokens_saved=draft.n_tokens, local_tokens=draft.n_tokens
        )

    def _verify(self, prompt: str, draft: DraftResult, t0: float) -> GenerateResult:
        assert self.cloud and self.tokenizer
        # The draft saw the ChatML-wrapped prompt, so the target must score the same ids.
        prompt_ids = self.tokenizer.encode(chatml(prompt) if getattr(self.local, "chatml", False) else prompt)
        draft_ids = [i for i in draft.token_ids if i is not None]
        res = self.cloud.verify(prompt_ids, draft_ids, draft.logprobs)
        out_ids = res.accepted_ids + ([res.correction_id] if res.correction_id is not None else [])
        text = self.tokenizer.decode(out_ids)
        self._remember(prompt, text)
        return self._done(
            text, "cloud_verified", t0, tokens_saved=res.n_accepted, alpha=res.alpha,
            local_tokens=len(draft_ids), cloud_tokens=len(draft_ids) - res.n_accepted + 1,
        )

    def _handoff(self, prompt: str, context: str, t0: float, draft: DraftResult | None) -> GenerateResult:
        assert self.cloud
        brief = build_brief(self.local, prompt, context)
        full = cloud_prompt(prompt, brief, draft.text if draft else "")
        text = self.cloud.handoff(full, self.cfg.max_cloud_tokens)
        self._remember(prompt, text)
        return self._done(text, "cloud_handoff", t0, cloud_tokens=len(text) // 4,
                          local_tokens=len(brief) // 4)

    # ---- helpers ------------------------------------------------------------
    def _remember(self, prompt: str, text: str) -> None:
        self.exact.put(prompt, text, self.cfg.namespace)
        if self.semantic is not None:
            self.semantic.put(prompt, text, self.cfg.namespace)

    def _done(
        self, text: str, tier: str, t0: float, tokens_saved: int = 0, alpha: float | None = None,
        local_tokens: int = 0, cloud_tokens: int = 0,
    ) -> GenerateResult:
        tel = Telemetry(
            tier_used=tier, tokens_saved=tokens_saved, acceptance_rate_alpha=alpha,
            latency_ms=(time.perf_counter() - t0) * 1000,
            dollars_saved=tokens_saved / 1000 * self.cfg.cloud_dollars_per_1k_tokens,
            local_tokens=local_tokens, cloud_tokens=cloud_tokens,
        )
        self.tracker.emit(tel)
        return GenerateResult(text=text, telemetry=tel)
