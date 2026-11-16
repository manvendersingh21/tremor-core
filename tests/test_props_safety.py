"""Property tests for scrub(), the risk scorer, memory, and the API shapes. Fakes only. Properties P16-P24."""
import json
import re

import pytest
from hypothesis import example, given, strategies as st

from _props import PBT
from test_memory import BagEmbedder

from chimera_core.config import ChimeraConfig
from chimera_core.firewall.risk_scorer import APPROVAL_THRESHOLD, score_action, verify_approval
from chimera_core.memory import InMemoryStore, Memory, scrub
from chimera_core.service import ApiError, Service, summarize
from chimera_core.inference.telemetry import Telemetry

ALNUM = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
word = st.text(alphabet="abcdefghij ", max_size=20)
tok = lambda n, m: st.text(alphabet=ALNUM, min_size=n, max_size=m)


def luhn_complete(body: str) -> str:
    tot = sum(x if i % 2 == 0 else (x * 2 - 9 if x > 4 else x * 2) for i, x in enumerate(map(int, reversed(body + "0"))))
    return body + str((10 - tot % 10) % 10)


email = st.builds(lambda a, b, c: f"{a}@{b}.{c}", tok(1, 10), tok(1, 8), st.sampled_from(["com", "org", "io"]))
apikey = st.builds(lambda p, k: f"{p}-{k}", st.sampled_from(["sk", "pk", "ghp", "gsk"]), tok(16, 40))
jwt = st.builds(lambda a, b, c: f"eyJ{a}.{b}.{c}", tok(8, 20), tok(8, 20), tok(8, 20))
dburl = st.builds(lambda s, u, p, h: f"{s}://{u}:{p}@{h}.example/db", st.sampled_from(["postgres", "postgresql", "mysql", "redis"]),
                  tok(2, 8), tok(2, 8), tok(2, 8))
card = st.builds(lambda d, sep: luhn_complete(d), st.text(alphabet="0123456789", min_size=14, max_size=15), st.just(""))
SECRETS = st.one_of(email, apikey, jwt, dburl, card)


# P16 (R7.1): scrub output never contains an email, key, JWT, DB URL or Luhn-valid card
@PBT
@given(word, SECRETS, word)
def test_scrub_removes_every_secret_kind(a, secret, b):
    out = scrub(f"{a} {secret} {b}")
    assert secret not in out


punct = st.sampled_from(["", " ", ",", ".", "(", ")", '"', "'", "=", ":", "/", "-", "\n", ";"])


@PBT
@given(punct, SECRETS, punct)
def test_scrub_removes_secrets_next_to_punctuation(a, secret, b):
    assert secret not in scrub(a + secret + b)


@PBT
@example("", "00000000000000", "_")
@given(st.sampled_from(["", "_", "x", "card_"]), st.text(alphabet="0123456789", min_size=14, max_size=15), st.sampled_from(["", "_", "x"]))
def test_scrub_removes_cards_glued_to_word_characters(a, body, b):
    c = luhn_complete(body)
    assert c not in scrub(a + c + b)


def test_scrub_card_glued_to_underscores_but_not_longer_digit_runs():
    assert "4111111111111111" not in scrub("id_4111111111111111_x")
    assert "12345678901234567890" in scrub("order 12345678901234567890")  # 20 digits is not a card length


@PBT
@given(word, st.text(alphabet="0123456789", min_size=14, max_size=15), st.sampled_from(["", " ", "-"]), word)
def test_scrub_removes_spaced_cards(a, body, sep, b):
    card_ = luhn_complete(body)
    spaced = sep.join(card_[i:i + 4] for i in range(0, len(card_), 4))
    assert re.sub(r"\D", "", scrub(f"{a} {spaced} {b}")) .find(card_) == -1


# P17 (R7.1): scrub is idempotent
@PBT
@given(word, SECRETS, st.text(max_size=40))
def test_scrub_is_idempotent(a, secret, tail):
    s = f"{a} {secret} {tail}"
    assert scrub(scrub(s)) == scrub(s)


# P18 (R5.3, R7.2): risk score is in 0..100, approval iff >= 70, and the token is issued exactly then
@PBT
@given(st.text(max_size=80))
def test_risk_score_range_and_approval_rule(action):
    v = score_action(action)
    assert 0 <= v.score <= 100
    assert v.needs_approval == (v.score >= APPROVAL_THRESHOLD)
    assert (v.approval_token is not None) == v.needs_approval
    if v.needs_approval:
        assert verify_approval(v, "ok " + v.approval_token.upper())
        assert not verify_approval(v, "yes please")


RISKY = ["pay", "delete", "merge pr", "force push", "rm -rf /", "drop table x", "wire transfer", "unlock", "git push"]


# P19 (R7.3): adding a risky verb never lowers the score
@PBT
@given(st.text(max_size=60), st.sampled_from(RISKY))
def test_adding_a_risky_verb_never_lowers_the_score(action, verb):
    assert score_action(f"{action} {verb}").score >= score_action(action).score


