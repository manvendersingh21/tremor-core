"""skeleton/apps/helpdesk: knowledge base, grounding check, warm-up, cost per ticket, HTTP API (demo, offline)."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from skeleton.apps.helpdesk.helpdesk import KnowledgeBase, make_assistant, seed
from skeleton.apps.helpdesk.server import App, handler, per_ticket


def test_kb_lines_and_version(tmp_path):
    kb = KnowledgeBase()
    assert "Q: How do I reset my password? A: Go to the sign-in page" in kb.text
    assert "1-800-555-0142" in kb.text
    other = tmp_path / "kb.json"
    other.write_text(json.dumps({**kb.data, "company": "Other"}))
    assert KnowledgeBase(other).version != kb.version  # an edited KB gets a fresh cache section


@pytest.mark.parametrize("answer,ok", [
    ("Unused items can be returned within 30 days of delivery.", True),
    ("Call 1-800-555-0142 between 9:00 and 17:00.", True),
    ("Returns are accepted within 60 days.", False),  # a number the KB never gives
    ("Call 1-800-555-9999.", False),
    ("I don't know.", False),  # climbs
    ("", False),
])
def test_grounded(answer, ok):
    assert KnowledgeBase().grounded(answer) is ok


def test_warm_cache_answers_repeats_and_rewording_without_models():
    bot = make_assistant()
    assert seed(bot)["questions"] == 30 and bot.stats()["questions"] == 0
    for q in ("How do I reset my password?", "how do i reset my password", "Please tell me how to cancel my order"):
        a = bot.ask(q)
        assert a["cache_hit"] and a["tokens"] == 0 and a["tokens_saved"] > 0, q
    novel = bot.ask("Why was my card charged twice?")  # not in the KB: climbs, served unverified, never cached
    assert novel["tried"] == ["gpu-small", "cloud-deepseek"] and novel["verified"] is False
    assert not bot.ask("Why was my card charged twice?")["cache_hit"]


def test_per_ticket_cost():
    s = {"questions": 4, "tokens": 400, "dollars": 0.0004, "dollars_saved": 0.0012}
    assert per_ticket(s) == {"tickets": 4, "tokens": 100.0, "dollars": 0.0001, "big_only_dollars": 0.0004}
    assert per_ticket({"questions": 0, "tokens": 0, "dollars": 0.0, "dollars_saved": 0.0})["tokens"] == 0


def test_http_api():
    from http.server import ThreadingHTTPServer
    app = App()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def post(body: bytes):
        req = urllib.request.Request(base + "/api/ask", data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        code, a = post(json.dumps({"q": "Where is my order?"}).encode())
        assert code == 200 and a["cache_hit"] and a["mode"] == "demo" and "Track" in a["answer"]
        assert post(json.dumps({"q": "x" * 501}).encode())[0] == 413
        assert post(json.dumps({"q": "  "}).encode())[0] == 400
        assert post(b"not json")[0] == 400
        assert post(b"x" * 5000)[0] == 413
        with urllib.request.urlopen(base + "/api/stats") as r:
            s = json.loads(r.read())
        assert s["questions"] == 31 and s["warmup_tickets"] == 30 and s["per_ticket"]["tickets"] == 31
        assert [c["tickets"] for c in s["curve"]] == [1, 5, 10, 20, 30]
        with urllib.request.urlopen(base + "/") as r:
            assert b"Support chat" in r.read()
    finally:
        srv.shutdown()
