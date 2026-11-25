"""skeleton/apps/store: catalog, grounding check, warm-up, HTTP API (demo mode, offline)."""
import datetime as dt
import json
import threading
import urllib.error
import urllib.request

import pytest

from skeleton.apps.store.server import App, handler
from skeleton.apps.store.store import Catalog, make_assistant, seed

TUESDAY = dt.date(2026, 11, 17)


def test_catalog_version_changes_with_the_day_and_lists_specials():
    c = Catalog(today=TUESDAY)
    assert "Today's specials (Tuesday): Salmon fillet at 5.99" in c.text
    assert "Oat milk: aisle 3, $3.49" in c.text
    assert Catalog(today=TUESDAY + dt.timedelta(days=1)).version != c.version


@pytest.mark.parametrize("answer,ok", [
    ("Oat milk is in aisle 3, $3.49.", True),
    ("Salmon is on special at $5.99 today.", True),
    ("Oat milk is in aisle 30.", False),        # no such aisle
    ("Oat milk costs $2.00.", False),          # a price the catalog never lists
    ("I don't know.", False),                  # climbs
    ("", False),
])
def test_grounded(answer, ok):
    assert Catalog(today=TUESDAY).grounded(answer) is ok


def test_checked_refuses_regular_price_for_specials_items():
    """When salmon is on special today, an answer with the regular price must fail the check."""
    c = Catalog(today=TUESDAY)  # Tuesday: Salmon fillet at 5.99
    q = "What is the price of salmon fillet?"
    # regular price is in the catalog but wrong today
    assert not c.checked(q, "Salmon fillet: aisle 4, $7.49.")
    # a non-specials item still passes grounded (aisle check is a separate rule)
    assert c.grounded("Oat milk: aisle 3, $3.49.")



    bot = make_assistant(catalog=Catalog(today=TUESDAY))
    warm = seed(bot)
    assert warm["questions"] == 30 and bot.stats()["questions"] == 0
    for q in ("Where do I find oat milk?", "where is the oat milk", "Is the kitchen open now?"):
        a = bot.ask(q)
        assert a["cache_hit"] and a["tokens"] == 0 and a["tokens_saved"] > 0, q
    novel = bot.ask("Can I order a birthday cake?")  # the stub 30B has no answer: climbs, not cached
    assert novel["tried"] == ["gpu-small", "cloud-deepseek"] and novel["verified"] is False
    s = bot.stats()
    assert (s["cache_hits"], s["model_calls"], s["unverified"]) == (3, 2, 1)


def test_http_api(tmp_path):
    from http.server import ThreadingHTTPServer
    app = App(catalog=Catalog(today=TUESDAY))
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
        code, a = post(json.dumps({"q": "Where are the eggs?"}).encode())
        assert code == 200 and a["cache_hit"] and a["mode"] == "demo" and "aisle 3" in a["answer"]
        assert post(json.dumps({"q": "x" * 301}).encode())[0] == 413
        assert post(json.dumps({"q": "  "}).encode())[0] == 400
        assert post(b"not json")[0] == 400
        assert post(b"x" * 5000)[0] == 413
        with urllib.request.urlopen(base + "/api/stats") as r:
            s = json.loads(r.read())
        assert s["questions"] == 1 and s["hit_rate"] == 1.0 and s["warmup"]["questions"] == 30
        with urllib.request.urlopen(base + "/") as r:
            assert b"Ask the store" in r.read()
    finally:
        srv.shutdown()
