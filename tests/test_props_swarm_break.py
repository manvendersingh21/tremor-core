"""Independent breaker properties for the swarm serving guard (PR #11: skeleton/core/swarm.py, kblookup.py, the apps).

Offline: demo mode, stub tiers, fake embedder and judge. Every model tier returns the ADVERSARIAL answer the property
builds, so a property fails when the swarm serves it. Inputs come from the real skeleton/apps/helpdesk/kb.json and
skeleton/apps/store/foods.json.
Modes: "a" = no embedder, no judge (the CI/demo path); "b" = a bag-of-words embedder plus a judge that always says YES.
A failing property is a break of the swarm, not of this file. Each break is kept and marked xfail(strict=True) with its
shrunk counterexample (tests/_props.py convention); @example pins it so the failure is deterministic.
See the live failures with: pytest --runxfail tests/test_props_swarm_break.py
Written on the k1 box (kiro-cli agent and the main session) and the k2 box (kiro-cli code reader); no keys, no network.
"""
import datetime as dt
import json
import re
import tomllib

import pytest
from hypothesis import example, given, settings, strategies as st

from skeleton.apps.helpdesk import helpdesk
from skeleton.apps.store import store
from skeleton.core import Assistant
from skeleton.core.demo import words
from skeleton.core.kblookup import Semantic, swarm_check
from skeleton.core.rules import Rules
from skeleton.core.swarm import SWARM_LADDER, Judge, Swarm

from tests._props import PBT

PBT = settings(PBT, database=None)  # the shared ~200-example settings; no example database written to disk


# ---- fakes ----------------------------------------------------------------------------------------------------------
class BagEmbedder:
    """Bag of content words (skeleton.core.demo.words), one dimension per distinct word, so no hash collisions.
    Knows no synonyms. Vectors grow with the vocabulary; Semantic's zip() then still gives the exact cosine."""
    vocab: dict[str, int] = {}

    def embed(self, text):
        ids = [self.vocab.setdefault(w, len(self.vocab)) for w in words(text)]
        v = [0.0] * len(self.vocab)
        for i in ids:
            v[i] += 1.0
        return v


class YesJudge:
    """The adversarial judge: every covers/agrees is YES. log: records each call (it is a model call when live)."""
    bot = None  # no judge Assistant: no judge cost to count

    def __init__(self, log=None):
        self.log = log

    def covers(self, question, entries):
        if self.log is not None:
            self.log.append("judge:covers")
        return True

    def agrees(self, question, entries, answer):
        if self.log is not None:
            self.log.append("judge:agrees")
        return True


MODES = {"a": (False, False), "b": (True, True)}  # (bag-of-words embedder, YES judge)
ALL_MODES = {**MODES, "b_no_judge": (True, False)}  # invariant 4 only: same embedder, no judge
HD_CFG = tomllib.loads(helpdesk.CONFIG.read_text())
ST_CFG = tomllib.loads(store.CONFIG.read_text())


def _tiers(answer, log=None):
    def tier(name):
        def fn(prompt):
            if log is not None:
                log.append("model:" + name)
            return answer
        return fn
    return {t: tier(t) for t in SWARM_LADDER}


def _logged(name, fn, log):
    if log is None:
        return fn

    def run(q):
        log.append("free:" + name)
        return fn(q)
    return run


def _log_lookup(bot, log):
    real = bot.router.shared.lookup

    def lookup(prompt, namespace=""):
        log.append("lookup_start")
        r = real(prompt, namespace)
        log.append("lookup_end")
        return r
    bot.router.shared.lookup = lookup


def helpdesk_swarm(mode, answer, log=None):
    """What helpdesk.make_assistant(swarm=True, embedder=E, judge=J) builds, with every tier returning `answer`."""
    emb, yes = ALL_MODES[mode]
    kb = helpdesk.KnowledgeBase()
    bot = Assistant({**HD_CFG, "mode": "demo", "ladder": SWARM_LADDER}, knowledge=kb, verify=kb.grounded,
                    demo_models=_tiers(answer, log))
    kb.attach(BagEmbedder() if emb else None)
    kb.judge = YesJudge(log) if yes else None
    if log is not None:
        _log_lookup(bot, log)
    return Swarm(bot, free=[("rules", _logged("rules", Rules.for_faq(kb.data).match, log)),
                            ("kb_lookup", _logged("kb_lookup", kb.lookup().match, log))],
                 check=kb.checked, fallback=helpdesk.FALLBACK, covered=kb.covered)


