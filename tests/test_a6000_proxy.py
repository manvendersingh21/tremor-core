"""bench/a6000/auth_proxy.py: the token gate in front of the public tunnel. Offline: loopback servers only."""
import importlib.util
import pathlib
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

spec = importlib.util.spec_from_file_location(
    "auth_proxy", pathlib.Path(__file__).resolve().parents[1] / "bench/a6000/auth_proxy.py")
auth_proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth_proxy)
KEY = "k" * 40


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")


def serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]


@pytest.fixture()
def proxy():
    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    port = serve(up)
    px = ThreadingHTTPServer(("127.0.0.1", 0), auth_proxy.make_handler(KEY, f"http://127.0.0.1:{port}"))
    yield f"http://127.0.0.1:{serve(px)}"
    px.shutdown()
    up.shutdown()


def get(url, token=None):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_token_required_and_only_router_paths_forwarded(proxy):
    assert get(proxy + "/api/version") == 401
    assert get(proxy + "/api/version", "wrong") == 401
    assert get(proxy + "/api/version", KEY) == 200
    assert get(proxy + "/api/pull", KEY) == 404  # model management is not exposed
