"""skeleton/core: Assistant over chimera-core with stub tiers and the in-memory cache (offline)."""
import pytest

from skeleton.core import Assistant, Config


def stubs(log, small="small answer", big="big answer"):
    def tier(name, text):
        def fn(prompt):
            log.append((name, prompt))
            return text(prompt) if callable(text) else text
        return fn
    return {"gpu-small": tier("gpu-small", small), "cloud-deepseek": tier("cloud-deepseek", big)}


def test_cache_answers_repeat_without_a_model_call():
    log = []
    bot = Assistant({"namespace": "t1"}, demo_models=stubs(log))
    first = bot.ask("What is the capital of France?")
    again = bot.ask("What is the capital of France?")
    assert first["tier"] == "gpu-small" and not first["cache_hit"] and first["tokens"] > 0
    assert again["cache_hit"] and again["tier"] == "exact_cache" and again["tokens"] == 0 and again["tried"] == []
    assert again["dollars_saved"] > 0 and len(log) == 1
    s = bot.stats()
    assert (s["questions"], s["cache_hits"], s["exact"], s["hit_rate"]) == (2, 1, 1, 0.5)


def test_failed_verify_climbs_one_tier_and_is_never_cached():
    log = []
    bot = Assistant({"namespace": "t2"}, demo_models=stubs(log, small="wrong", big="right"),
                    verify=lambda a: a == "right")
    a = bot.ask("fix the bug")
    assert a["tier"] == "cloud-deepseek" and a["verified"] is True and a["tried"] == ["gpu-small", "cloud-deepseek"]
    assert [s["verified"] for s in a["steps"]] == [False, True] and a["dollars"] > 0 and a["dollars_saved"] == 0
    b = bot.ask("fix the bug")
    assert b["cache_hit"] and b["answer"] == "right"  # the failing 30B answer was not stored
    assert bot.stats()["climbs"] == 1


def test_top_tier_failing_verify_is_served_marked_unverified():
    bot = Assistant({"namespace": "t3"}, demo_models=stubs([], small="no", big="no"), verify=lambda a: False)
    a = bot.ask("impossible")
    assert a["verified"] is False and a["tier"] == "cloud-deepseek"
    assert not bot.ask("impossible")["cache_hit"]


def test_empty_answer_climbs_in_the_pool():
    bot = Assistant({"namespace": "t4"}, demo_models=stubs([], small=""))
    a = bot.ask("hard question")
    assert a["tier"] == "cloud-deepseek" and a["tried"] == ["gpu-small", "cloud-deepseek"]


def test_cached_answer_that_fails_verify_goes_to_the_models():
    good = {"v": True}
    log = []
    bot = Assistant({"namespace": "t5"}, demo_models=stubs(log), verify=lambda a: good["v"])
    bot.ask("q")
    good["v"] = False
    a = bot.ask("q")
    assert a["steps"][0]["cache"] == "shared" and a["steps"][0]["verified"] is False
    assert [s["tier"] for s in a["steps"]] == ["exact_cache", "gpu-small", "cloud-deepseek"]


def test_knowledge_reaches_models_but_only_its_version_keys_the_cache():
    log = []

    class Facts:
        version = "v1"

        def __call__(self, q):
            return "Oat milk: aisle 3."

    facts = Facts()
    bot = Assistant({"namespace": "t6", "instructions": "Be short."}, knowledge=facts, demo_models=stubs(log))
    bot.ask("Where do I find oat milk?")
    assert "Be short." in log[0][1] and "Oat milk: aisle 3." in log[0][1] and log[0][1].endswith("Question: Where do I find oat milk?")
    assert bot.ask("where is the oat milk")["cache_hit"]  # same content words: cosine 1.0 in demo
    facts.version = "v2"  # new facts: old answers are not served
    assert not bot.ask("Where do I find oat milk?")["cache_hit"]


def test_context_is_part_of_the_cache_key():
    bot = Assistant({"namespace": "t7"}, demo_models=stubs([]))
    bot.ask("fix it", context="FILE: a.py\nx = 1\nEND FILE")
    assert bot.ask("fix it", context="FILE: a.py\nx = 1\nEND FILE")["cache_hit"]
    assert not bot.ask("fix it", context="FILE: a.py\nx = 2\nEND FILE")["cache_hit"]


def test_every_call_emits_standard_telemetry():
    bot = Assistant({"namespace": "t8"}, demo_models=stubs([]))
    bot.ask("hello")
    bot.ask("hello")
    ev = bot.router.tracker.events
    assert [e.tier_used for e in ev] == ["gpu", "exact_cache"]
    for e in ev:
        for k in ("tier_used", "tokens_saved", "acceptance_rate_alpha", "latency_ms", "dollars_saved"):
            assert hasattr(e, k)


def test_config_from_toml_and_bad_ladder(tmp_path):
    p = tmp_path / "app.toml"
    p.write_text('namespace = "x"\nladder = ["gpu-small", "cloud-deepseek"]\nmax_tokens = 64\n')
    assert Config.load(p).max_tokens == 64 and Assistant(p).ladder == ["gpu-small", "cloud-deepseek"]
    with pytest.raises(KeyError):
        Assistant({"ladder": ["no-such-tier"]})