def store_swarm(mode, answer, day, log=None):
    """What store.make_assistant(swarm=True, catalog=Catalog(today=day), ...) builds, every tier returning `answer`."""
    emb, yes = ALL_MODES[mode]
    c = store.Catalog(today=day)
    bot = Assistant({**ST_CFG, "mode": "demo", "ladder": SWARM_LADDER}, knowledge=c, verify=c.grounded,
                    demo_models=_tiers(answer, log))
    c.attach(BagEmbedder() if emb else None)
    c.judge = YesJudge(log) if yes else None
    if log is not None:
        _log_lookup(bot, log)
    return Swarm(bot, free=[("kb_lookup", _logged("kb_lookup", c.lookup().match, log))], check=c.checked,
                 fallback=store.FALLBACK, covered=c.covered)


def _served(a):
    return f"tier={a['tier']} answer={a['answer']!r}"


# ---- data from the real knowledge base and catalog ------------------------------------------------------------------
KB = helpdesk.KnowledgeBase()
FAQ = KB.data["faq"]
LINES = KB.lines()
FOODS = json.loads(store.FOODS.read_text())
ITEMS = FOODS["items"]
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY = {d: dt.date(2026, 11, 23) + dt.timedelta(days=i) for i, d in enumerate(WEEKDAYS)}  # 2026-11-23 is a Monday
assert all(DAY[d].strftime("%A").lower() == d for d in WEEKDAYS)

# Invariant 1: "How do I <verb> my|a <object>?" FAQ entries, asked about a thing no KB line mentions.
HOWTO = [(m.group(1), e) for e in FAQ if (m := re.match(r"How do I (\w+) (?:my|a|an) (.+)\?$", e["q"]))]
KB_WORDS = set(words(KB.text))
FOREIGN = [t for t in ["router", "modem", "printer", "flight", "laptop", "car insurance", "hotel booking", "wifi"]
           if not set(words(t)) & KB_WORDS]
UNCOVERED_ASK = ["How do I {verb} my {thing}?", "How can I {verb} my {thing}?", "I need to {verb} my {thing}.",
                 "Please help me {verb} my {thing}."]
assert len(HOWTO) >= 8 and len(FOREIGN) >= 6

# Invariant 2: things the KB names, and pairs of them that no single KB line states together.
THINGS = [t for t in ["express shipping", "Canada", "phone support", "Saturday", "gift card", "PayPal", "discount code",
                      "warranty", "subscription", "password", "tracking number", "replacement", "spam folder",
                      "cancellation fee", "Sunday", "price drops"]
          if any(t.lower() in x.lower() for x in LINES)]


def _together(x, y):
    return any(x.lower() in line.lower() and y.lower() in line.lower() for line in LINES)


JOINED = [(x, y) for x in THINGS for y in THINGS if x != y and not _together(x, y)]
assert ("express shipping", "Canada") == JOINED[0] and ("phone support", "Saturday") in JOINED


def _sentence(x):
    """The KB sentence that states thing x (its numbers are the KB's), e.g. 'Express shipping is $14.99.'"""
    for line in LINES:
        if x.lower() in line.lower():
            body = line.split(" A: ", 1)[-1]
            sents = re.split(r"(?<=[.!?])\s+", body)
            return next((s for s in sents if x.lower() in s.lower()), sents[0])
    raise KeyError(x)


ASK_TWO = ["Is {x} available to {y}?", "Is {x} available on {y}?", "Can I use {x} for {y}?", "Does {x} cover {y}?"]
ASK_ONE = ["Is {x} available?", "Tell me about {x}.", "How does {x} work?", "What about {x}?"]
JOIN = ["Yes, {x} is available for {y}. {s}", "{s} The same goes for {y}.", "Yes. {s} That includes {y}."]

# Invariant 3: today's specials mapped to their catalog items; diet tags each item does NOT carry.
SALES = []
for day in WEEKDAYS:
    for s in FOODS["specials"][day]:
        short = s.split(" at ")[0]
        item = next(i for i in ITEMS if i["name"].lower().startswith(short.lower()))
        SALES.append((day, item, short))
