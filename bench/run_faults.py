"""Live failure-mode checks on the product path (config.build_router with chimera.toml): does every call still answer,
with no wrong and no empty answer, when a part breaks?

    tunnel     the SSH tunnel to the GPU box is killed while a 30B call is in flight; then the time until it heals
    hung       the tunnel's ssh is frozen (SIGSTOP) while a 30B call is in flight; the watcher must kill and reopen it
    supabase   CHIMERA_DB_URL points at a closed port, then at an address that never answers: no cache, calls answer
    neo4j      CHIMERA_GRAPH_URL points at a closed port, then at an address that never answers: no graph, calls answer
    ratelimit  the 763B sits behind a local proxy that answers 429 (or 429 then 503) before passing the call to Crusoe

    .venv/bin/python bench/run_faults.py tunnel hung supabase neo4j ratelimit
Needs scripts/gpu_tunnel_keep.sh running (make gpu-keep) for tunnel and hung, plus the usual .env names. No Modal.
Rows: bench/.scratch/backend_v3/faults.jsonl, one per call; a rerun skips done rows. Own tenant, purged at the end.
The "never answers" address is 192.0.2.1 (TEST-NET-1, RFC 5737: reserved for documentation, routes nowhere).
"""
from __future__ import annotations

import http.server
import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import conftest  # noqa: E402,F401
from chimera_core.config import build_router, load_config, load_env  # noqa: E402

OUT = ROOT / "bench/.scratch/backend_v3/faults.jsonl"
TENANT = "bench-faults"
CRUSOE = "https://api.inference.crusoecloud.com"
BLACKHOLE = "192.0.2.1"
SHORT = [("What is the capital of Japan? One word.", ["tokyo"]), ("What is 17 times 3? Reply with the number only.", ["51"]),
         ("Which Python keyword defines a function? One word.", ["def"])]
LONG = ("Write a Python function merge_intervals(intervals) that merges overlapping [start, end] pairs and returns them "
        "sorted. Give a docstring, then explain the method in 6 short bullet points.", ["def merge_intervals"])
ENV = {"supabase": {"refused": {"CHIMERA_DB_URL": "postgresql://chimera@127.0.0.1:1/none"},
                    "no_answer": {"CHIMERA_DB_URL": f"postgresql://chimera@{BLACKHOLE}:5432/none?connect_timeout=5"}},
       "neo4j": {"refused": {"CHIMERA_GRAPH_URL": "neo4j://127.0.0.1:1"},
                 "no_answer": {"CHIMERA_GRAPH_URL": f"neo4j://{BLACKHOLE}:7687"},
                 # the same after the 60 s graph cooldown in memory.py (043ccc4): only the first call should wait
                 "no_answer_after_fix": {"CHIMERA_GRAPH_URL": f"neo4j://{BLACKHOLE}:7687"}}}


def done() -> set[tuple]:
    rows = [json.loads(x) for x in OUT.read_text().splitlines()] if OUT.exists() else []
    return {(r["case"], r["variant"], r["i"]) for r in rows}


