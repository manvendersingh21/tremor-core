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


# Demo (no embedder): the word-overlap check is strict. These answers come from a policy or hours line, or the stub gives the
# wrong line ("How long does shipping take?" gets the shipping price). They are misses, never served. Live uses meaning.
DEMO_WORD_MISSES = {"How long does shipping take?", "What is your return policy?", "How long does a refund take?",
                    "Are you open on Sunday?", "Is there a cancellation fee?", "When does my order ship?"}


def test_demo_questions_still_pass_the_check():
    """Every seed question passes grounded + backed, except one where the demo stub itself answers wrongly: for "How
    long does shipping take?" it returns the shipping price. The old check served that answer; the new one rejects it."""
    bot = helpdesk.make_assistant(swarm=True)
    for q in json.loads(helpdesk.QUESTIONS.read_text())["seed"]:
        a = bot.ask(q)
        if q in DEMO_WORD_MISSES:
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
    a = bot.ask("How long is the password reset link valid?")
    assert bot.ladder == SWARM_LADDER == ["crusoe-small", "cloud-top", "cloud-deepseek"]
    assert a["verified"] is True and a["tried"] == ["crusoe-small", "cloud-top"] == [a["tried"][0], a["tier"]] and not a["cache_hit"]
    assert bot.ask("How long is the password reset link valid?")["cache_hit"]


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
    for q in ("How long is the password reset link valid?", "Why was my card charged twice?", "how do i reset my password"):
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


# ---- small talk with a tail -----------------------------------------------------------------------------------
@pytest.mark.parametrize("q", ["thanks, that helped!", "Thank you so much, that worked", "great, that worked", "ok thanks bye!",
                               "hello, thanks", "thanks for the quick answer", "much appreciated", "no more questions, thanks"])
def test_small_talk_with_a_tail_gets_the_small_talk_reply_never_the_fallback(q):
    a = helpdesk.make_assistant(swarm=True).ask(q)
    assert a["tier"] == "rules" and a["tokens"] == 0 and a["answer"] != helpdesk.FALLBACK


@pytest.mark.parametrize("q", ["hi, my order arrived broken", "thanks, where is my order?", "hello I need a refund"])
def test_small_talk_with_a_real_question_is_not_small_talk(q):
    from skeleton.core.rules import Rules
    assert Rules.for_faq(KB.data).match(q) is None


# ---- meaning (a fake embedder: synonym groups -> one dimension each; never the real model) ---------------------------
GROUPS = [{"talk", "human", "contact", "person", "speak"}, {"refund", "money", "back", "reimburse"},
          {"password", "login"}, {"order", "parcel", "package"}, {"cancel", "stop"}, {"subscription", "membership"}]


class FakeEmbedder:
    def embed(self, text):
        import re
        v = [0.0] * (len(GROUPS) + 64)
        for w in re.findall(r"[a-z]+", text.lower()):
            if w in {"how", "can", "i", "do", "a", "to", "my", "the", "you", "your", "is", "or", "does", "q"}:
                continue
            g = next((i for i, s in enumerate(GROUPS) if w in s), None)
            v[g if g is not None else len(GROUPS) + sum(map(ord, w)) % 64] += 1.0
        return v


def test_meaning_finds_the_entry_when_no_words_are_shared():
    kb = helpdesk.KnowledgeBase().attach(FakeEmbedder())
    q = "How can I speak to a human?"  # shares no content word with "How do I contact a person?"
    assert KB.lookup().match(q) is None  # word overlap alone: miss
    assert "chat or email" in kb.lookup().match(q)
    assert kb.lookup().match("Do you sell fresh flowers?") is None  # nothing close: still a miss


def test_meaning_check_accepts_the_right_entry_and_rejects_a_wrong_one():
    kb = helpdesk.KnowledgeBase().attach(FakeEmbedder())
    contact = next(e["a"] for e in KB.data["faq"] if e["q"] == "How do I contact a person?")
    q = "How can I speak to a human?"
    assert not KB.checked(q, contact) and kb.checked(q, contact)  # same words fail, meaning passes
    assert not kb.checked(q, REFUND) and not kb.checked(q, PASSWORD)  # an answer about another entry never passes


