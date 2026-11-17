"""Bearer-token gate in front of a loopback Ollama, for the Cloudflare quick tunnel (bench/a6000/serve.sh).

    python3 auth_proxy.py <listen port> <ollama port> <key file>

Listens on 127.0.0.1 only. A request without "Authorization: Bearer <key>" gets 401 and never reaches Ollama.
Only the Ollama paths the router uses are forwarded. Stdlib only (the box has no extra packages).
shortcut: buffers whole responses (the router sends stream=false); add streaming if a caller needs it.
"""
from __future__ import annotations

import hmac
import pathlib
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALLOWED = {"/api/chat", "/api/generate", "/api/tags", "/api/ps", "/api/version", "/api/show"}


def make_handler(key: str, upstream: str):
    want = f"Bearer {key}".encode()

    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # no request lines (they would hold nothing secret, but keep logs small)
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _go(self, method: str) -> None:
            got = (self.headers.get("Authorization") or "").encode()
            if not hmac.compare_digest(got, want):
                return self._send(401, b'{"error":"unauthorized"}')
            path = self.path.split("?", 1)[0]
            if path not in ALLOWED:
                return self._send(404, b'{"error":"not found"}')
            n = int(self.headers.get("Content-Length") or 0)
            if n > 4_000_000:
                return self._send(413, b'{"error":"too large"}')
            data = self.rfile.read(n) if n else None
            req = urllib.request.Request(upstream + path, data=data, method=method,
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=600) as r:  # noqa: S310 (loopback upstream)
                    self._send(r.status, r.read(), r.headers.get("Content-Type", "application/json"))
            except urllib.error.HTTPError as e:
                self._send(e.code, e.read())
            except Exception:  # noqa: BLE001  upstream down (yielded or loading)
                self._send(503, b'{"error":"upstream unavailable"}')

        def do_GET(self):  # noqa: N802
            self._go("GET")

        def do_POST(self):  # noqa: N802
            self._go("POST")

    return H


def main() -> None:
    listen, up, keyfile = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    key = pathlib.Path(keyfile).read_text().strip()
    if len(key) < 32:
        raise SystemExit("key too short")
    ThreadingHTTPServer(("127.0.0.1", listen), make_handler(key, f"http://127.0.0.1:{up}")).serve_forever()


if __name__ == "__main__":
    main()