assert len(SALES) == 14
NAMES = ["name", "before_comma", "special_word", "no_comma"]  # how a shopper writes the item


def _name(item, short, how):
    return {"name": item["name"], "before_comma": item["name"].split(",")[0], "special_word": short,
            "no_comma": item["name"].replace(",", "")}[how]


SALE_ASK = ["How much is {n}?", "How much are {n}?", "Where is the {n}?", "Which aisle has {n}?",
            "What aisle is the {n} in? How much?", "Price of {n}?"]
TAGS = sorted({t for i in ITEMS for t in i.get("tags", [])})
NOT_TAGGED = [(i, t) for t in TAGS for i in ITEMS if t not in i.get("tags", [])]
DIET_ASK = ["Is the {n} {tag}?", "Is {n} {tag}?", "Where is the {n}?", "How much is {n}?", "Which aisle has {n}?",
            "Do you have {tag} {n}?"]
DIET_CLAIM = ["{name}: aisle {aisle}, ${price} ({tag}).", "Yes, {name} is {tag}: aisle {aisle}, ${price}."]


def _line(item):
    return f"{item['name']}: aisle {item['aisle']}, ${item['price']}."


# ---- 1. a thing the KB does not cover is never answered from a nearby entry ---------------------------------------
@pytest.mark.xfail(strict=True, reason="BREAK: a and b: 'How do I reset my router?' -> the password-reset steps (crusoe-small)")
@pytest.mark.parametrize("mode", MODES)
@PBT
@given(entry=st.sampled_from(HOWTO), thing=st.sampled_from(FOREIGN), ask=st.sampled_from(UNCOVERED_ASK))
@example(entry=HOWTO[0], thing="router", ask=UNCOVERED_ASK[0])
def test_inv1_uncovered_thing_is_never_answered_from_a_nearby_entry(mode, entry, thing, ask):
    verb, e = entry
    q = ask.format(verb=verb, thing=thing)
    a = helpdesk_swarm(mode, e["a"]).ask(q)  # every tier answers from the nearby entry (seen live)
    assert a["answer"] == helpdesk.FALLBACK, f"{q!r} (no KB line names {thing!r}) -> {_served(a)}"


# ---- 2. no answer joins facts from two separate entries -------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason="BREAK: a and b: 'Is gift card available to express shipping?' -> 'Yes, gift card is available for express shipping. Visa, Mastercard, American Express, PayPal and gift cards.' (21 of 2,808 inputs)")
@pytest.mark.parametrize("mode", MODES)
@PBT
@given(pair=st.sampled_from(JOINED), ask=st.sampled_from(ASK_TWO), join=st.sampled_from(JOIN))
@example(pair=("gift card", "express shipping"), ask=ASK_TWO[0], join=JOIN[0])
def test_inv2a_question_naming_two_things_never_gets_a_joined_answer(mode, pair, ask, join):
    x, y = pair
    q, ans = ask.format(x=x, y=y), join.format(x=x, y=y, s=_sentence(x))
    a = helpdesk_swarm(mode, ans).ask(q)
    assert a["answer"] != ans, f"{q!r}: no KB line states {x!r} with {y!r} -> {_served(a)}"


@pytest.mark.xfail(strict=True, reason="BREAK (94f8b61): a: 'Is price drops available?' -> 'Yes, price drops is available for Sunday. We do refund the difference ...'; b: 'Is Canada available?' -> 'Yes, Canada is available for Sunday. We ship to the US and Canada only.'")
@pytest.mark.parametrize("mode", MODES)
@PBT
@given(pair=st.sampled_from(JOINED), ask=st.sampled_from(ASK_ONE), join=st.sampled_from(JOIN))
@example(pair=("warranty", "Canada"), ask=ASK_ONE[0], join=JOIN[0])
@example(pair=("price drops", "Sunday"), ask=ASK_ONE[0], join=JOIN[0])
@example(pair=("Canada", "Sunday"), ask=ASK_ONE[0], join=JOIN[0])
def test_inv2b_question_naming_one_thing_never_gets_a_joined_answer(mode, pair, ask, join):
    x, y = pair
    q, ans = ask.format(x=x), join.format(x=x, y=y, s=_sentence(x))
    a = helpdesk_swarm(mode, ans).ask(q)
    assert a["answer"] != ans, f"{q!r}: the answer joins {x!r} with {y!r}, no KB line does -> {_served(a)}"


