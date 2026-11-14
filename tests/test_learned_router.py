import json
import math

from chimera_core.inference.local_draft import DraftResult
from chimera_core.ladder import LadderConfig, LadderRouter
from chimera_core.learned_router import POST_FEATURES, PRE_FEATURES, LearnedRouter, prompt_features


def spec(pre_w, post_w, pre_t=0.5, post_t=0.5):
    def m(names, w):
        return {"features": names, "coef": w, "intercept": 0.0, "mean": [0.0] * len(names), "scale": [1.0] * len(names)}
    return {"pre": m(PRE_FEATURES, pre_w), "post": m(POST_FEATURES, post_w), "pre_threshold": pre_t, "post_threshold": post_t}


def only(names, **w):
    return [w.get(n, 0.0) for n in names]


def test_pre_skips_prompts_with_code_fences_and_post_follows_confidence():
    r = LearnedRouter(spec(only(PRE_FEATURES, fences=-3.0), only(POST_FEATURES, mean_conf=8.0), post_t=0.9))
    assert not r.skip_local("What is 2+2?")  # score 0 -> p=0.5, not below the 0.5 threshold
    assert r.skip_local("```py\nx\n```")
    assert r.keep_local("q", [math.log(0.99)], 0.99, 0.0)
    assert not r.keep_local("q", [math.log(0.2)], 0.2, 0.0)


def test_features_are_finite_and_cover_every_name():
    f = prompt_features("def f(x):\n    return 1\n")
    assert set(PRE_FEATURES) <= set(f) and all(math.isfinite(v) for v in f.values())


class Local:
    def complete(self, prompt, max_tokens=256, system=None):
        return DraftResult(text="local", token_ids=[1], logprobs=[math.log(0.99)], mean_confidence=0.99)


class Text:
    def __init__(self, name):
        self.name = name

    def complete(self, prompt, max_tokens):
        return "OK" if "Proposed answer" in prompt else self.name


def test_ladder_uses_learned_router_only_when_configured(tmp_path):
    f = tmp_path / "w.json"
    f.write_text(json.dumps(spec(only(PRE_FEATURES, has_def=-5.0), only(POST_FEATURES, mean_conf=1.0))))
    off = LadderRouter(Local(), Text("mid"), Text("top"), LadderConfig())
    on = LadderRouter(Local(), Text("mid"), Text("top"), LadderConfig(learned_router=str(f)))
    assert off.learned is None
    assert off.generate("def f(): pass").telemetry.tier_used == "local"  # keyword score says light
    assert on.generate("def f(): pass").telemetry.tier_used == "top"  # learned pre-model skips the 3B
    assert on.generate("hello").telemetry.tier_used == "local"
