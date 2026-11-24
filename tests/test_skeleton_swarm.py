"""skeleton/core/swarm.py, kblookup.py and the stronger help-desk / store check (demo mode, offline, no keys)."""
import json

import pytest

from skeleton.apps.helpdesk import helpdesk
from skeleton.apps.store import store
from skeleton.core.kblookup import KBLookup
from skeleton.core.swarm import SWARM_LADDER

KB = helpdesk.KnowledgeBase()
REFUND = next(e["a"] for e in KB.data["faq"] if e["q"] == "How do I get a refund?")
SUBSCRIPTION = next(e["a"] for e in KB.data["faq"] if e["q"] == "How do I cancel my subscription?")
PASSWORD = next(e["a"] for e in KB.data["faq"] if e["q"] == "How do I reset my password?")


def _rows(bot):
    bot.router.shared.flush()
    return bot.router.shared._store_ready().rows


# ---- 1. the check -------------------------------------------------------------------------------------------
def test_wrong_answer_without_numbers_now_fails_the_check():
    wrong = "Open Orders and click Track. The tracking number appears once the order ships."  # about another entry
    assert KB.grounded(wrong)  # the old check lets it through: no number
    assert not KB.checked("How do I reset my password?", wrong)
    assert KB.checked("How do I reset my password?", PASSWORD)
    assert not KB.checked("How do I reset my password?", "I don't know.")
    assert not KB.checked("Do you sell fresh flowers?", "Yes, we sell flowers.")  # nothing in the KB matches


def test_store_check_needs_the_right_item():
    c = store.Catalog()
    assert c.checked("Where do I find oat milk?", "Oat milk: aisle 3, $3.49.")
    assert not c.checked("Where do I find oat milk?", "Tofu: aisle 4, $2.29.")


def test_demo_questions_still_pass_the_check():
    """Every seed question passes grounded + backed, except one where the demo stub itself answers wrongly: for "How
    long does shipping take?" it returns the shipping price. The old check served that answer; the new one rejects it."""
    bot = helpdesk.make_assistant(swarm=True)
    for q in json.loads(helpdesk.QUESTIONS.read_text())["seed"]:
        a = bot.ask(q)
        if q == "How long does shipping take?":
            assert a["verified"] is False and a["answer"] == helpdesk.FALLBACK
        else:
            assert a["verified"] is not False and a["answer"] != helpdesk.FALLBACK, q


# ---- 2. KB lookup -------------------------------------------------------------------------------------------
def test_lookup_answers_strong_matches_only():
    lk = KB.lookup()
    assert lk.match("how do i reset my password") == PASSWORD
    assert lk.match("Can I get a refund?") == REFUND
    assert lk.match("How do I cancel my subscription?") != lk.match("How do I cancel my order?")  # one word apart
    for q in ("Do you sell fresh flowers?", "Why was my card charged twice?", "How can I talk to a human?", "", "?"):
        assert lk.match(q) is None  # outside the KB, a synonym only, or empty: fall through


def test_lookup_refuses_a_tie():
    lk = KBLookup([("reset password", "A"), ("reset password email", "B")], q_cov=0.5, k_cov=0.5, margin=0.5)
    assert lk.match("reset password") is None


def test_store_lookup_needs_exactly_one_item():
    lk = store.Catalog().lookup()
    assert lk.match("Where do I find oat milk?") == "Oat milk: aisle 3, $3.49."
    assert lk.match("where is the milk") is None  # three milks
    assert lk.match("Is oat milk on special today?") is None  # more than an item name


