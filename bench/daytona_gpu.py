"""One Daytona GPU sandbox at a time, from the Mac: create, run commands, publish a port, delete with proof.

    .venv/bin/python bench/daytona_gpu.py capacity                 # GPU units free per type and count (read-only)
    .venv/bin/python bench/daytona_gpu.py up [--gpu H100,H200] [--n 1] [--cpu 16] [--mem 96] [--disk 300] [--tag 120b]
    .venv/bin/python bench/daytona_gpu.py run "<shell command>" [--timeout 600]
    .venv/bin/python bench/daytona_gpu.py put <local file> <remote path>
    .venv/bin/python bench/daytona_gpu.py publish [--port 8000]   # sets CHIMERA_120B_URL in .env to the preview URL
    .venv/bin/python bench/daytona_gpu.py keep <minutes>          # refresh_activity every 4 min, then exit
    .venv/bin/python bench/daytona_gpu.py down                    # delete, prove with the SDK list and REST, log spend
    .venv/bin/python bench/daytona_gpu.py list                    # every sandbox of the account (proof)

Spend rules (docs/handoff/tier_120b.md): one GPU sandbox at a time, auto-stop 15 min, ephemeral (deleted when it
stops), a wall-clock TTL as the last backstop. The sandbox id, its preview URL and the spend ledger stay in
bench/.scratch/daytona/ (git-ignored). DAYTONA_API_KEY and CHIMERA_120B_KEY come from .env and are never printed.
"""
from __future__ import annotations

import json
import os
import pathlib
import secrets
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import conftest  # noqa: E402,F401
from chimera_core.config import load_env  # noqa: E402

OUT = ROOT / "bench" / ".scratch" / "daytona"
STATE = OUT / "sandbox.json"
ENV = ROOT / ".env"
API = "https://app.daytona.io/api"
IMAGE = "vllm/vllm-openai:v0.33.0"
AUTO_STOP_MIN, TTL_MIN = 15, 360
# $/hour, daytona.io/pricing (2026-11-17), billed per second. GPU rows are listed as the GPU price; the CPU, RAM and
# disk of the sandbox are billed on top.
GPU_RATE = {"H100": 2.47, "H200": 2.87, "B200": 4.30, "B300": 5.17, "RTX-PRO-6000": 1.95, "L40S": 1.14, "MI355X": 3.56}
CPU_RATE, RAM_RATE, DISK_RATE, DISK_FREE = 0.0504, 0.0162, 0.000108, 5


def rate(gpu: str, n: int, cpu: int, mem: int, disk: int) -> float:
    return n * GPU_RATE[gpu] + cpu * CPU_RATE + mem * RAM_RATE + max(0, disk - DISK_FREE) * DISK_RATE


def set_env(name: str, value: str | None) -> None:
    """Set (or with None remove) one line of .env. The value is never printed."""
    lines = [x for x in (ENV.read_text().splitlines() if ENV.exists() else []) if not x.startswith(name + "=")]
    if value is not None:
        lines.append(f"{name}={value}")
    ENV.write_text("\n".join(lines) + "\n")
    os.chmod(ENV, 0o600)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def client():
    from daytona import Daytona, DaytonaConfig

    return Daytona(DaytonaConfig(api_key=os.environ["DAYTONA_API_KEY"]))


def rest(path: str):
    req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + os.environ["DAYTONA_API_KEY"]})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (fixed host)
        return json.load(r)


def state() -> dict:
    if not STATE.exists():
        sys.exit("no sandbox: run `up` first")
    return json.loads(STATE.read_text())


def sandbox():
    return client().get(state()["id"])


def capacity() -> dict:
    org = rest("/api-keys/current")["organizationId"]
    cap = rest(f"/organizations/{org}/gpu-capacity")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"capacity_{time.strftime('%Y%m%d_%H%M%S')}.json").write_text(json.dumps(cap))
    for c in cap["capacity"]:
        free = {s["gpuCount"]: s["onDemand"] for s in c["availableSandboxes"] if s["onDemand"]}
        print(f"{c['gpuType']:>13}: on-demand sandboxes free by GPU count {free or 'none'}")
    return cap


def live(rows=None) -> list[dict]:
    """Sandboxes the REST API lists that are not gone, with the fields the proof needs (no URLs)."""
    rows = rest("/sandbox")["items"] if rows is None else rows
    keep = ("id", "state", "gpu", "gpuType", "labels", "createdAt", "updatedAt")
    return [{k: r.get(k) for k in keep} for r in rows if r.get("state") not in ("destroyed", "deleted")]


