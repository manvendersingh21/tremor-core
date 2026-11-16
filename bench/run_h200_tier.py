"""Live check of the warm-only H200 30B tier through the real router (cache -> gpu-h200 -> gpu-small -> 763B).

1. With the H200 cold, one call: it must fall through to the next tier at once and start a wake.
2. Wait until the container serves, then N calls: they must be answered by gpu-h200.
3. Stay idle IDLE_S seconds: the container must be gone (scaledown_window=120).
Needs: `make modal-qwen-up` (deploy only, scales to zero), MODAL_QWEN_URL and MODAL_VLLM_TOKEN in .env, chimera.toml with
the gpu-h200 tier. Stop the app after: `make modal-qwen-down` (prints modal app list).
Rows: bench/.scratch/backend_v2/h200_live.jsonl (one per event).  Usage: .venv/bin/python bench/run_h200_tier.py [N]
"""
import json
import pathlib
import sys
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import conftest  # noqa: F401,E402  registers chimera_core

from chimera_core.config import build_router, load_config  # noqa: E402
from chimera_core.tiers import http_probe, modal_running  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 6
IDLE_S = 170
OUT = ROOT / "bench/.scratch/backend_v2/h200_live.jsonl"
OUT.parent.mkdir(parents=True, exist_ok=True)
QS = ["What does a hash map do? One sentence.", "Name the time complexity of binary search. One line.",
      "What is a Python list comprehension? One sentence.", "What does HTTP 404 mean? One line.",
      "What is a mutex for? One sentence.", "What does git stash do? One sentence.",
      "What is a foreign key? One sentence.", "What does `ls -a` show? One line."]
run = uuid.uuid4().hex[:6]
t_start = time.time()


def row(**kw):
    kw["t"] = round(time.time() - t_start, 1)
    print(json.dumps(kw), flush=True)
    with OUT.open("a") as f:
        f.write(json.dumps({"run": run, **kw}) + "\n")


cfg = load_config()
# this check tests the wake, so it turns it on explicitly (the product default is wake = false: never auto-start)
cfg.tiers = [t.model_copy(update={"wake": True}) if t.name == "gpu-h200" else t for t in cfg.tiers]
router = build_router(cfg)
router.cfg = router.cfg.model_copy(update={"namespace": f"bench-h200-{run}"})  # fresh namespace: no cache hits
h200 = next(t for t in cfg.tiers if t.name == "gpu-h200")


def ask(i):
    t0 = time.perf_counter()
    r = router.generate(f"{QS[i % len(QS)]} (check {run}-{i})")
    tel = r.telemetry
    row(step="call", i=i, tier=tel.tier_name, tier_used=tel.tier_used, ms=round((time.perf_counter() - t0) * 1000),
        latency_ms=round(tel.latency_ms), tokens_saved=tel.tokens_saved, dollars_saved=round(tel.dollars_saved, 6),
        alpha=tel.acceptance_rate_alpha, answer=r.text[:80])
    return tel.tier_name


row(step="start", running=modal_running(h200.modal_app))
ask(0)  # cold: falls through, the pool starts a wake in the background
t_wake = time.time()
while not (modal_running(h200.modal_app) and http_probe(h200)):
    if time.time() - t_wake > 1200:
        row(step="warm_timeout")
        sys.exit(1)
    time.sleep(10)
row(step="warm", seconds_to_warm=round(time.time() - t_wake))
time.sleep(16)  # let the pool's health ttl (15 s) run out so its background check sees the warm container
ask(1)          # may still read the old state; it refreshes behind
time.sleep(5)
tiers = [ask(i) for i in range(2, 2 + N)]
row(step="warm_calls", n=N, by_h200=tiers.count("gpu-h200"))
time.sleep(IDLE_S)
row(step="idle", idle_s=IDLE_S, running=modal_running(h200.modal_app))
