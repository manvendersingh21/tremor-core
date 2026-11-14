import math

from chimera_core.inference.local_draft import DraftResult
from chimera_core.ladder import LadderConfig, LadderRouter


class Local:
    def __init__(self, conf=0.95):
        self.conf, self.calls = conf, 0

    def complete(self, prompt, max_tokens=256, system=None):
        self.calls += 1
        return DraftResult(text="local", token_ids=[1], logprobs=[math.log(self.conf)], mean_confidence=self.conf)


class Text:
    """Fake mid/top. Replies 'ESCALATE' to the self-check prompt when escalate=True."""

    def __init__(self, name, escalate=False):
        self.name, self.escalate, self.prompts = name, escalate, []

    def complete(self, prompt, max_tokens):
        self.prompts.append(prompt)
        if prompt.startswith("Task:\n") and "Proposed answer" in prompt:
            return "ESCALATE" if self.escalate else "OK"
        return self.name


def make(conf=0.95, escalate=False, **cfg):
    mid, top = Text("mid", escalate), Text("top")
    return LadderRouter(Local(conf), mid, top, LadderConfig(**cfg)), mid, top


def test_confident_3b_answers_and_second_call_is_cached():
    r, mid, top = make()
    assert r.generate("hi").telemetry.tier_used == "local"
    assert r.generate("hi").telemetry.tier_used == "exact_cache"
    assert not mid.prompts and not top.prompts


def test_unsure_3b_goes_to_mid_and_stops_there():
    r, mid, top = make(conf=0.3)
    out = r.generate("hi")
    assert (out.text, out.telemetry.tier_used) == ("mid", "gpu")
    assert not top.prompts and out.telemetry.tokens_saved > 0


def test_mid_self_check_escalate_climbs_with_short_brief():
    r, mid, top = make(conf=0.3, escalate=True)
    out = r.generate("hi")
    assert out.telemetry.tier_used == "top"
    assert top.prompts[0].startswith("Brief from an assistant:")


def test_heavy_task_skips_3b_and_mid_answer_and_no_brief_sends_prompt_as_is():
    heavy = "Refactor and redesign the architecture, then implement it. " * 5
    r, mid, top = make(use_brief=False, heavy_threshold=0.3)
    out = r.generate(heavy)
    assert out.telemetry.tier_used == "top" and r.local.calls == 0
    assert top.prompts == [heavy] and not mid.prompts


def test_failed_check_climbs_even_when_3b_is_confident():
    r, mid, top = make()
    out = r.generate("write code", check=lambda a: a == "top")
    assert out.telemetry.tier_used == "top" and r.local.calls == 1
