"""Live check: the running web server answers every field the UI reads (docs/api.md).

    .venv/bin/python scripts/check_ui_backend.py [--base http://127.0.0.1:8765] [--prompt "..."]

Sends one /api/chat question, checks the SSE steps arrive in order, then checks /api/stats moved
(session calls +1, tokens_today up or the call was a cache hit) and that each UI field is present and not null.
Prints one line per check and exits 1 on any failure. Prints no keys, DSNs or host names.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request

UI_FIELDS = [  # path in /api/stats -> must exist and not be null
    "session.calls", "session.tokens_today", "session.tokens", "session.hit_rate",
    "session.cache.today.exact", "session.cache.today.cosine", "session.cache.today.false_hits",
    "session.cache.all_time.exact", "session.cache.all_time.cosine", "session.cache.all_time.false_hits",
    "session.by_task", "session.by_conversation", "session.series.hourly", "session.series.daily",
    "session.dollars_saved", "session.tokens_kept_off_big",
    "global.calls", "global.tokens_today", "global.series.daily", "global.by_task",
    "recent", "storage.supabase.up", "storage.supabase.tables.prompts.bytes",
    "storage.supabase.tables.teacher_pairs.tenant_rows", "storage.supabase.tables.mem_nodes.tenant_rows",
    "storage.supabase.tables.mem_edges.tenant_rows", "storage.neo4j.nodes", "storage.neo4j.edges",
]
HEALTH_FIELDS = ["ok", "ram.free_mb", "gpu_tunnel.up", "supabase.up", "crusoe.up", "modal.state"]


def get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path, timeout=60) as r:  # noqa: S310 (local server)
        return json.loads(r.read())


def pick(obj, path: str):
    for k in path.split("."):
        if not isinstance(obj, dict) or k not in obj:
            return KeyError
        obj = obj[k]
    return obj


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--prompt", default=f"In one word: what color is a clear daytime sky? (check {int(time.time())})")
    a = ap.parse_args()
    ok = True

    def check(name: str, cond: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= bool(cond)
        print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))

    health = get(a.base, "/api/health")
    for f in HEALTH_FIELDS:
        v = pick(health, f)
        check(f"health {f}", v is not KeyError and v is not None, f"{v}")
    before = get(a.base, "/api/stats")
    conv = f"check-{int(time.time())}"
    body = json.dumps({"prompt": a.prompt, "conversation_id": conv, "task": "check"}).encode()
    req = urllib.request.Request(a.base + "/api/chat", data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    steps, answer = [], None
    with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310
        ev = None
        for raw in r:
            line = raw.decode().rstrip("\n")
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: ") and ev:
                data = json.loads(line[6:])
                steps.append(ev)
                if ev == "answer":
                    answer = data.get("text")
                if ev == "final":
                    final = data
    secs = time.time() - t0
    print(f"      steps: {' -> '.join(steps)}  ({secs:.1f} s)")
    check("chat ends with answer, done", steps[-2:] == ["answer", "done"] and bool(answer))
    check("chat has cache_shared and final", "cache_shared" in steps and "final" in steps)
    hit = "final" in steps and final.get("cache") is not None
    if not hit:
        check("miss path has memory, decide, call", all(s in steps for s in ("memory", "decide", "call")))
    after = get(a.base, "/api/stats")
    dc = after["session"]["calls"] - before["session"]["calls"]
    dt = after["session"]["tokens_today"] - before["session"]["tokens_today"]
    check("session calls +1", dc == 1, f"+{dc}")
    check("session tokens_today up (or a cache hit)", dt > 0 or hit, f"+{dt}, cache hit={hit}")
    check("by_conversation has this call", pick(after, f"session.by_conversation.{conv}.calls") == 1)
    check("recent[0] is this call", (after["recent"] or [{}])[0].get("conversation_id") == conv)
    for f in UI_FIELDS:
        v = pick(after, f)
        check(f"stats {f}", v is not KeyError and v is not None, "" if isinstance(v, (dict, list)) else f"{v}")
    print("RESULT:", "all checks passed" if ok else "some checks FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