# ---- 3. store: no sale item at its full price, no diet claim the item's own entry lacks ---------------------------
@pytest.mark.xfail(strict=True, reason="BREAK: a and b: thursday 'How much is Bananas, per kg?' -> kb_lookup 'Bananas, per kg: aisle 1, $1.29.' (special 0.99)")
@pytest.mark.parametrize("mode", MODES)
@PBT
@given(sale=st.sampled_from(SALES), how=st.sampled_from(NAMES), ask=st.sampled_from(SALE_ASK))
@example(sale=SALES[7], how="name", ask=SALE_ASK[0])
def test_inv3a_sale_item_is_never_served_at_its_full_price(mode, sale, how, ask):
    day, item, short = sale
    q = ask.format(n=_name(item, short, how))
    a = store_swarm(mode, _line(item), DAY[day]).ask(q)  # every tier quotes the catalog (full) price
    assert f"${item['price']}" not in a["answer"], (
        f"{day}: {q!r}; today's special is {[s for s in FOODS['specials'][day] if s.startswith(short)][0]!r} "
        f"-> {_served(a)}")


@pytest.mark.xfail(strict=True, reason="BREAK (94f8b61): a: tuesday 'Which aisle has salmon?' -> 'Salmon fillet: aisle 4, $7.49.' (special 5.99); b: tuesday 'How much is salmon?' -> the same line")
@pytest.mark.parametrize("mode", MODES)
@PBT
@given(sale=st.sampled_from(SALES), word=st.integers(0, 3), ask=st.sampled_from(SALE_ASK))
@example(sale=SALES[2], word=0, ask="Which aisle has {n}?")
@example(sale=SALES[2], word=0, ask="How much is {n}?")
def test_inv3a2_sale_item_asked_by_one_word_of_its_name_is_never_served_at_its_full_price(mode, sale, word, ask):
    """Shoppers say "salmon", not "Salmon fillet": one word of the item's name (before any comma)."""
    day, item, short = sale
    ws = item["name"].split(",")[0].lower().split()
    q = ask.format(n=ws[word % len(ws)])
    a = store_swarm(mode, _line(item), DAY[day]).ask(q)
    assert f"${item['price']}" not in a["answer"], (
        f"{day}: {q!r}; today's special is {[s for s in FOODS['specials'][day] if s.startswith(short)][0]!r} "
        f"-> {_served(a)}")


@pytest.mark.xfail(strict=True, reason="BREAK: a: monday 'Is the Chicken breast, per kg vegan?' -> '... $9.99 (vegan).'; b: monday 'Is the Whole milk dairy-free?' -> 'Whole milk: aisle 3, $2.19 (dairy-free).'")
@pytest.mark.parametrize("mode", MODES)
@PBT
@given(it=st.sampled_from(NOT_TAGGED), day=st.sampled_from(WEEKDAYS), how=st.sampled_from(["name", "before_comma"]),
       ask=st.sampled_from(DIET_ASK), claim=st.sampled_from(DIET_CLAIM))
@example(it=next(x for x in NOT_TAGGED if x[0]["name"] == "Free-range eggs, 12" and x[1] == "vegan"), day="monday",
         how="name", ask=DIET_ASK[0], claim=DIET_CLAIM[0])
@example(it=next(x for x in NOT_TAGGED if x[0]["name"] == "Whole milk" and x[1] == "dairy-free"), day="monday",
         how="name", ask=DIET_ASK[0], claim=DIET_CLAIM[0])
def test_inv3b_diet_claim_not_in_the_items_entry_is_never_served(mode, it, day, how, ask, claim):
    item, tag = it
    q = ask.format(n=_name(item, "", how), tag=tag)
    ans = claim.format(name=item["name"], aisle=item["aisle"], price=item["price"], tag=tag)
    a = store_swarm(mode, ans, DAY[day]).ask(q)
    assert tag not in a["answer"].lower(), (
        f"{day}: {q!r}; {item['name']!r} is tagged {item.get('tags', [])} -> {_served(a)}")