# ---- 3-5. the wrapper ---------------------------------------------------------------------------------------
def test_free_answer_costs_nothing_logs_one_row_and_is_not_cached():
    bot = helpdesk.make_assistant(swarm=True)
    n0 = len(bot.router.tracker.events)
    a = bot.ask("How do I cancel my subscription?")
    assert a["tier"] == "kb_lookup" and a["answer"] == SUBSCRIPTION and a["tokens"] == 0 and a["dollars"] == 0
    assert a["tokens_saved"] > 0 and a["dollars_saved"] > 0 and a["tried"] == []
    rows = bot.router.tracker.events[n0:]
    assert len(rows) == 1
    t = rows[0]
    assert (t.tier_name, t.acceptance_rate_alpha, t.latency_ms >= 0, t.tokens_saved) == ("kb_lookup", None, True, a["tokens_saved"])
    assert t.dollars_saved == pytest.approx(a["dollars_saved"], abs=1e-6)
    assert _rows(bot) == []  # nothing written to the cache
    s = bot.stats()
    assert s["questions"] == 1 and s["free_answers"] == 1 and s["by_tier"] == {"kb_lookup": 1}
    assert bot.ask("hello")["tier"] == "rules"


def test_model_path_serves_the_cheapest_passing_tier_and_caches_it():
    bot = helpdesk.make_assistant(swarm=True)
    a = bot.ask("Is there a cancellation fee?")
    assert bot.ladder == SWARM_LADDER == ["crusoe-small", "cloud-top", "cloud-deepseek"]
    assert a["verified"] is True and a["tried"] == ["crusoe-small", "cloud-top"] == [a["tried"][0], a["tier"]] and not a["cache_hit"]
    assert bot.ask("Is there a cancellation fee?")["cache_hit"]


def test_nothing_passes_serves_the_fallback_and_caches_nothing():
    bot = helpdesk.make_assistant(swarm=True)
    q = "Why was my card charged twice?"
    a = bot.ask(q)
    assert a["answer"] == helpdesk.FALLBACK and a["verified"] is False and a["tried"] == SWARM_LADDER
    assert _rows(bot) == [] and not bot.ask(q)["cache_hit"]


def test_context_skips_the_free_modules():
    bot = helpdesk.make_assistant(swarm=True)
    assert bot.ask("how do i reset my password", context="note")["tier"] != "kb_lookup"


# ---- owner rule: no model call before the cache lookup finishes --------------------------------------------------
def test_no_model_call_before_the_cache_lookup_finishes():
    log = []
    from skeleton.core import Assistant
    from skeleton.core.swarm import Swarm
    models = {t: (lambda p, fn=fn, t=t: (log.append("model:" + t), fn(p))[1]) for t, fn in helpdesk.SWARM_DEMO_MODELS.items()}
    inner = Assistant({"mode": "demo", "namespace": "own", "ladder": SWARM_LADDER, "max_tokens": 250}, knowledge=KB,
                      verify=KB.grounded, demo_models=models)
    real = inner.router.shared.lookup

    def lookup(prompt, namespace=""):
        log.append("lookup_start")
        r = real(prompt, namespace)
        log.append("lookup_end")
        return r
    inner.router.shared.lookup = lookup
    swarm = Swarm(inner, free=[("kb_lookup", KB.lookup().match)], check=KB.checked, fallback=helpdesk.FALLBACK)
    for q in ("Is there a cancellation fee?", "Why was my card charged twice?", "how do i reset my password"):
        log.clear()
        swarm.ask(q)
        firsts = [i for i, x in enumerate(log) if x.startswith("model:")]
        if firsts:
            assert log.index("lookup_end") < firsts[0], (q, log)
    # a $0 module answered the third question: it called no model at all
    assert not [x for x in log if x.startswith("model:")]


def test_swarm_wires_into_store_and_coder():
    s = store.make_assistant(swarm=True)
    assert s.ask("Where do I find oat milk?")["tier"] == "kb_lookup" and s.ladder == SWARM_LADDER
    from skeleton.apps.coder import demo
    from skeleton.apps.coder.coder import make_swarm
    bot = make_swarm(demo_models={"crusoe-small": demo.DEMO_MODELS["gpu-small"], "cloud-top": demo.DEMO_MODELS["gpu-small"],
                                  "cloud-deepseek": demo.DEMO_MODELS["cloud-deepseek"]})
    assert bot.ladder == SWARM_LADDER and bot.fallback == ""
