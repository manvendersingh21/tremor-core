"""The one server: the castle site (site/) with the dashboard inside it, SSE telemetry, bench and evals data,
and the backend API (/api/chat, /api/health, /api/stats from chimera_core.service). Stdlib only, 127.0.0.1 by default."""
from __future__ import annotations

import csv
import mimetypes
import json
import os
import pathlib
import statistics
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
BENCH = HERE.parent.parent.parent / "bench"
SITE = HERE.parent.parent.parent / "site"
TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".html": "text/html; charset=utf-8",
         ".json": "application/json", ".webp": "image/webp", ".png": "image/png", ".gif": "image/gif", ".svg": "image/svg+xml"}
sys.path.insert(0, str(BENCH))
import evallog  # noqa: E402  the one eval log (bench/evallog.py)
# The real log every router call writes (chimera.toml [telemetry]); `make demo` points HUD_TELEMETRY at the demo file instead.
TELEMETRY = pathlib.Path(os.environ.get("HUD_TELEMETRY") or os.environ.get("CHIMERA_TELEMETRY") or pathlib.Path.home() / ".chimera" / "telemetry.jsonl")
# CSV column prefix -> ledger tier. shortcut: a CSV has no per-model split, so GPU = gpu_small and cloud/top = crusoe.
CSV_TIER = {"cloud": "crusoe", "top": "crusoe", "crusoe": "crusoe", "gpu": "gpu_small", "mid": "gpu_small"}
BENCH_FILES = ["results.csv", "results_gpu.csv", "results_ladder.csv", "spec_results.csv"]


