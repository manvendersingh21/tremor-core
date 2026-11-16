import pytest

from chimera_core.tiers import AllTiersFailed, TierCfg, TierPool, can_verify


def cfg(name, mx, cost=0.0, family="qwen", enabled=True):
    return TierCfg(name=name, device="gpu", backend="ollama", url="http://x", family=family,
                   max_complexity=mx, cost_per_1k_out=cost, enabled=enabled)


class Fake:
    def __init__(self, name, fail=False, conf=None, log=None):
        self.name, self.fail, self.conf, self.log = name, fail, conf, log

    def complete(self, prompt, n):
        self.log.append(self.name)
        if self.fail:
            raise TimeoutError
        return self.name + "-answer", 10, 5, self.conf


def pool(tiers, fakes=None, **kw):
    log = []
    fakes = fakes or {}
    factory = lambda t: fakes.get(t.name, Fake(t.name, log=log)) if t.name not in fakes else _bind(fakes[t.name], log)
    kw.setdefault("probe", lambda t: True)
    return TierPool(tiers, backend_factory=factory, **kw), log


def _bind(f, log):
    f.log = log
    return f


def test_cheapest_fit():
    p, log = pool([cfg("big", 1.0, 1), cfg("small", 0.3), cfg("mid", 0.6)])
    assert p.generate("hi", 0.5).tier == "mid"
    assert p.generate("hi", 0.1).tier == "small"
    assert p.generate("hi", 0.9).tier == "big"


def test_climb_on_error_and_low_confidence():
    p, _ = pool([cfg("a", 0.5), cfg("b", 1.0, 1)], {"a": Fake("a", fail=True)})
    r = p.generate("hi", 0.1)
    assert r.tier == "b" and r.attempts == ["a", "b"] and r.per_tier["a"].errors == 1
    p, _ = pool([cfg("a", 0.5), cfg("b", 1.0, 1)], {"a": Fake("a", conf=0.2)}, min_confidence=0.85)
    r = p.generate("hi", 0.1)
    assert r.tier == "b" and r.per_tier["a"].tokens_out == 5  # low-confidence tokens still counted


def test_circuit_breaker_skips_then_recovers():
    now = [0.0]
    a = Fake("a", fail=True)
    p, log = pool([cfg("a", 0.5), cfg("b", 1.0, 1)], {"a": a}, breaker_threshold=2,
                  breaker_cooldown_s=30, clock=lambda: now[0], health_ttl_s=0)
    p.generate("x", 0.1), p.generate("x", 0.1)
    log.clear()
    assert p.generate("x", 0.1).attempts == ["b"]  # breaker open: a not tried
    assert "a" not in log
    now[0] = 31
    a.fail = False
    assert p.generate("x", 0.1).tier == "a"


def test_unhealthy_skipped_and_health_cached():
    calls = []
    p, _ = pool([cfg("a", 0.5), cfg("b", 1.0, 1)], probe=lambda t: calls.append(t.name) or t.name != "a")
    assert p.generate("x", 0.1).tier == "b"
    p.generate("x", 0.1)
    assert calls.count("a") == 1  # cached within ttl


def test_failed_call_marks_tier_down_until_next_probe():
    # A dead tunnel whose /api/tags still answers: one timeout, then skipped (not re-probed) for the health ttl.
    now = [0.0]
    p, log = pool([cfg("a", 0.5), cfg("b", 1.0, 1)], {"a": Fake("a", fail=True)}, clock=lambda: now[0], health_ttl_s=15)
    for _ in range(4):
        assert p.generate("x", 0.1).tier == "b"
    assert log.count("a") == 1
    now[0] = 16  # ttl over: probed again and tried again
    p.generate("x", 0.1)
    assert log.count("a") == 2


def h200(**kw):
    return TierCfg(name="h200", device="gpu", backend="openai", url="http://x", family="qwen", max_complexity=0.6,
                   warm_only=True, modal_app="app", **kw)


def test_warm_only_tier_cold_falls_through_and_wakes_once_then_serves_when_warm():
    now, warm, woke, later = [0.0], [False], [], []
    p, log = pool([cfg("gpu-small", 0.6), h200(), cfg("top", 1.0, 1, family="ds")], clock=lambda: now[0],
                  warm_check=lambda t: warm[0], waker=lambda t: woke.append(t.name), spawn=later.append)
    assert [t.name for t in p.tiers] == ["h200", "gpu-small", "top"]
    assert p.generate("x", 0.1).tier == "gpu-small"  # unknown = cold: no wait, next tier answers
    for f in later[:]:
        later.remove(f)
        f()  # the background warm check: cold, so it queues one wake
    while later:
        later.pop(0)()
    assert woke == ["h200"] and "h200" not in log
    p.generate("x", 0.1)
    assert not later  # checked moments ago: no new check, no second wake
    warm[0], now[0] = True, 16
    assert p.generate("x", 0.1).tier == "gpu-small"  # stale: answers from the last check, refreshes behind
    while later:
        later.pop(0)()
    assert p.generate("x", 0.1).tier == "h200" and woke == ["h200"]