def add(rec: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
    print(json.dumps(rec), flush=True)


def router(tiers_patch=None):
    cfg = load_config()
    cfg.cache.tenant = TENANT
    if tiers_patch:
        cfg.tiers = tiers_patch(cfg.tiers)
    r = build_router(cfg)
    r.cfg = r.cfg.model_copy(update={"namespace": f"faults-{uuid.uuid4().hex[:8]}"})  # fresh: no cache hits
    return r


def ask(r, q: str, expect: list[str], **extra) -> dict:
    t0 = time.perf_counter()
    text, tel, err = "", None, ""
    try:
        res = r.generate(q)
        text, tel = res.text, res.telemetry
    except Exception as e:  # noqa: BLE001
        err = type(e).__name__
    calls = [{"tier": e.get("tier"), "ok": e.get("ok"), "error": e.get("error"), "ms": e.get("ms")}
             for e in (tel.events if tel else []) if e["step"] == "call"]
    mem = [e.get("ms") for e in (tel.events if tel else []) if e["step"] == "memory" and e.get("op") == "retrieve"]
    shared = next((e for e in (tel.events if tel else []) if e["step"] == "cache_shared"), {})
    return {**extra, "tier": tel.tier_name if tel else "failed", "ms": round((time.perf_counter() - t0) * 1000),
            "empty": not text.strip(), "right": any(x in text.lower() for x in expect) if text else False,
            "calls": calls, "memory_ms": mem[0] if mem else None, "cache_status": shared.get("status"),
            "cache_ms": shared.get("ms"), "error": err}


def cleanup(r) -> None:
    """Drop this run's cache rows (own tenant) once the background writes are done."""
    if r.shared is not None:
        r.shared.flush()
        print("purged", r.shared.purge(), "cache rows", flush=True)


# ---- tunnel -------------------------------------------------------------------------------------------------
def tunnel_pid() -> int | None:
    w = subprocess.run(["pgrep", "-f", "gpu_tunnel_keep.sh"], capture_output=True, text=True).stdout.split()
    for p in w:
        kids = subprocess.run(["pgrep", "-P", p, "ssh"], capture_output=True, text=True).stdout.split()
        if kids:
            return int(kids[0])
    return None


def gpu_up() -> bool:
    try:
        with urllib.request.urlopen(os.environ["CHIMERA_GPU_URL"].rstrip("/") + "/api/tags", timeout=3) as x:
            return x.status == 200
    except Exception:  # noqa: BLE001
        return False


def heal_wait(t_fault: float, limit: float = 120) -> float | None:
    while time.time() - t_fault < limit:
        if gpu_up():
            return round(time.time() - t_fault, 1)
        time.sleep(0.5)
    return None


def tunnel(variant: str, reps: int = 3) -> None:
    sig = signal.SIGTERM if variant == "killed" else signal.SIGSTOP
    case = "tunnel" if variant == "killed" else "hung"
    for i in range(reps):
        if (case, variant, i) in done():
            continue
        while not gpu_up():
            time.sleep(1)
        r = router()
        pid0, box = tunnel_pid(), {}
        if pid0 is None:
            raise SystemExit("no tunnel watcher running: start make gpu-keep")
        th = threading.Thread(target=lambda: box.update(ask(r, f"{LONG[0]} (run {uuid.uuid4().hex[:6]})", LONG[1])))
        th.start()
        time.sleep(2.0)  # the 30B call is in flight (it takes about 5 s on the tuned server)
        t_fault = time.time()
        os.kill(pid0, sig)
        th.join(timeout=300)
        healed = heal_wait(t_fault)
        pid1 = tunnel_pid()
        if sig == signal.SIGSTOP:
            try:
                os.kill(pid0, signal.SIGCONT)  # safety: never leave a frozen ssh behind (the watcher killed it already)
            except ProcessLookupError:
                pass
        time.sleep(16)  # past the pool's 15 s health ttl: the 30B is probed again
        after = ask(r, SHORT[i % 3][0] + f" (after {uuid.uuid4().hex[:6]})", SHORT[i % 3][1])
        add({"case": case, "variant": variant, "i": i, **box, "heal_s": healed, "new_tunnel": pid1 not in (None, pid0),
             "next_call": {k: after[k] for k in ("tier", "ms", "right", "empty", "error")}})
        cleanup(r)


# ---- supabase / neo4j down: a child process with the broken env, so nothing leaks into this one ----------------
def env_case(case: str, reps: int = 3) -> None:
    for variant, env in ENV[case].items():
        if all((case, variant, i) in done() for i in range(reps)):
            continue
        subprocess.run([sys.executable, __file__, "_env", case, variant, str(reps)], env={**os.environ, **env},
                       cwd=ROOT, check=True)


def _env(case: str, variant: str, reps: int) -> None:
    r = router()
    for i in range(reps):
        if (case, variant, i) in done():
            continue
        q, exp = SHORT[i % 3]
        add({"case": case, "variant": variant, "i": i, **ask(r, f"{q} (run {uuid.uuid4().hex[:6]})", exp)})
    if case != "supabase":
        cleanup(r)


# ---- 763B 429 -------------------------------------------------------------------------------------------------
class Proxy(http.server.BaseHTTPRequestHandler):
    plan: list[int] = []
    seen: list[int] = []

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):  # the pool's health probe (/v1/models)
        self._send(200, b'{"data": []}')

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        if Proxy.plan:
            code = Proxy.plan.pop(0)
            Proxy.seen.append(code)
            return self._send(code, b'{"error": "rate limited"}', {"Retry-After": "1"} if code == 429 else {})
        req = urllib.request.Request(CRUSOE + self.path, data=body, headers={
            "Content-Type": "application/json", "User-Agent": "chimera/0.1", "Authorization": self.headers["Authorization"]})
        with urllib.request.urlopen(req, timeout=120) as x:  # noqa: S310 (fixed Crusoe URL)
            data = x.read()
        Proxy.seen.append(200)
        self._send(200, data)

    def _send(self, code: int, data: bytes, hdr: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        for k, v in (hdr or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def ratelimit() -> None:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    # only the 763B, behind the proxy: the answer must come from it, after the retries
    top_only = lambda ts: [t.model_copy(update={"url": url}) for t in ts if t.name == "cloud-deepseek"]  # noqa: E731
    # per call: the codes the proxy sends before it passes the call on. storm_then_ok: 3 x 429, then Crusoe is fine again
    plans = {"429_once": [[429], [429]], "429_then_503": [[429, 503]] * 2, "429_x3": [[429] * 3] * 2,
             "storm_then_ok": [[429] * 3, []]}
    r = router(top_only)
    for variant, per_call in plans.items():
        for i, plan in enumerate(per_call):
            if ("ratelimit", variant, i) in done():
                continue
            Proxy.plan, Proxy.seen = list(plan), []
            q, exp = SHORT[i % 3]
            add({"case": "ratelimit", "variant": variant, "i": i, **ask(r, f"{q} (run {uuid.uuid4().hex[:6]})", exp),
                 "upstream": list(Proxy.seen)})
    cleanup(r)
    srv.shutdown()


if __name__ == "__main__":
    load_env()
    if sys.argv[1] == "_env":
        _env(sys.argv[2], sys.argv[3], int(sys.argv[4]))
        sys.exit(0)
    for c in sys.argv[1:]:
        {"tunnel": lambda: tunnel("killed"), "hung": lambda: tunnel("frozen", 2), "supabase": lambda: env_case("supabase"),
         "neo4j": lambda: env_case("neo4j"), "ratelimit": ratelimit}[c]()