# ---- 4. a judge YES never overrides the one-entry rule (never turns a structural NO into a served answer) -----------
@pytest.mark.xfail(strict=True, reason="BREAK (94f8b61): 'Is subscription available?' + 'Yes, subscription is available for gift card. Open Account, then Subscriptions, and click Cancel subscription.': no judge -> fallback, YES judge -> served (backed_loose)")
@PBT
@given(pair=st.sampled_from(JOINED), two=st.booleans(), ask=st.integers(0, 3), join=st.sampled_from(JOIN))
@example(pair=("subscription", "gift card"), two=False, ask=0, join=JOIN[0])
def test_inv4_judge_yes_never_turns_a_refused_joined_answer_into_a_served_one(pair, two, ask, join):
    """Same bag-of-words embedder both times; the only difference is the judge (None vs always YES)."""
    x, y = pair
    q = (ASK_TWO if two else ASK_ONE)[ask].format(x=x, y=y)
    ans = join.format(x=x, y=y, s=_sentence(x))
    no_judge = helpdesk_swarm("b_no_judge", ans).ask(q)
    yes = helpdesk_swarm("b", ans).ask(q)
    if no_judge["answer"] != ans:
        assert yes["answer"] != ans, (
            f"{q!r} / joined answer {ans!r}: without a judge -> {_served(no_judge)}; with a YES judge -> {_served(yes)}")


# ---- 5. no model tier (or live judge) is called before rules, KB lookup and the cache had their chance -------------
HD_ASK = ([e["q"] for e in FAQ] + json.loads(helpdesk.QUESTIONS.read_text())["seed"]
          + [UNCOVERED_ASK[0].format(verb=v, thing=FOREIGN[0]) for v, _ in HOWTO]
          + [ASK_TWO[0].format(x=x, y=y) for x, y in JOINED[:20]] + ["hi", "thanks, that helped!", "What are your hours?"])
ST_ASK = ([f"Where is the {i['name']}?" for i in ITEMS] + json.loads(store.QUESTIONS.read_text())["seed"]
          + [f"Is the {i['name']} {t}?" for i, t in NOT_TAGGED[:20]])


@pytest.mark.parametrize("mode", MODES)
@PBT
@given(app=st.sampled_from(["helpdesk", "store"]), qi=st.integers(0, 10**6), ai=st.integers(0, len(FAQ) - 1),
       day=st.sampled_from(WEEKDAYS), twice=st.booleans())
def test_inv5_no_model_call_before_rules_kb_lookup_and_cache(mode, app, qi, ai, day, twice):
    log: list[str] = []
    if app == "helpdesk":
        q, bot, need = HD_ASK[qi % len(HD_ASK)], helpdesk_swarm(mode, FAQ[ai]["a"], log), ("free:rules", "free:kb_lookup")
    else:
        item = ITEMS[ai % len(ITEMS)]
        q, bot, need = ST_ASK[qi % len(ST_ASK)], store_swarm(mode, _line(item), DAY[day], log), ("free:kb_lookup",)
    for _ in range(2 if twice else 1):  # the second ask may be a cache hit
        log.clear()
        a = bot.ask(q)
        calls = [i for i, x in enumerate(log) if x.startswith(("model:", "judge:"))]
        if a["tier"] in ("rules", "kb_lookup"):
            assert not calls, (q, log)
        if calls:
            before = log[:calls[0]]
            for step in need + ("lookup_end",):
                assert step in before, (q, step, log)


# ---- k1 main session: hand-written joined claims, and the judge widening the check for a near miss -----------------
CURATED = [
    (["Is express shipping available to Canada?", "Can I get express delivery to Canada?", "How fast is express shipping?"],
     "Yes, express shipping to Canada takes 1 to 2 business days and costs $14.99."),
    (["Is phone support open on Saturday?", "Can I call you on Saturday?", "What are your phone hours?"],
     "Yes, phone support is open 10:00 to 16:00 on Saturday."),
    (["Can I get a refund for a gift card?", "Are gift cards refundable?"],
     "Yes, gift cards can be returned within 30 days of delivery and refunded to the original payment method."),
    (["Does my subscription come with a warranty?", "Do subscriptions have a warranty?"],
     "Yes, every subscription has a 2-year warranty against defects."),
    (["Is shipping to Canada free?", "How much is shipping to Canada?"],
     "Shipping to Canada is free on orders over $50 and $5.99 otherwise."),
    (["Is return shipping free from Canada?", "Can I return an item from Canada?"],
     "Yes, returns from Canada are free with the prepaid label within 30 days of delivery."),
]
CURATED_QA = [(q, a) for qs, a in CURATED for q in qs]


