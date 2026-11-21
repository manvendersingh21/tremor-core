"""Properties of the skeleton core and the coder path guard (demo mode: stub models, in-memory cache, offline)."""
import pathlib

from hypothesis import given, strategies as st

from skeleton.apps.coder.coder import Coder
from skeleton.core import Assistant

from tests._props import PBT, PBT_SLOW

QUESTION = st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), min_size=1, max_size=60).filter(lambda s: s.strip())


def _bot(verify=None):
    # the 30B stub echoes the question; the 763B stub is the same, so every answer is "echo: <question>"
    echo = lambda p: "echo: " + p.rsplit("Question:", 1)[-1].strip()  # noqa: E731
    return Assistant({"mode": "demo", "namespace": "props"}, demo_models={"gpu-small": echo, "cloud-deepseek": echo}, verify=verify)


@PBT_SLOW
@given(st.lists(QUESTION, min_size=1, max_size=12))
def test_stats_add_up_and_a_hit_costs_no_tokens(qs):
    bot, answers = _bot(), []
    for q in qs:
        answers.append(bot.ask(q))
    s = bot.stats()
    assert s["questions"] == len(qs) and sum(s["by_tier"].values()) == len(qs)
    assert s["cache_hits"] == sum(a["cache_hit"] for a in answers) <= len(qs)
    assert all(a["tokens"] == 0 for a in answers if a["cache_hit"])
    assert all(a["tokens"] >= 0 and a["dollars"] >= 0 and a["dollars_saved"] >= 0 for a in answers)


@PBT_SLOW
@given(st.lists(QUESTION, min_size=1, max_size=8), st.sets(st.integers(0, 9), max_size=9))
def test_a_failed_check_is_never_served_as_verified(qs, banned_digits):
    """verify rejects any answer containing a banned digit: a verified answer always passes it, and a repeat never turns a failure into a pass."""
    bad = {str(d) for d in banned_digits}
    verify = lambda text: not any(d in text for d in bad)  # noqa: E731
    bot = _bot(verify)
    for q in qs * 2:
        a = bot.ask(q)
        assert (a["verified"] is True) == verify(a["answer"])
        if a["cache_hit"]:
            assert a["verified"] is True or not verify(a["answer"])


@PBT
@given(st.text(max_size=40), st.text(max_size=40))
def test_namespace_changes_with_facts_or_context(facts, context):
    bot = _bot()
    ns = bot._namespace
    assert ns(facts, context) == ns(facts, context)
    if (facts, context) != ("", ""):
        assert ns(facts, context).startswith("props:")
    if facts != context and facts and context:
        assert ns(facts, "") != ns(context, "")


SEGMENT = st.sampled_from(["a", "b.py", "..", ".", ".env", ".ENV", ".env.local", ".git", "x.pem", "sub", ""])


@PBT
@given(st.lists(SEGMENT, min_size=1, max_size=5))
def test_coder_refuses_escapes_and_secret_names(tmp_path_factory, parts):
    repo = tmp_path_factory.mktemp("repo")
    c = Coder(repo, [], "true")
    rel = "/".join(parts)
    target = (repo / rel).resolve()
    if not target.is_relative_to(repo.resolve()):
        assert not c._safe(rel)
        return
    names = target.relative_to(repo.resolve()).parts
    secret = ".git" in names or any(n.lower().startswith(".env") or n.lower().endswith((".pem", ".key")) for n in names)
    assert c._safe(rel) is not secret
