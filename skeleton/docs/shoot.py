"""Screenshots for vice_city_ui.md: demo servers in-process, one headless browser at a time.

    .venv/bin/python skeleton/docs/shoot.py before|after
"""
import pathlib
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from skeleton.apps.helpdesk import server as hd
from skeleton.apps.store import server as st

OUT = pathlib.Path(__file__).resolve().parent / "img"
SIZES = {"desktop": (1280, 900), "phone": (390, 844)}


def serve(handler):
    s = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def main(tag: str) -> None:
    OUT.mkdir(exist_ok=True)
    servers = {"helpdesk": serve(hd.handler(hd.App())), "store": serve(st.handler(st.App()))}
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        for name, s in servers.items():
            for size, (w, h) in SIZES.items():
                pg = b.new_page(viewport={"width": w, "height": h})
                pg.goto(f"http://127.0.0.1:{s.server_port}/")
                pg.wait_for_timeout(600)
                pg.fill("#q", "What are your opening hours?")
                pg.click("button[type=submit]")
                pg.wait_for_timeout(800)
                pg.screenshot(path=str(OUT / f"{name}_{size}_{tag}.png"), full_page=False)
                pg.close()
        b.close()
    for s in servers.values():
        s.shutdown()
    # coder terminal output rendered as an image: ANSI -> HTML via a tiny page
    out = subprocess.run([sys.executable, "-m", "skeleton.apps.coder", "demo"], capture_output=True, text=True,
                         env={**__import__("os").environ, "FORCE_COLOR": "1"}).stdout
    import html
    import re
    def ansi(t):
        t = html.escape(t)
        def sub(m):
            c = m.group(1)
            if c.startswith("38;2;"):
                r, g, bl = c.split(";")[2:5]
                return f'</span><span style="color:rgb({r},{g},{bl})">'
            return '</span><span>'
        return re.sub(r"\x1b\[([0-9;]*)m", sub, t)
    page = f"<body style='margin:0;background:#fff'><pre style='margin:0;padding:14px;font:13px/1.35 Menlo,monospace;color:#222;background:{'#fff' if tag == 'after' else '#fff'}'><span>{ansi(out)}</span></pre>"
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        for size, (w, h) in SIZES.items():
            pg = b.new_page(viewport={"width": w, "height": h})
            pg.set_content(page)
            pg.screenshot(path=str(OUT / f"coder_{size}_{tag}.png"))
            pg.close()
        b.close()


if __name__ == "__main__":
    main(sys.argv[1])