@pytest.mark.parametrize("mode", ["a", pytest.param("b", marks=pytest.mark.xfail(strict=True, reason=(
    "BREAK: b: 'What are your phone hours?' -> 'Yes, phone support is open 10:00 to 16:00 on Saturday.' (the chat "
    "hours joined to phone support; the all-hours entry holds every number) via crusoe-small")))])
@PBT
@given(qa=st.sampled_from(CURATED_QA))
@example(qa=("What are your phone hours?", "Yes, phone support is open 10:00 to 16:00 on Saturday."))
def test_inv2c_curated_joined_claims_are_never_served(mode, qa):
    q, fused = qa
    a = helpdesk_swarm(mode, fused).ask(q)
    assert a["answer"] != fused, f"{q!r}: joined claim served -> {_served(a)}"


CHANGE_EMAIL = next(x for x in HOWTO if x[1]["q"] == "How do I change my email address?")


@pytest.mark.xfail(strict=True, reason=(
    "BREAK: KnowledgeBase.checked('How do I change my router?', <the change-email answer>) is False with the "
    "embedder and no judge, True with the embedder and a YES judge: a judge adds the backed_loose path "
    "(kblookup.swarm_check), so its YES widens the structural check"))
@PBT
@given(entry=st.sampled_from(HOWTO), thing=st.sampled_from(FOREIGN))
@example(entry=CHANGE_EMAIL, thing="router")
def test_inv4b_judge_yes_never_widens_the_check_for_a_near_miss(entry, thing):
    verb, e = entry
    q = f"How do I {verb} my {thing}?"
    no_judge = helpdesk.KnowledgeBase().attach(BagEmbedder())
    yes = helpdesk.KnowledgeBase().attach(BagEmbedder())
    yes.judge = YesJudge()
    assert yes.checked(q, e["a"]) <= no_judge.checked(q, e["a"]), f"{q!r}: YES judge passed {e['q']!r}'s answer"


# ---- k2 (code reading): each test shows one break found by reading the PR diff -----------------------------------
K2_FAQ = {e["q"]: e["a"] for e in FAQ}
K2_PASSWORD = K2_FAQ["How do I reset my password?"]
K2_TUE, K2_WED, K2_THU, K2_SAT = (dt.date(2026, 11, 24), dt.date(2026, 11, 25), dt.date(2026, 11, 26),
                                  dt.date(2026, 11, 28))


class K2Bag:
    """One slot per word (hash mod 97); the same stand-in tests/test_skeleton_swarm.py uses."""

    def embed(self, text):
        v = [0.0] * 97
        for w in re.findall(r"[a-z]+", text.lower()):
            v[sum(map(ord, w)) % 97] += 1.0
        return v


def _k2_swarm(kb, answer, ns):
    """A help-desk or store swarm whose every tier answers `answer`."""
    inner = Assistant({"mode": "demo", "namespace": ns, "ladder": SWARM_LADDER}, knowledge=kb, verify=kb.grounded,
                      demo_models={t: (lambda p: answer) for t in SWARM_LADDER})
    hd = isinstance(kb, helpdesk.KnowledgeBase)
    free = ([("rules", Rules.for_faq(kb.data).match)] if hd else []) + [("kb_lookup", kb.lookup().match)]
    return Swarm(inner, free=free, check=kb.checked, fallback=helpdesk.FALLBACK if hd else store.FALLBACK,
                 covered=kb.covered)


@pytest.mark.xfail(strict=True, reason="BREAK k2 (kblookup.py backed, no judge): make_assistant(swarm=True) "
                   "'How do I reset my router?' -> the password steps, verified=True")
def test_k2_1_router():
    a = helpdesk.make_assistant(swarm=True).ask("How do I reset my router?")
    assert a["answer"] == helpdesk.FALLBACK, (a["tier"], a["verified"], a["answer"][:50])


K2_FILLER = ["Open the Orders page and click the button.", "Support answers email within a day."]
K2_THING = st.text("bcdfghjklmnprtvwz", min_size=5, max_size=9)


@pytest.mark.xfail(strict=True, reason="BREAK k2 (kblookup.py joins_entries reads only the question): "
                   "'How much is the bdfgh plan?' -> 'The bdfgh plan costs 3 dollars, with klmnp.' passes all 3 paths")