def up(gpu: list[str], n: int, cpu: int, mem: int, disk: int, tag: str, image: str) -> None:
    from daytona import CreateSandboxFromImageParams, GpuType, Resources

    if STATE.exists():
        sys.exit(f"a sandbox is already recorded in {STATE.relative_to(ROOT)}: run `down` first (one at a time)")
    if live():
        sys.exit("the account already has a sandbox (REST /sandbox): one at a time, run `list`")
    if not os.environ.get("CHIMERA_120B_KEY"):
        set_env("CHIMERA_120B_KEY", secrets.token_urlsafe(32))
    types = [GpuType(g) for g in gpu]  # values: H100, H200, RTX-PRO-6000, MI355X, ...
    params = CreateSandboxFromImageParams(
        image=image, public=True, ephemeral=True, auto_stop_interval=AUTO_STOP_MIN, ttl_minutes=TTL_MIN,
        labels={"chimera": tag}, env_vars={"CHIMERA_120B_KEY": os.environ["CHIMERA_120B_KEY"]},
        resources=Resources(cpu=cpu, memory=mem, disk=disk, gpu=n, gpu_type=types if len(types) > 1 else types[0]))
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    rec = {"tag": tag, "requested_gpu": gpu, "n": n, "cpu": cpu, "mem": mem, "disk": disk, "image": image,
           "t_create": t0}
    STATE.write_text(json.dumps({**rec, "id": None}))  # a crash during create still leaves a trace to clean up
    try:
        sb = client().create(params, timeout=3600)
    except Exception as e:  # noqa: BLE001
        STATE.unlink()
        left = live()
        print("create failed:", type(e).__name__, str(e)[:500], "| sandboxes left:", left, flush=True)
        raise
    rec["id"] = sb.id
    rec["create_s"] = round(time.time() - t0, 1)
    gpu_out = sb.process.exec("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader", timeout=60).result
    rec["gpus_seen"] = gpu_out.strip().splitlines()
    got = next((g for g in gpu if g.split("-")[0] in gpu_out), gpu[0])  # nvidia-smi: "NVIDIA H100 80GB HBM3"
    rec["gpu"], rec["usd_per_hour"] = got, round(rate(got, n, cpu, mem, disk), 4)
    STATE.write_text(json.dumps(rec))
    print(json.dumps({k: v for k, v in rec.items() if k != "id"}), flush=True)


def run(cmd: str, timeout: int) -> int:
    r = sandbox().process.exec(cmd, timeout=timeout)
    print(r.result, flush=True)
    return int(r.exit_code or 0)


def put(local: str, remote: str) -> None:
    sandbox().fs.upload_file(pathlib.Path(local).read_bytes(), remote)
    print("uploaded", local, "->", remote)


def publish(port: int) -> None:
    link = sandbox().get_preview_link(port)
    set_env("CHIMERA_120B_URL", link.url.rstrip("/"))
    print("CHIMERA_120B_URL set in .env (value not shown)")


def keep(minutes: float) -> None:
    end = time.time() + minutes * 60
    while time.time() < end and STATE.exists():
        try:
            sandbox().refresh_activity()
        except Exception as e:  # noqa: BLE001
            print("refresh failed:", type(e).__name__, flush=True)
        time.sleep(240)


def down() -> int:
    st = json.loads(STATE.read_text()) if STATE.exists() else {}
    c = client()
    t_del = time.time()
    if st.get("id"):
        try:
            c.delete(c.get(st["id"]), timeout=300, wait=True)
        except Exception as e:  # noqa: BLE001  already gone (ephemeral auto-stop) or a transient error: prove below
            print("delete:", type(e).__name__, str(e)[:200], flush=True)
    left = []
    for _ in range(30):
        left = live()
        if not left:
            break
        time.sleep(10)
    sdk = [{"id": s.id, "state": str(s.state)} for s in c.list()]
    proof = {"at": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "rest_live": left, "sdk_list": sdk}
    (OUT / f"proof_down_{time.strftime('%Y%m%d_%H%M%S')}.json").write_text(json.dumps(proof, indent=1))
    print(json.dumps(proof, indent=1), flush=True)
    if st.get("t_create"):
        hours = (t_del - st["t_create"]) / 3600
        usd = round(hours * st.get("usd_per_hour", 0), 4)
        with (OUT / "spend.jsonl").open("a") as fh:
            fh.write(json.dumps({"tag": st.get("tag"), "gpu": st.get("gpu"), "n": st.get("n"),
                                 "usd_per_hour": st.get("usd_per_hour"), "hours": round(hours, 4), "usd": usd,
                                 "created": st["t_create"], "deleted": t_del}) + "\n")
        print(f"sandbox up {hours * 60:.1f} min at ${st.get('usd_per_hour')}/h = ${usd}", flush=True)
    if not left:
        STATE.unlink(missing_ok=True)
        set_env("CHIMERA_120B_URL", None)
    return len(left)


def arg(name: str, default):
    return type(default)(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


if __name__ == "__main__":
    load_env()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "capacity":
        capacity()
    elif cmd == "up":
        up(arg("--gpu", "H100,H200").split(","), arg("--n", 1), arg("--cpu", 16), arg("--mem", 96), arg("--disk", 300),
           arg("--tag", "120b"), arg("--image", IMAGE))
    elif cmd == "run":
        sys.exit(run(sys.argv[2], arg("--timeout", 600)))
    elif cmd == "put":
        put(sys.argv[2], sys.argv[3])
    elif cmd == "publish":
        publish(arg("--port", 8000))
    elif cmd == "keep":
        keep(float(sys.argv[2]))
    elif cmd == "down":
        sys.exit(down())
    else:
        print(json.dumps(live(), indent=1))