def test_two_close_entries_are_a_miss_not_a_guess():
    kb = helpdesk.KnowledgeBase().attach(FakeEmbedder())
    assert kb.lookup().match("How do I stop my order or my membership?") is None  # order and subscription fit equally


def test_a_broken_embedder_falls_back_to_word_overlap():
    class Broken:
        def embed(self, text):
            raise ImportError("no sentence-transformers")
    kb = helpdesk.KnowledgeBase().attach(Broken())
    assert kb.lookup().match("how do i reset my password") == PASSWORD  # words still work
    assert kb.checked("How do I reset my password?", PASSWORD) and not kb.checked("How can I speak to a human?", PASSWORD)


def test_store_lookup_never_serves_an_item_that_is_on_special_today():
    import datetime as dt
    tuesday = store.Catalog(today=dt.date(2026, 11, 24))  # Tuesday: salmon and avocados are on special
    assert "Salmon fillet" in " ".join(tuesday.data["specials"]["tuesday"])
    assert tuesday.lookup().match("How much is the salmon?") is None  # the regular price would be wrong today
    wednesday = store.Catalog(today=dt.date(2026, 11, 25))
    assert wednesday.lookup().match("How much is the salmon?") == "Salmon fillet: aisle 4, $7.49."


# ---- near-duplicate entries: the margin looks at the facts, not at the cosine ----------------------------------------
class BagEmbedder:
    """One dimension per word (hash), so entries about the same thing score almost the same."""

    def embed(self, text):
        import re
        v = [0.0] * 97
        for w in re.findall(r"[a-z]+", text.lower()):
            v[sum(map(ord, w)) % 97] += 1.0
        return v


def _sem(entries, members=None):
    from skeleton.core.kblookup import Semantic
    return Semantic(BagEmbedder(), [k for k, _ in entries], [t for _, t in entries], members)


def test_near_duplicates_that_agree_on_the_facts_are_not_ambiguous():
    s = _sem([("where is the rice", "Aisle 5: rice and grains."), ("where is the rice", "Basmati rice: aisle 5, $2.89.")])
    assert s.backed("where is the rice", "Basmati rice is in aisle 5, $2.89.")  # either line backs it
    assert s.backed("where is the rice", "Rice and grains are in aisle 5.")
    assert not s.backed("where is the rice", "Rice is in aisle 4.")  # a fact no entry states


def test_near_duplicates_with_different_prices_or_aisles_are_refused():
    s = _sem([("where is the milk", "Oat milk: aisle 3, $3.49."), ("where is the milk", "Almond milk: aisle 3, $3.29.")])
    assert not s.backed("where is the milk", "Oat milk: aisle 3, $3.49.")  # two prices: which milk?
    s = _sem([("where is the milk", "Oat milk: aisle 3, $3.49."), ("where is the milk", "Whole milk: aisle 8, $3.49.")])
    assert not s.backed("where is the milk", "Oat milk: aisle 3, $3.49.")  # two aisles
    s = _sem([("how do i cancel", "Cancel your order in Orders."), ("how do i cancel", "Cancel your plan in Account.")])
    assert not s.backed("how do i cancel", "Cancel your order in Orders.")  # no facts at all: cannot tell they agree


def test_a_combined_entry_backs_answers_from_its_parts_and_nothing_else():
    s = _sem([("hours chat", "Hours, chat: 8:00 to 20:00 Monday to Friday, closed Sunday."),
              ("hours phone", "Hours, phone: 9:00 to 17:00 Monday to Friday."),
              ("what are your hours open sunday", "Support hours. 8:00 to 20:00 Monday to Friday, closed Sunday. 9:00 to 17:00 Monday to Friday."),
              ("refund", "Refunds take 5 to 7 days.")], members={2: [0, 1]})
    assert s.backed("what are your hours open sunday", "Chat is closed on Sunday; phone is 9:00 to 17:00 Monday to Friday.")
    assert not s.backed("what are your hours open sunday", "Chat is open 8:00 to 22:00.")  # 22:00 is not in the hours
    assert not s.backed("what are your hours open sunday", "Refunds take 5 to 7 days.")  # an answer from another entry