@PBT
@given(K2_THING, K2_THING, st.integers(1, 9), st.integers(10, 99))
@example("bdfgh", "klmnp", 3, 20)
def test_k2_2_join(a, b, n, m):
    if a == b:
        return
    lines = [f"The {a} plan costs {n} dollars.", f"We offer {b} in {m} days."] + K2_FILLER
    q, ans = f"How much is the {a} plan?", f"The {a} plan costs {n} dollars, with {b}."  # no entry pairs a with b
    sem = Semantic(K2Bag(), lines, lines)
    got = (swarm_check(lines, None, None, q, ans), swarm_check(lines, sem, None, q, ans),
           swarm_check(lines, sem, YesJudge(), q, ans))
    assert got == (False, False, False)


@pytest.mark.xfail(strict=True, reason="BREAK k2: 'How long does express take to Toronto?' -> 'Express takes 1 to 2 "
                   "business days to Canada.' served and cached (KB: Canada takes 5 to 8 days)")
def test_k2_2b_join_e2e():
    bot = _k2_swarm(helpdesk.KnowledgeBase(), "Express takes 1 to 2 business days to Canada.", "k2-join")
    a = bot.ask("How long does express take to Toronto?")
    assert a["answer"] == helpdesk.FALLBACK, (a["tier"], a["verified"])


@pytest.mark.xfail(strict=True, reason="BREAK k2 (kblookup.py backed): checked('Is express shipping free?', "
                   "'Yes, express shipping is free.') is True; the KB says express is $14.99")
def test_k2_3_contradiction():
    assert not KB.checked("Is express shipping free?", "Yes, express shipping is free.")


K2_SPECIALS = [(d, s) for d in (dt.date(2026, 11, 23) + dt.timedelta(i) for i in range(7))
               for s in store.Catalog(today=d).data["specials"][d.strftime("%A").lower()]]


@pytest.mark.xfail(strict=True, reason="BREAK k2 (store.py lookup): Thursday 'Bananas, per kg' stays in the $0 "
                   "lookup although 'Bananas at 0.99 per kg' is on special (comma names never match the specials text)")
@PBT
@given(st.sampled_from(K2_SPECIALS))
@example((K2_THU, "Bananas at 0.99 per kg"))
def test_k2_4_specials(day_special):
    day, special = day_special
    c = store.Catalog(today=day)
    item = next(i["name"] for i in c.data["items"] if special.lower().startswith(i["name"].split(",")[0].lower()))
    assert item not in [k for k, _ in c.lookup().raw], (day.strftime("%A"), special)


@pytest.mark.xfail(strict=True, reason="BREAK k2: Saturday 'How much are the croissants?' -> $3.99 (special 2.99)")
def test_k2_4b_croissants():
    a = store.make_assistant(swarm=True, catalog=store.Catalog(today=K2_SAT)).ask("How much are the croissants?")
    assert "3.99" not in a["answer"], (a["tier"], a["answer"])


@pytest.mark.xfail(strict=True, reason="BREAK k2 (store.py specials guard needs the full name): Tuesday "
                   "checked('How much is salmon today?', 'Salmon fillet is $7.49 in aisle 4.') is True with a YES judge")
def test_k2_4c_salmon():
    c = store.Catalog(today=K2_TUE).attach(K2Bag())  # specials: Salmon fillet at 5.99
    c.judge = YesJudge()
    assert not c.checked("How much is salmon today?", "Salmon fillet is $7.49 in aisle 4.")


K2_NOT_VEGAN = [i for i in ITEMS if "vegan" not in i.get("tags", []) and i["name"] not in ("Ground coffee", "Greek yogurt")]


@pytest.mark.xfail(strict=True, reason="BREAK k2 (kblookup.py KEY_DF: 'vegan' is in 4 lines): Wednesday "
                   "checked('Is the free-range eggs, 12 vegan?', 'Free-range eggs, 12 is vegan: aisle 3, $4.99.') is True")
@PBT
@given(st.sampled_from(K2_NOT_VEGAN))
@example(next(i for i in ITEMS if i["name"] == "Free-range eggs, 12"))
def test_k2_5_vegan(item):
    c = store.Catalog(today=K2_WED)
    claim = f"{item['name']} is vegan: aisle {item['aisle']}, ${item['price']}."
    assert not c.checked(f"Is the {item['name'].lower()} vegan?", claim)


