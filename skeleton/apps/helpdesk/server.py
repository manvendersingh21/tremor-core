"""Help-desk web app: one support-chat page and a small JSON API, standard library only.

    .venv/bin/python -m skeleton.apps.helpdesk           # demo: stub models, in-memory cache, no keys
    .venv/bin/python -m skeleton.apps.helpdesk --live    # 30B on your GPU box, then the 763B, Supabase cache

GET /                 the page
GET /api/info         company, hours, sample questions, mode
GET|POST /api/ask     {"q": "..."} (1-500 characters) -> the skeleton Answer + mode
GET /api/stats        totals since start (the 30 warm-up tickets count as the first tickets) and cost per ticket
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .helpdesk import QUESTIONS, KnowledgeBase, make_assistant

INDEX = pathlib.Path(__file__).resolve().parent / "index.html"
MAX_Q, MAX_BODY = 500, 4096
MARKS = (1, 5, 10, 20, 30, 50, 100, 200, 500, 1000, 2000, 5000, 10000)


class App:
    def __init__(self, live: bool = False, warm: bool = True, kb: KnowledgeBase | None = None, no_gpu: bool = False) -> None:
        self.kb = kb or KnowledgeBase()
        self.bot = make_assistant(live, self.kb, no_gpu=no_gpu)
        self.mode = "live" if live else "demo"
        self.questions = json.loads(QUESTIONS.read_text())["seed"]
        self._lock = threading.Lock()
        self.curve: list[dict] = []  # cost per ticket at 1, 5, 10, ... tickets (warm-up included)
        if warm:
            for q in self.questions:
                self.bot.ask(q)
                self._mark()
        self.warmup = self.bot.stats()

    def _mark(self) -> None:
        """Record cost per ticket when the ticket count reaches a mark."""
        s = self.bot.stats()
        n = s["questions"]
        if n in MARKS:
            with self._lock:
                self.curve.append(per_ticket(s))

    def info(self) -> dict:
        d = self.kb.data
        return {"company": d["company"], "hours": d["hours"], "samples": self.questions[:10], "mode": self.mode}

    def ask(self, q) -> tuple[int, dict]:
        if not isinstance(q, str) or not q.strip():
            return 400, {"error": {"code": "empty", "message": "write a question"}}
        if len(q) > MAX_Q:
            return 413, {"error": {"code": "too_long", "message": f"at most {MAX_Q} characters"}}
        try:
            a = self.bot.ask(q.strip())
        except Exception as e:  # noqa: BLE001  every tier failed: say so, never a made-up answer
            return 503, {"error": {"code": "all_tiers_failed", "message": type(e).__name__}}
        self._mark()
        return 200, {**a, "mode": self.mode}

    def stats(self) -> dict:
        s = self.bot.stats()
        with self._lock:
            curve = list(self.curve)
        return {**s, "mode": self.mode, "warmup_tickets": self.warmup["questions"], "per_ticket": per_ticket(s),
                "curve": curve}


def per_ticket(s: dict) -> dict:
    """What one ticket costs on average so far: model tokens and $ (763B list price; the 30B is owned, $0),
    against the 763B-only estimate (spent + saved)."""
    n = max(s["questions"], 1)
    return {"tickets": s["questions"], "tokens": round(s["tokens"] / n, 1), "dollars": round(s["dollars"] / n, 7),
            "big_only_dollars": round((s["dollars"] + s["dollars_saved"]) / n, 7)}


def handler(app: App):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                return self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/info":
                return self._json(200, app.info())
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

        def log_message(self, *a) -> None:  # no request log: tickets stay out of the terminal
            pass
    return H


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m skeleton.apps.helpdesk")
    ap.add_argument("--live", action="store_true", help="real tiers and the Supabase cache (keys from .env)")
    ap.add_argument("--no-gpu", action="store_true", dest="no_gpu",
                    help="live but Crusoe 763B only (cache -> 763B); no GPU needed")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--no-warm", action="store_true", help="skip asking the 30 common questions at start")
    args = ap.parse_args(argv)
    live = args.live or args.no_gpu
    print(f"warming the cache with the common questions ({'live' if live else 'demo'})...", flush=True)
    app = App(live=live, warm=not args.no_warm, no_gpu=args.no_gpu)
    w = app.warmup
    if w["questions"]:
        print(f"warm: {w['questions']} tickets, {w['cache_hits']} already cached, {w['model_calls']} model calls")
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), handler(app))
    print(f"help desk on http://127.0.0.1:{args.port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