def test_low_confidence_skips_a_same_family_tier_that_is_no_stronger():
    p, log = pool([h200(), cfg("gpu-small", 0.6), cfg("top", 1.0, 1, family="ds")], {"h200": Fake("h200", conf=0.3)},
                  min_confidence=0.95, warm_check=lambda t: True, spawn=lambda f: f())
    p.generate("x", 0.1)  # first call: warm state unknown, the check runs (synchronously here)
    log.clear()
    r = p.generate("x", 0.1)
    assert r.tier == "top" and log == ["h200", "top"]  # the Akash 30B (same model) is not asked again


def test_openai_tier_logprobs_become_confidence(monkeypatch):
    from chimera_core import ladder
    from chimera_core.tiers import build_backend
    sent = {}

    def post(self, path, body):
        sent.update(body)
        return {"choices": [{"message": {"content": "hi"}, "logprobs": {"content": [{"logprob": 0.0}, {"logprob": -0.6931}]}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2}}
    monkeypatch.setattr(ladder.TopBackend, "_post", post)
    monkeypatch.setenv("CRUSOE_API_KEY", "test")
    text, tin, tout, conf = build_backend(h200(logprobs=True, api_key_env="CRUSOE_API_KEY")).complete("q", 8)
    assert sent["logprobs"] is True and (text, tin, tout) == ("hi", 3, 2) and abs(conf - 0.75) < 1e-3


def test_ollama_tier_sends_options_and_keep_alive(monkeypatch):
    from chimera_core.inference import cloud_verifier as cv
    from chimera_core.tiers import build_backend
    sent = []

    def post(self, path, body):
        sent.append(body)
        return {"message": {"content": "hi"}, "prompt_eval_count": 3, "eval_count": 2, "logprobs": [{"logprob": 0.0}]}
    monkeypatch.setattr(cv.OllamaBackend, "_post", post)
    t = cfg("gpu-small", 0.6).model_copy(update={"options": {"num_thread": 4}, "keep_alive": -1})
    assert build_backend(t).complete("q", 8)[:3] == ("hi", 3, 2)
    assert sent[0]["options"] == {"num_thread": 4, "num_predict": 8} and sent[0]["keep_alive"] == -1
    build_backend(cfg("plain", 0.6)).complete("q", 8)  # unset: server defaults, no keep_alive field
    assert sent[1]["options"] == {"num_predict": 8} and "keep_alive" not in sent[1]


def test_disabled_tier_skipped_and_none_left_raises():
    p, _ = pool([cfg("off", 1.0, enabled=False), cfg("on", 1.0, 1)])
    assert p.generate("x", 0.1).tier == "on"
    with pytest.raises(AllTiersFailed):
        pool([cfg("off", 1.0, enabled=False)])[0].generate("x", 0.1)


def test_same_family_rule():
    assert can_verify(cfg("a", 1, family="qwen"), cfg("b", 1, family="qwen"))
    assert not can_verify(cfg("a", 1, family="gemma"), cfg("b", 1, family="qwen"))
    assert not can_verify(cfg("a", 1, family=""), cfg("b", 1, family=""))


def test_example_config_loads():
    from chimera_core.config import ROOT, load_config
    names = [t.name for t in load_config(ROOT / "chimera.example.toml").tiers]
    assert names == ["phone-3b", "mac-3b", "gpu-h200", "gpu-small", "gpu-large", "cloud-mid", "cloud-top", "cloud-deepseek",
                     "cloud-coder", "cloud-largest"]


def test_default_order_is_h200_if_warm_then_gpu_30b_then_763b():
    from chimera_core.config import ROOT, load_config
    order = [t.name for t in TierPool(load_config(ROOT / "chimera.example.toml").tiers).tiers]
    assert order == ["gpu-h200", "gpu-small", "cloud-deepseek"]


def test_router_uses_pool_behind_flag(tmp_path):
    from chimera_core.router import SpeculativeCascadeRouter
    p, _ = pool([cfg("gpu-small", 1.0)])
    r = SpeculativeCascadeRouter(local=None, pool=p)
    out = r.generate("hello")
    assert out.text == "gpu-small-answer" and out.telemetry.tier_used == "gpu"
    assert out.telemetry.tier_name == "gpu-small"  # the gateway's x-chimera-tier header uses this
    assert out.telemetry.per_tier["gpu_small"].output_tokens == 5


def test_per_tier_has_real_model_and_latency_for_each_tier_touched():
    a = TierCfg(name="phone-3b", device="phone", backend="llamacpp", url="http://x", family="qwen",
                model="Qwen2.5-3B-Instruct-q4_k_m", max_complexity=0.5)
    b = cfg("gpu-small", 1.0, 1)
    p, _ = pool([a, b], {"phone-3b": Fake("phone-3b", fail=True)})
    per = p.telemetry_per_tier(p.generate("x", 0.1))
    assert set(per) == {"phone_3b", "gpu_small"}
    assert per["phone_3b"].model == "Qwen2.5-3B-Instruct-q4_k_m" and per["phone_3b"].device == "Phone"


def test_url_env_expansion(monkeypatch):
    monkeypatch.setenv("MODAL_VLLM_URL", "https://x.modal.run")
    t = TierCfg(name="g", device="gpu", backend="openai", url="$MODAL_VLLM_URL")
    assert t.url == "https://x.modal.run"