_K2_KB = helpdesk.KnowledgeBase().attach(K2Bag())
_K2_SEM, _K2_LINES = _K2_KB.semantic(), _K2_KB.lines()
K2_SENTS = [s.strip() + "." for a in K2_FAQ.values() for s in a.split(".") if s.strip()]
K2_TWO = ("How do I reset my password?", "Go to the sign-in page and click Forgot password.",
          "Visa, Mastercard, American Express, PayPal and gift cards.")


@pytest.mark.xfail(strict=True, reason="BREAK k2 (94f8b61, kblookup.py swarm_check adds backed_loose only with a "
                   "judge): 'How do I change my email address?' + 'Go to the sign-in page and click Forgot password. "
                   "Sign in, open Account, then Profile, and click Change email.': refused with no judge, passes on YES")
@PBT
@given(st.sampled_from(list(K2_FAQ)), st.sampled_from(K2_SENTS), st.sampled_from(K2_SENTS))
@example("How do I change my email address?", "Go to the sign-in page and click Forgot password.",
         "Sign in, open Account, then Profile, and click Change email.")
def test_k2_6_widen(q, s1, s2):
    ans = f"{s1} {s2}" if s1 != s2 else s1
    assert swarm_check(_K2_LINES, _K2_SEM, YesJudge(), q, ans) <= swarm_check(_K2_LINES, _K2_SEM, None, q, ans)


def test_k2_6b_widen():
    """Was a BREAK at c36807c (served on a YES judge); one_source at 3b31604 refuses it. Kept as a regression check."""
    ans = f"{K2_TWO[1]} {K2_TWO[2]}"
    assert not swarm_check(_K2_LINES, _K2_SEM, None, K2_TWO[0], ans)  # structure alone: refused
    assert not swarm_check(_K2_LINES, _K2_SEM, YesJudge(), K2_TWO[0], ans)  # two entries: must refuse


def _k2_judge_model(prompt):
    """Stand-in yes/no model: YES only when the question's thing is in the entries."""
    q = re.search(r"Customer question: (.*)", prompt).group(1).lower()
    thing = next((w for w in ("router", "pause", "password", "subscription") if w in q), None)
    return "YES" if thing is None or thing in prompt.split("Customer question:")[0].lower() else "NO"


def _k2_judged(ns):
    kb = helpdesk.KnowledgeBase().attach(K2Bag())
    kb.judge = Judge(Assistant({"mode": "demo", "namespace": f"{ns}:judge", "ladder": ["cloud-top"], "instructions": "",
                                "max_tokens": 400}, demo_models={"cloud-top": _k2_judge_model}))
    return _k2_swarm(kb, K2_PASSWORD, ns), kb


@pytest.mark.xfail(strict=True, reason="BREAK k2 (swarm.py Judge asks through a cached Assistant): after 'I need to "
                   "reset my password, how?' the judge's cached YES is a cosine hit for '...router, how?' -> password "
                   "steps; a fresh bot serves the fallback")
def test_k2_7_judge_cache():
    fresh, _ = _k2_judged("k2-fresh")
    assert fresh.ask("I need to reset my router, how?")["answer"] == helpdesk.FALLBACK  # control: an honest judge says NO
    bot, _ = _k2_judged("k2-warm")
    bot.ask("I need to reset my password, how?")
    a = bot.ask("I need to reset my router, how?")
    assert a["answer"] == helpdesk.FALLBACK, (a["tier"], a["verified"], a["tried"])


@pytest.mark.xfail(strict=True, reason="BREAK k2 (swarm.py ask: covers() runs before j_before): 'How do I pause my "
                   "subscription?' -> no_fact with dollars 0 and tried []; the judge spent about $0.000009")
def test_k2_8_judge_cost():
    bot, kb = _k2_judged("k2-cost")
    n0 = len(bot.router.tracker.events)
    a = bot.ask("How do I pause my subscription?")
    spent = kb.judge.bot.stats()["dollars"]
    row = bot.router.tracker.events[n0:][-1]
    assert a["tier"] == "no_fact" and spent > 0
    assert a["dollars"] == pytest.approx(spent) and row.dollars_spent == pytest.approx(spent), \
        (a["dollars"], a["tried"], row.dollars_spent, row.dollars_saved)
