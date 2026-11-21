"""skeleton/core/rules.py: the regex fast path answers only short, exact intents, from the knowledge base (offline)."""
import importlib.util
import pathlib

from skeleton.apps.helpdesk import helpdesk
from skeleton.core.rules import Rules

KB = helpdesk.KnowledgeBase()
RULES = Rules.for_faq(KB.data)


def test_small_talk_and_kb_intents_match():
    assert "Hello" in RULES.match("Hi!")
    assert "welcome" in RULES.match("Thanks a lot!")
    assert "8:00 to 20:00" in RULES.match("What are your hours?")
    assert "1-800-555-0142" in RULES.match("What is your phone number?")
    assert RULES.match("how do i reset my password") == next(e["a"] for e in KB.data["faq"] if "reset my password" in e["q"])


def test_anything_longer_or_different_falls_through():
    for q in ("hi, my order arrived broken and I want money back", "what are your hours for returns on gift cards",
              "How long does shipping take?", "", "x" * 200):
        assert RULES.match(q) is None


def test_rules_first_skips_the_models_and_counts():
    bot = helpdesk.make_assistant(rules=True)
    a = bot.ask("hello")
    assert a["tier"] == "rules" and a["tokens"] == 0 and a["dollars"] == 0 and not a["cache_hit"]
    b = bot.ask("How do I get a refund?")  # no rule: the normal path
    assert b["tier"] != "rules" and b["answer"]
    assert bot.stats()["rule_hits"] == 1 and bot.stats()["questions"] == 1


def test_bench_sets_are_fixed_sizes():
    p = pathlib.Path(__file__).resolve().parents[1] / "skeleton/bench/vs_pybot.py"
    spec = importlib.util.spec_from_file_location("vs_pybot", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    h, c = m.helpdesk_set(), m.coder_set()
    assert len(h) == 60 and len(c) == 40 and len({r["id"] for r in h}) == 60
    assert m.run_tests("def fib(n):\n    a, b = 0, 1\n    for _ in range(n):\n        a, b = b, a + b\n    return a", "fib")[0]
    assert not m.run_tests("def fib(n):\n    return 1", "fib")[0]