def test_help_desk_and_store_have_hours_policy_and_diet_entries_built_from_the_data():
    kb = helpdesk.KnowledgeBase().attach(BagEmbedder())
    assert any(t.startswith("Support hours.") for t in kb.semantic().texts)
    assert any(t.startswith("Policies.") for t in kb.semantic().texts)
    c = store.Catalog().attach(BagEmbedder())
    texts = c.semantic().texts
    assert any(t.startswith("Opening hours.") for t in texts) and any(t.startswith("Vegan items:") for t in texts)


# ---- near-miss class: shares words and meaning with an entry, asks about another thing ---------------------------
class FakeJudge:
    """Says YES only when the question's key thing is in the entries (a stand-in for the live yes/no model)."""

    def __init__(self, thing_of):
        self.thing_of, self.calls = thing_of, []

    def _ok(self, question, entries):
        thing = self.thing_of(question)
        return thing is None or any(thing in e.lower() for e in entries)

    def covers(self, question, entries):
        self.calls.append(("covers", question))
        return self._ok(question, entries)

    def agrees(self, question, entries, answer):
        self.calls.append(("agrees", question))
        return self._ok(question, entries)


def _thing(q):
    for w in ("router", "flight", "pause", "password", "order", "subscription"):
        if w in q.lower():
            return w
    return None


def test_near_miss_is_refused_by_the_check_even_when_words_and_meaning_match():
    kb = helpdesk.KnowledgeBase().attach(BagEmbedder())
    kb.judge = FakeJudge(_thing)
    assert not kb.checked("How do I reset my router?", PASSWORD)  # the judge: router is not in the password entry
    assert kb.checked("How do I reset my password?", PASSWORD)


# ---- joined-entry class: an answer that combines facts from two separate entries must be refused -----------------
def test_joined_entry_claim_is_refused_even_when_the_judge_says_yes():
    """The code must refuse a joined-entry answer before the judge runs. A judge-YES on two separate entries is not
    enough: each entry must cover ALL the answer's facts on its own. The FakeJudge below always says YES."""
    class YesJudge:
        def agrees(self, q, entries, a): return True
        def covers(self, q, entries): return True
        bot = None  # no cost tracking

    s = _sem([
        ("express shipping speed cost",    "Express shipping: 2-3 days, $12.99."),
        ("canada shipping destination",    "We ship to US and Canada, standard 7-10 days."),
        ("standard shipping cost price",   "Standard shipping: $4.99."),
    ])
    # entry A: has price $12.99, entry B: has duration 7-10 days; neither has both
    joined_answer = "Express shipping to Canada costs $12.99 and takes 7-10 days."
    assert not s.backed("express shipping canada destination", joined_answer), (
        "joined-entry answer must be refused: no single entry states both $12.99 and 7-10 days")

    # an answer from one entry only is backed
    single_entry = "Express shipping takes 2-3 days and costs $12.99."
    assert s.backed("express shipping speed cost", single_entry), (
        "single-entry answer must be backed")

    # backed_loose also refuses a joined claim, even with a YesJudge
    # entries A and B are both candidates for the joined question; backed_loose uses candidates() not _cluster()
    from skeleton.core.kblookup import swarm_check
    lines = ["Express shipping: 2-3 days, $12.99.", "We ship to US and Canada, standard 7-10 days.", "Standard shipping: $4.99."]
    assert not swarm_check(lines, s, YesJudge(), "express shipping canada destination", joined_answer), (
        "swarm_check must refuse joined claim even when the judge says YES")
    assert swarm_check(lines, s, YesJudge(), "express shipping speed cost", single_entry), (
        "swarm_check must pass a single-entry answer")


