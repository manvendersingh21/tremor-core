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
    assert names == ["phone-3b", "mac-3b", "gpu-small", "gpu-large", "cloud-mid", "cloud-top", "cloud-largest"]


def test_router_uses_pool_behind_flag(tmp_path):
    from chimera_core.router import SpeculativeCascadeRouter
    p, _ = pool([cfg("gpu-small", 1.0)])
    r = SpeculativeCascadeRouter(local=None, pool=p)
    out = r.generate("hello")
    assert out.text == "gpu-small-answer" and out.telemetry.tier_used == "gpu"
    assert out.telemetry.per_tier["gpu_small"].output_tokens == 5


def test_per_tier_has_real_model_and_latency_for_each_tier_touched():
    a = TierCfg(name="phone-3b", device="phone", backend="llamacpp", url="http://x", family="qwen",
                model="Qwen2.5-3B-Instruct-q4_k_m", max_complexity=0.5)
    b = cfg("gpu-small", 1.0, 1)
    p, _ = pool([a, b], {"phone-3b": Fake("phone-3b", fail=True)})
    per = p.telemetry_per_tier(p.generate("x", 0.1))
    assert set(per) == {"phone_3b", "gpu_small"}
    assert per["phone_3b"].model == "Qwen2.5-3B-Instruct-q4_k_m" and per["phone_3b"].device == "Phone"
