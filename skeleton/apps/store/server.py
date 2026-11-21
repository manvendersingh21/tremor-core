"""Food-store helper web app: one page and a small JSON API, standard library only.

    .venv/bin/python -m skeleton.apps.store            # demo: stub models, in-memory cache, no keys
    .venv/bin/python -m skeleton.apps.store --live     # A6000 30B, then the 763B, Supabase cache

GET /                 the page
GET /api/guide        store name, today's specials, hours, sample questions
GET|POST /api/ask     {"q": "..."} (1-300 characters) -> the skeleton Answer + mode
GET /api/stats        the Assistant's totals since the cache was warmed, + the warm-up totals
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .store import QUESTIONS, Catalog, make_assistant, seed

INDEX = pathlib.Path(__file__).resolve().parent / "index.html"
MAX_Q, MAX_BODY = 300, 4096


class App:
    def __init__(self, live: bool = False, warm: bool = True, catalog: Catalog | None = None, no_gpu: bool = False) -> None:
        self.catalog = catalog or Catalog()
        self.bot = make_assistant(live, self.catalog, no_gpu=no_gpu)
        self.mode = "live" if live else "demo"
        self.questions = json.loads(QUESTIONS.read_text())["seed"]
        self.warmup = seed(self.bot, self.questions) if warm else {}

    def guide(self) -> dict:
        d = self.catalog.data
        return {"store": d["store"], "day": self.catalog.weekday, "specials": d["specials"][self.catalog.weekday],
                "hours": d["hours"], "samples": self.questions[:10], "mode": self.mode}

    def ask(self, q) -> tuple[int, dict]:
        if not isinstance(q, str) or not q.strip():
            return 400, {"error": {"code": "empty", "message": "ask a question"}}
        if len(q) > MAX_Q:
            return 413, {"error": {"code": "too_long", "message": f"at most {MAX_Q} characters"}}
        try:
            return 200, {**self.bot.ask(q.strip()), "mode": self.mode}
        except Exception as e:  # noqa: BLE001  every tier failed: say so, never a made-up answer
            return 503, {"error": {"code": "all_tiers_failed", "message": type(e).__name__}}

    def stats(self) -> dict:
        return {**self.bot.stats(), "mode": self.mode, "warmup": self.warmup}


def handler(app: App):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                return self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/guide":
                return self._json(200, app.guide())
            if u.path == "/api/stats":
                return self._json(200, app.stats())
            if u.path == "/api/ask":
                return self._json(*app.ask(parse_qs(u.query).get("q", [""])[0]))
            self._json(404, {"error": {"code": "not_found", "message": u.path}})

        def do_POST(self):
            if urlparse(self.path).path != "/api/ask":
                return self._json(404, {"error": {"code": "not_found", "message": self.path}})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                return self._json(413, {"error": {"code": "body_too_large", "message": f"at most {MAX_BODY} bytes"}})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._json(400, {"error": {"code": "bad_json", "message": "send {\"q\": \"...\"}"}})
            self._json(*app.ask(body.get("q") if isinstance(body, dict) else None))

        def _json(self, code: int, data: dict) -> None:
            self._send(code, json.dumps(data).encode(), "application/json")

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a) -> None:  # no request log: questions stay out of the terminal
            pass
    return H


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m skeleton.apps.store")
    ap.add_argument("--live", action="store_true", help="real tiers and the Supabase cache (keys from .env)")
    ap.add_argument("--no-gpu", action="store_true", dest="no_gpu", help="live, Crusoe 763B only + Supabase; no GPU needed")
    ap.add_argument("--port", type=int, default=8767)
    ap.add_argument("--no-warm", action="store_true", help="skip asking the 30 common questions at start")
    args = ap.parse_args(argv)
    print(f"warming the cache with the common questions ({'live' if args.live else 'demo'})...", flush=True)
    app = App(live=args.live or args.no_gpu, warm=not args.no_warm, no_gpu=args.no_gpu)
    w = app.warmup
    if w:
        print(f"warm: {w['questions']} questions, {w['cache_hits']} already cached, {w['model_calls']} model calls")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), handler(app))
    print(f"food-store helper on http://127.0.0.1:{args.port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