def test_other_joined_pairs_are_refused():
    """Additional joined pairs: payment x refund, hours x day.
    Cases where entries disagree on facts are refused (at the cluster or single-entry gate); we check the result."""
    s = _sem([
        ("payment methods",         "We accept credit card and PayPal."),
        ("refund policy",           "Refunds are processed in 5 to 7 business days."),
        ("store hours monday",      "We are open Monday to Friday 9:00 to 18:00."),
        ("store hours saturday",    "We are open Saturday 10:00 to 16:00."),
        ("apple special",           "Apples are on special today: $0.99 per kg."),
        ("apple aisle",             "Apples: aisle 2."),
    ])
    # payment + refund: each has distinct numbers → not backed (entries disagree or answer not in cluster)
    assert not s.backed("Can I get a refund on a PayPal payment?",
                        "Yes, PayPal payments are refunded in 5 to 7 business days.")
    # hours + day: Saturday hours are in one entry, Monday in another; a combined answer is not backed
    assert not s.backed("What are your weekday and weekend hours?",
                        "Monday to Friday 9:00 to 18:00, Saturday 10:00 to 16:00.")
    # single-entry answers are still fine
    assert s.backed("What are your Monday hours?", "We are open Monday to Friday 9:00 to 18:00.")


def test_no_fact_serves_the_fallback_without_any_tier_call():
    log = []
    from skeleton.core import Assistant
    from skeleton.core.swarm import Swarm
    models = {t: (lambda p, t=t: (log.append(t), "x")[1]) for t in SWARM_LADDER}
    kb = helpdesk.KnowledgeBase().attach(BagEmbedder())
    kb.judge = FakeJudge(_thing)
    bot = Swarm(Assistant({"mode": "demo", "namespace": "nofact", "ladder": SWARM_LADDER}, knowledge=kb,
                          verify=kb.grounded, demo_models=models), check=kb.checked, fallback=helpdesk.FALLBACK,
                covered=kb.covered)
    a = bot.ask("How do I reset my router?")
    assert a["answer"] == helpdesk.FALLBACK and a["tier"] == "no_fact" and a["verified"] is False and log == []
    assert bot.stats()["by_tier"] == {"no_fact": 1}


def test_live_swarm_fails_loudly_without_an_embedder(monkeypatch):
    from skeleton.core import swarm

    class Bot:
        class cfg:
            mode = "live"
        router = None
    import chimera_core.cache.semantic_cache as sc

    class Boom:
        def __init__(self, *a, **k):
            raise ImportError("no sentence-transformers")
    monkeypatch.setattr(sc, "OnnxMiniLMEmbedder", Boom)
    with pytest.raises(RuntimeError, match="embedder"):
        swarm.need_embedder(Bot())
    Bot.cfg.mode = "demo"
    assert swarm.need_embedder(Bot()) is None  # demo: word overlap, no error


def test_demo_swarm_has_no_judge_and_calls_no_extra_model():
    bot = helpdesk.make_assistant(swarm=True)
    assert bot.check.__self__.judge is None


def test_a_yes_or_no_about_a_clock_time_is_never_backed():
    """The bot does not know the time: "Is the store open at 10 pm?" may get the hours, never a verdict."""
    from skeleton.core.kblookup import swarm_check, time_verdict
    assert time_verdict("Is the store open at 10 pm?", "No, it closes at 22:00.")
    assert time_verdict("Is the kitchen open now?", "Yes, until 20:00.")
    assert not time_verdict("Is the store open at 10 pm?", "The store is open 7:00 to 22:00 every day.")
    assert not time_verdict("Are you open on Sundays?", "No, phone support is closed on Sunday.")
    c = store.Catalog().attach(BagEmbedder())
    assert not swarm_check(c.lines(), c.semantic(), None, "Is the store open at 10 pm?", "No, it closes at 22:00.")
