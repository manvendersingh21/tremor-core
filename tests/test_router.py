import math
import random

from chimera_core import RouterConfig, SpeculativeCascadeRouter
from chimera_core.cache.exact_cache import ExactCache
from chimera_core.cache.semantic_cache import SemanticCache
from chimera_core.firewall.risk_scorer import score_action, verify_approval
from chimera_core.inference.cloud_verifier import CloudVerifier, rejection_sample
from chimera_core.inference.local_draft import DraftResult, confidence_stats


class FakeLocal:
    def __init__(self, text="local answer", conf=0.95):
        self.text, self.conf, self.calls = text, conf, 0

    def complete(self, prompt, max_tokens=256, system=None):
        self.calls += 1
        lp = math.log(self.conf)
        return DraftResult(text=self.text, token_ids=[1, 2, 3], logprobs=[lp] * 3, mean_confidence=self.conf)


class FakeCloud:
    def __init__(self):
        self.prompts = []

    def complete(self, prompt, max_tokens):
        self.prompts.append(prompt)
        return "cloud answer"

    def score_tokens(self, prompt_ids, draft_ids):
        return [0.0] * len(draft_ids)  # target is certain: always accept

    def sample_next(self, ctx):
        return 99


class BagEmbedder:
    VOCAB = ["capital", "france", "paris", "city", "python", "sort"]

    def embed(self, text):
        t = text.lower()
        return [float(w in t) for w in self.VOCAB]


def make(local=None, cloud=None, **cfg):
    return SpeculativeCascadeRouter(
        local or FakeLocal(), CloudVerifier(cloud or FakeCloud()),
        semantic=SemanticCache(BagEmbedder()), config=RouterConfig(**cfg),
    )


def test_confident_local_answer_stays_local_and_is_cached():
    r = make()
    out = r.generate("What is 2+2?")
    assert out.telemetry.tier_used == "local"
    assert r.generate("what is   2+2?").telemetry.tier_used == "exact_cache"


def test_semantic_cache_hit_on_paraphrase():
    local = FakeLocal("Paris")
    r = make(local)
    r.generate("What is the capital of France?")
    out = r.generate("the capital of France?")
    assert out.text == "Paris" and out.telemetry.tier_used == "semantic_cache"
    assert local.calls == 1


def test_low_confidence_hands_off_to_cloud_with_brief():
    cloud = FakeCloud()
    r = make(FakeLocal(conf=0.3), cloud)
    out = r.generate("Why does this fail?")
    assert out.telemetry.tier_used == "cloud_handoff"
    assert "# Brief" in cloud.prompts[0] and "# Original request" in cloud.prompts[0]


def test_heavy_task_skips_local_answer():
    cloud = FakeCloud()
    local = FakeLocal()
    r = make(local, cloud, heavy_threshold=0.3)
    out = r.generate("Refactor and migrate the architecture across the codebase " + "x" * 1500)
    assert out.telemetry.tier_used == "cloud_handoff"


def test_rejection_sampling_accepts_when_target_agrees():
    n, alpha = rejection_sample([1, 2], [math.log(0.5)] * 2, [0.0, 0.0], random.Random(0))
    assert (n, alpha) == (2, 1.0)


def test_rejection_sampling_rejects_when_target_disagrees():
    n, _ = rejection_sample([1, 2], [0.0, 0.0], [-50.0, 0.0], random.Random(0))
    assert n == 0


def test_confidence_stats():
    conf, _ = confidence_stats([math.log(0.9), math.log(0.8)])
    assert abs(conf - 0.85) < 1e-9


def test_exact_cache_lru():
    c = ExactCache(max_entries=1)
    c.put("a", "1")
    c.put("b", "2")
    assert c.get("a") is None and c.get("b") == "2"


def test_firewall():
    assert score_action("Tap Pay").needs_approval
    assert score_action("Merge PR #4").score >= 70
    assert not score_action("Scroll down").needs_approval
    v = score_action("rm -rf /tmp/x")
    assert v.needs_approval and verify_approval(v, f"yes {v.approval_token}")
    assert not verify_approval(v, "yes")