def _num(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def summarize_csv(path: pathlib.Path) -> dict:
    """One CSV -> {run, modes: {mode: stats}, categories: {cat: {mode: stats}}}. Read-only."""
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    def stats(rs: list[dict]) -> dict:
        lat = [x for r in rs if (x := _num(r.get("latency_ms"))) is not None]
        qual = [x for r in rs if (x := _num(r.get("quality"))) is not None]
        tiers: dict[str, int] = {}
        for r in rs:
            tiers[r.get("tier", "?")] = tiers.get(r.get("tier", "?"), 0) + 1
        tok = lambda suffix: sum(  # noqa: E731
            _num(v) or 0 for r in rs for k, v in r.items() if k.endswith(suffix) and k != "cloud_cached_tokens")
        per_tier: dict[str, dict] = {}  # only tiers whose columns exist in this CSV
        for k in rs[0] if rs else []:
            if k.endswith("_prompt_tokens") and CSV_TIER.get(k[:-14]):
                t = per_tier.setdefault(CSV_TIER[k[:-14]], {"input_tokens": 0, "output_tokens": 0})
                t["input_tokens"] += int(sum(_num(r.get(k)) or 0 for r in rs))
                t["output_tokens"] += int(sum(_num(r.get(k[:-14] + "_completion_tokens")) or 0 for r in rs))
        if rs and "local_tokens" in rs[0]:  # local tokens are one number, not split in/out
            per_tier["mac_3b"] = {"input_tokens": None, "output_tokens": int(sum(_num(r.get("local_tokens")) or 0 for r in rs))}
        return {
            "n": len(rs), "tiers": tiers, "per_tier": per_tier,
            "latency_mean_ms": round(statistics.fmean(lat), 1) if lat else None,
            "latency_p50_ms": round(statistics.median(lat), 1) if lat else None,
            "quality_mean": round(statistics.fmean(qual), 3) if qual else None,
            "usd": round(sum(_num(r.get("usd")) or 0 for r in rs), 6),
            "remote_tokens": int(tok("_prompt_tokens") + tok("_completion_tokens")),
            "local_tokens": int(sum(_num(r.get("local_tokens")) or 0 for r in rs)),
        }

    modes = list(dict.fromkeys(r["mode"] for r in rows if r.get("mode")))
    cats = list(dict.fromkeys(r.get("cat", "") for r in rows))
    by = lambda m, c=None: [r for r in rows if r.get("mode") == m and (c is None or r.get("cat") == c)]  # noqa: E731
    return {
        "run": path.stem, "file": path.name, "baseline": modes[0] if modes else None,
        "modes": {m: stats(by(m)) for m in modes},
        "categories": {c: {m: stats(by(m, c)) for m in modes if by(m, c)} for c in cats if c},
    }


def bench_summary(bench_dir: pathlib.Path = BENCH) -> dict:
    runs = []
    for name in BENCH_FILES:
        p = bench_dir / name
        if p.is_file():
            try:
                runs.append(summarize_csv(p))
            except (OSError, KeyError, csv.Error) as e:  # a worker may be mid-write
                runs.append({"run": p.stem, "file": name, "error": str(e), "modes": {}, "categories": {}})
    return {"runs": runs}


def read_new_events(path: pathlib.Path, offset: int) -> tuple[list[dict], int]:
    """Return complete JSON lines written after `offset` and the new offset. Resets if file shrank."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return [], 0
    if size < offset:
        offset = 0
    with open(path, "rb") as fh:
        fh.seek(offset)
        chunk = fh.read()
    end = chunk.rfind(b"\n") + 1  # leave a partial last line for the next poll
    events = []
    for line in chunk[:end].splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return events, offset + end


def _api(h, method: str) -> bool:
    """/api/chat, /api/health, /api/stats from chimera_core.service. Imported on first use (the router is heavy)."""
    sys.path.insert(0, str(HERE.parent.parent.parent))
    import conftest  # noqa: F401  registers the hyphenated package as chimera_core
    from chimera_core.service import handle_http
    return handle_http(h, method)


def static_file(path: str) -> pathlib.Path | None:
    """A file under site/ for a URL path, or None. "/" is index.html; nothing outside site/ and no dotfiles."""
    rel = "index.html" if path in ("/", "") else path.lstrip("/")
    if any(part.startswith(".") for part in rel.split("/")):
        return None
    f = (SITE / rel).resolve()
    return f if f.is_file() and SITE.resolve() in f.parents else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if not _api(self, "POST"):
            self._send(404, b"not found", "text/plain")

    def do_GET(self) -> None:
        if self.path.split("?")[0] in ("/api/chat", "/api/health", "/api/stats") and _api(self, "GET"):
            return  # backend API: chimera_core.service (docs/api.md)
        path = self.path.split("?")[0]
        if path == "/api/bench":
            self._send(200, json.dumps(bench_summary()).encode(), "application/json")
        elif self.path == "/api/evals":
            try:
                self._send(200, json.dumps(evallog.api_payload(evallog.load_rows())).encode(), "application/json")
            except Exception as e:  # noqa: BLE001  a bad DB must not kill the page
                self._send(500, json.dumps({"error": type(e).__name__}).encode(), "application/json")
        elif self.path == "/events":
            self._events()
        elif (f := static_file(path)) is not None:
            self._send(200, f.read_bytes(), TYPES.get(f.suffix, mimetypes.guess_type(f.name)[0] or "application/octet-stream"))
        else:
            self._send(404, b"not found", "text/plain")

    def _events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        offset, idle = 0, 0
        try:
            while True:
                events, offset = read_new_events(TELEMETRY, offset)
                for e in events:
                    self.wfile.write(f"data: {json.dumps(e)}\n\n".encode())
                idle = 0 if events else idle + 1
                if not events and idle % 15 == 0:
                    self.wfile.write(b": ping\n\n")  # keep-alive
                self.wfile.flush()
                time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main() -> None:
    port = int(os.environ.get("CHIMERA_PORT") or os.environ.get("HUD_PORT") or "8765")
    ThreadingHTTPServer.request_queue_size = 64  # the default 5 resets bursts of parallel /api/chat calls
    host = os.environ.get("CHIMERA_HOST") or os.environ.get("HUD_HOST") or "127.0.0.1"  # 0.0.0.0 only in a container
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    print(f"CHIMERA on http://127.0.0.1:{port}  (castle, dashboard and API; telemetry: {TELEMETRY})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
