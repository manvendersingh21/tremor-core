"""Vice City theme: coder colours obey NO_COLOR; the pages link the shared CSS and the servers serve it."""
import io
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from skeleton.apps.coder import vice
from skeleton.apps.helpdesk import server as hd
from skeleton.apps.store import server as st


def test_no_color_wins_over_force_and_tty(monkeypatch):
    class Tty(io.StringIO):
        isatty = lambda self: True  # noqa: E731
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert vice.use_color(Tty()) and not vice.use_color(io.StringIO())
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert vice.use_color(io.StringIO())
    monkeypatch.setenv("NO_COLOR", "")
    assert not vice.use_color(Tty())


def test_paint_keeps_text():
    plain = "step 1  x  tests PASS\n+a\n-b\nanswered by x"
    import re
    assert re.sub(r"\x1b\[[0-9;]*m", "", vice.paint(plain)) == plain


def test_banner_box_is_aligned():
    import re
    widths = {len(re.sub(r"\x1b\[[0-9;]*m", "", ln)) for ln in vice.banner().splitlines()}
    assert len(widths) == 1


@pytest.mark.parametrize("mod", [hd, st])
def test_page_links_shared_css(mod):
    assert 'href="/vicecity.css"' in mod.INDEX.read_text()
    assert mod.CSS.exists()
    app = mod.App()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mod.handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{srv.server_port}/vicecity.css")
        assert r.headers["Content-Type"].startswith("text/css") and b"--pink" in r.read()
    finally:
        srv.shutdown()