# P20 (R8.1): memory stores only verified answers
@PBT
@given(st.booleans(), st.sampled_from([True, False, None]), st.one_of(st.none(), st.floats(0, 5)),
       st.sampled_from(["", "  ", "x = 1"]), st.sampled_from(["", "sort a list"]))
def test_memory_refuses_unverified_answers(verified, tests, score, answer, prompt):
    m = Memory(InMemoryStore(), BagEmbedder(), "t")
    pid = m.store(prompt, answer, model="big", tier="top", verified=verified, tests=tests, score=score)
    ok = verified and (tests is True or (tests is None and score is not None and score >= 4)) and answer.strip() and prompt.strip()
    assert (pid is not None) == bool(ok)
    assert (len(m.graph.pairs) == 1) == bool(ok)


# P21 (R8.2): purge removes all of one tenant's rows and none of another's
@PBT
@given(st.lists(st.sampled_from(["sort a list", "reverse a string", "sum numbers", "parse json"]), min_size=1, max_size=5, unique=True),
       st.lists(st.sampled_from(["sort a list", "reverse a string", "merge dicts"]), min_size=1, max_size=4, unique=True))
def test_memory_purge_is_scoped_to_the_tenant(a_prompts, b_prompts):
    store = InMemoryStore()
    a, b = Memory(store, BagEmbedder(), "a"), Memory(store, BagEmbedder(), "b")
    for p in a_prompts:
        assert a.store(p, "def f(): pass", model="m", tier="top", verified=True, tests=True) is not None
    for p in b_prompts:
        assert b.store(p, "def g(): pass", model="m", tier="top", verified=True, tests=True) is not None
    before_b = b.graph.stats("b")
    assert a.purge() > 0
    assert all(v == 0 for v in a.graph.stats("a").values())
    assert b.graph.stats("b") == before_b


# P22 (R8.3): what memory stores is scrubbed
@PBT
@given(email)
def test_memory_never_keeps_an_email(addr):
    m = Memory(InMemoryStore(), BagEmbedder(), "t")
    m.store(f"mail {addr} about sorting", f"send to {addr}", model="m", tier="top", verified=True, tests=True)
    assert all(addr not in p.prompt and addr not in p.answer for _, p, _ in m.graph.pairs)


# P23 (R9.1): the summary behind /api/stats always has the documented fields, with sane values
STATS_KEYS = {"calls", "cache_hits", "hit_rate", "gpu_calls_avoided", "big_calls_avoided", "dollars_saved", "dollars_spent",
              "tokens_kept_off_big", "false_hits", "by_tier"}
tel = st.builds(
    lambda tier_, saved, d, src, spent: Telemetry(tier_used=tier_, tokens_saved=saved, dollars_saved=d, cache_source=src,
                                                  dollars_spent=spent).model_dump(exclude={"events", "per_tier"}),
    st.sampled_from(["exact_cache", "semantic_cache", "local", "gpu", "top"]), st.integers(0, 10**5),
    st.floats(0, 10), st.sampled_from([None, "exact", "local", "shared"]), st.floats(0, 10))


@PBT
@given(st.lists(tel, max_size=12))
def test_stats_summary_shape(rows):
    s = summarize(rows)
    assert set(s) >= STATS_KEYS and set(s["cache_hits"]) == {"exact", "local", "shared"}  # fields may be added
    assert s["tokens_today"] <= s["tokens"] and s["cache"]["all_time"]["exact"] + s["cache"]["all_time"]["cosine"] == sum(
        r.get("tier_used") in ("exact_cache", "semantic_cache") for r in rows)
    assert s["calls"] == len(rows) and 0 <= s["hit_rate"] <= 1
    assert s["tokens_kept_off_big"] >= 0 and s["dollars_saved"] >= 0 and s["dollars_spent"] >= 0
    assert sum(s["by_tier"].values()) == len(rows)
    json.dumps(s)


# P24 (R9.2): a chat action the firewall holds (score >= 70) is refused before any model is called
class CountingRouter:
    def __init__(self):
        from chimera_core.router import RouterConfig
        self.cfg, self.calls = RouterConfig(), 0

    def generate(self, prompt, on_event=None, **kw):
        self.calls += 1
        raise RuntimeError("no model in this test")


@PBT
@given(st.text(max_size=60), st.sampled_from(RISKY + ["hello"]))
def test_chat_refuses_held_actions_before_calling_the_router(prefix, verb):
    r = CountingRouter()
    svc = Service(r, ChimeraConfig(), rate_per_min=10**6, burst=10**6)
    action = f"{prefix} {verb}"
    held = score_action(action).needs_approval
    try:
        gen = svc.chat({"prompt": "hi", "action": action}, "1.2.3.4")
        list(gen)
        refused = None
    except ApiError as e:
        refused = e
    if held:
        assert refused is not None and refused.status == 403 and refused.code == "approval_required"
        assert r.calls == 0
    else:
        assert refused is None or refused.status != 403
