"""Speculative decoding across Modal boxes: drafters on L40S ("local machine"), a big verifier on H200s ("server").

One job = one `modal run` = one EPHEMERAL app with the job's own name (chimera-spec-<job>). Never `modal deploy` it.
Run it through the driver, which sets the job's env, stops the app by ID when the run ends (also on failure) and saves
`modal app list` as proof:

  python bench/run_spec_modal.py job smoke         # cheap: 30B as the "big" model on one L40S, 3 prompts
  python bench/run_spec_modal.py job qa_235b       # Phase A, see JOBS in deploy/modal/spec_models.py

Every GPU class scales down after 2 idle minutes. The big box (max 1 container) serves /verify, /generate, /margin,
/stats, /health and /switch (restart its vLLM with another same-box speculative setting, so one cold start covers
several modes). Drafter boxes run the loop in bench/spec_modal_core.py next to their own vLLM; each verify crosses
Modal's public HTTPS edge, like a laptop calling a server. Weights come from the family volumes (spec_models.py).
"""
import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time

import modal

_here = pathlib.Path(__file__).resolve().parent
_repo = _here.parents[1] if len(_here.parents) > 1 else _here  # in the container this file sits in /root
sys.path[:0] = [str(_here), str(_repo / "bench")]
import spec_modal_core as core  # noqa: E402
from spec_models import DRAFTERS, FAMILIES, JOBS, MODELS, MODES, family, path  # noqa: E402

MINUTES = 60
IDLE = 2 * MINUTES  # user rule: a box that waits 2 minutes is turned off
JOB = os.environ.get("SPEC_JOB", "smoke")
CFG = JOBS[JOB]
BIG = CFG["big"]
GPU = [CFG["gpu"], *CFG.get("gpu_fallback", [])]  # Modal tries these in order when the first is short of capacity
# Every box of a job runs in one broad region (Modal bills 1.15x for it). Unpinned, the first try put the drafter in
# eu-west and the big box in ap-southeast; every call also goes through Modal's us-east router, so one bare call took
# about 330 ms. The router stays us-east, so "us" keeps both legs short.
REGION = os.environ.get("SPEC_REGION", "us")

app = modal.App(CFG["app"])
VOLS = {f"/w/{f}": modal.Volume.from_name(c["volume"], create_if_missing=True, version=2) for f, c in FAMILIES.items()}
VOLS["/vllm-cache"] = modal.Volume.from_name("chimera-spec-vllm-cache", create_if_missing=True, version=2)
token = modal.Secret.from_name("chimera-spec-token")  # own secret (SPEC_TOKEN); guards the big box's endpoints
image = (
    modal.Image.from_registry("vllm/vllm-openai:v0.33.0")  # the image the other tiers already start on
    .entrypoint([])
    .run_commands("ln -sf $(command -v python3) /usr/local/bin/python")
    .env({"VLLM_CACHE_ROOT": "/vllm-cache", "TRITON_CACHE_DIR": "/vllm-cache/triton", "SPEC_JOB": JOB})
)
if modal.is_local():
    image = (image.add_local_file(_repo / "bench" / "spec_modal_core.py", "/root/spec_modal_core.py")
             .add_local_file(_here / "spec_models.py", "/root/spec_models.py")
             .add_local_file(_repo / "packages" / "chimera-core" / "inference" / "specplus.py", "/root/specplus.py"))


# ---------- one vLLM server per box ----------
def spec_flags(mode: str) -> list[str]:
    cfg = MODES[mode]
    if not cfg:
        return []
    cfg = {**cfg, **({"model": path(cfg["model"])} if "model" in cfg else {})}
    return ["--speculative-config", json.dumps(cfg)]


def start_vllm(key: str, mode: str, tp: int, util: float, extra=()):
    cmd = ["vllm", "serve", path(key), "--served-model-name", key, "--host", "127.0.0.1", "--port", "8000", *extra,
           "--tensor-parallel-size", str(tp), "--max-model-len", "4096", "--max-num-seqs", "8",
           "--gpu-memory-utilization", str(util), "--enable-prefix-caching", "--max-logprobs", "5",
           "--enable-scale-out",  # registers /inference/v1/generate (token ids in and out) in v0.33.0
           "--generation-config", "vllm",  # no repo sampling defaults (the 480B ships repetition_penalty 1.05)
           *MODELS[key].get("flags", []), *spec_flags(mode)]
    print("vllm:", " ".join(cmd), flush=True)
    return subprocess.Popen(cmd, start_new_session=True)


def wait_ready(proc, limit=40 * MINUTES) -> float:
    import httpx

    t0 = time.time()
    while time.time() - t0 < limit:
        if proc.poll() is not None:
            raise RuntimeError(f"vllm exited with code {proc.returncode}")
        try:
            if httpx.get("http://127.0.0.1:8000/health", timeout=3).status_code == 200:
                return time.time() - t0
        except Exception:  # noqa: BLE001
            pass
        time.sleep(3)
    raise RuntimeError("vllm did not become healthy")


def stop_vllm(proc) -> None:
    """Kill the server and its worker processes, then wait until the GPUs are free again."""
    if proc is not None and proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(90)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(30)
    for _ in range(90):
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True).stdout.split()
        if out and max(int(x) for x in out) < 2048:
            return
        time.sleep(2)
    raise RuntimeError("GPU memory was not released after stopping vLLM")


def tokenizer(key: str):
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(path(key))


def encode(tok, key: str, messages) -> list[int]:
    """Chat template as text, then tokens without extra specials (the template already holds BOS where needed)."""
    text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, **family(key)["chat"])
    return tok(text, add_special_tokens=False)["input_ids"]


def test_ids(tok, key):
    return encode(tok, key, [{"role": "user", "content": "Write a Python function fib(n) that returns the n-th "
                                                          "Fibonacci number, with a docstring."}])


# ---------- the big model (server) ----------
@app.cls(image=image, gpu=GPU if len(GPU) > 1 else GPU[0], volumes=VOLS, secrets=[token], min_containers=0, max_containers=1,
         cpu=8.0, memory=65536,
         scaledown_window=IDLE, timeout=4 * 60 * MINUTES, region=REGION)
@modal.concurrent(max_inputs=16)
class Big:
    @modal.enter()
    def boot(self):
        self.t_enter, self.proc, self.mode, self.state, self.starts = time.time(), None, None, "booting", []
        self.gpus = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                   capture_output=True, text=True).stdout.strip().splitlines()
        self.tok = tokenizer(CFG["tok"])
        self.v = core.VLLM(BIG, stop=family(BIG)["eos"])
        self._start("plain")

    def _start(self, mode):
        self.state, self.mode = "starting", None  # a failed start leaves mode None, so the next switch restarts
        stop_vllm(self.proc)
        t0 = time.time()
        tp = len(self.gpus)  # tensor parallel over every GPU this box got (the fallback may have more, smaller GPUs)
        # FP8 block quantization needs each MoE shard to be a multiple of 128; past that, split experts instead
        moe = {"q3c_480b": 2560, "q3_235b": 1536, "q35_397b": 1024}.get(BIG)
        ep = ["--enable-expert-parallel"] if moe and (moe // tp) % 128 else []
        self.proc = start_vllm(BIG, mode, tp, 0.92, ep)
        ready = wait_ready(self.proc)
        self.v.fast, self.v.transport = False, "tito"
        ids = test_ids(self.tok, CFG["tok"])
        st = self.v.selftest(ids) if mode == "plain" else {}
        if mode != "plain":
            self.v.pick_transport(ids)
        warm_s = self.v.warmup(ids, verify=mode == "plain")
        for i, n in enumerate((48, 160, 400)):  # longer decodes: the verify shapes of vLLM's own spec modes
            self.v.call((ids * 20)[:n], 48, f"warm-long-{i}")
        self.mode, self.state = mode, "ready"
        self.starts.append({"mode": mode, "vllm_ready_s": round(ready, 1), "start_s": round(time.time() - t0, 1),
                            "warmup_s": round(warm_s, 1), "selftest": st, "at": time.time()})
        print("big ready:", json.dumps(self.starts[-1]), flush=True)

    @modal.asgi_app()
    def api(self):
        import httpx
        from fastapi import Depends, FastAPI, Header, HTTPException

        web, key = FastAPI(), os.environ["SPEC_TOKEN"]
        lock = threading.Lock()

        def auth(authorization: str = Header(default="")):
            if authorization != f"Bearer {key}":
                raise HTTPException(401)

        def ready():
            if self.state != "ready":
                raise HTTPException(503, f"big model is {self.state}")

        def timed(fn):
            t0 = time.perf_counter()
            out = fn()
            return out, (time.perf_counter() - t0) * 1e3

        @web.get("/ping")
        def ping():
            return {}

        @web.get("/health")
        def health():
            return {"model": MODELS[BIG]["repo"], "gpu": CFG["gpu"], "gpus_seen": self.gpus, "mode": self.mode,
                    "state": self.state, "where": where(), "fallback_errors": self.v.fallback_errors,
                    "transport": self.v.transport, "fast_verify": self.v.fast, "fast_fallbacks": self.v.fallbacks,
                    "container_up_s": round(time.time() - self.t_enter, 1), "starts": self.starts}

        @web.post("/switch", dependencies=[Depends(auth)])
        def switch(b: dict):
            with lock:
                if b["mode"] != self.mode or self.state != "ready":
                    try:
                        self._start(b["mode"])
                    except Exception as e:  # noqa: BLE001
                        self.state = f"failed: {e!r}"[:300]
                        raise HTTPException(500, self.state) from e
            return self.starts[-1]

        @web.post("/verify", dependencies=[Depends(auth)])
        def verify(b: dict):
            ready()
            (m, nxt, info), ms = timed(lambda: self.v.verify_info(b["ctx"], b["draft"], b["salt"]))
            return {"m": m, "next": nxt, "server_ms": ms, **info}

        @web.post("/generate", dependencies=[Depends(auth)])
        def generate(b: dict):
            ready()
            ids, ms = timed(lambda: self.v.gen(b["ctx"], b["max_tokens"], b["salt"]))
            return {"ids": ids, "server_ms": ms}

        @web.post("/margin", dependencies=[Depends(auth)])
        def margin(b: dict):
            ready()
            return {"top2": self.v.top2(b["ctx"], b["salt"])}

        @web.post("/rescore", dependencies=[Depends(auth)])
        def rescore(b: dict):
            ready()
            return self.v.rescore(b["prompt_ids"], b["out"], b["salt"])

        @web.get("/stats", dependencies=[Depends(auth)])
        def stats():  # vLLM's own speculative-decoding counters, summed over labels
            out = {}
            for line in httpx.get("http://127.0.0.1:8000/metrics", timeout=10).text.splitlines():
                if line.startswith("vllm:spec_decode"):
                    try:
                        name, val = line.split("{")[0].split(" ")[0], float(line.rsplit(" ", 1)[1])
                    except ValueError:
                        continue
                    out[name] = out.get(name, 0.0) + val
            return out

        return web


# ---------- drafter boxes (the "local machine") ----------
@app.cls(image=image, gpu="L40S", volumes=VOLS, secrets=[token], min_containers=0, max_containers=1,
         cpu=4.0, memory=32768,
         scaledown_window=IDLE, timeout=3 * 60 * MINUTES, region=REGION)
@modal.concurrent(max_inputs=4)
class Draft:
    drafter: str = modal.parameter()

    @modal.enter()
    def boot(self):
        t0 = time.time()
        d = DRAFTERS[self.drafter]
        gpus = int(d["gpu"].split(":")[1]) if ":" in d["gpu"] else 1
        self.proc = start_vllm(d["model"], d["mode"], gpus, 0.92)
        self.vllm_ready_s = wait_ready(self.proc)
        self.v = core.VLLM(d["model"], stop=family(d["model"])["eos"])
        self.toks = {}
        ids = test_ids(self.tok(CFG["tok"]), CFG["tok"])
        self.v.pick_transport(ids)
        self.warm_s = self.v.warmup(ids, verify=False)
        self.boot_s = time.time() - t0

    def tok(self, key):
        if key not in self.toks:
            self.toks[key] = tokenizer(key)
        return self.toks[key]

    @modal.method()
    def info(self):
        return {"drafter": self.drafter, "vllm_ready_s": round(self.vllm_ready_s, 1), "boot_s": round(self.boot_s, 1),
                "warmup_s": round(self.warm_s, 1), "transport": self.v.transport, "where": where()}

    @modal.method()
    def run(self, prompts, warm, plan, url):
        return run_plan(prompts, warm, plan, url, self.tok(CFG["tok"]), self.v)


NEAR = {}  # filled by main() with the big box's own region, so every other box runs next to it


def draft_for(key):
    """The drafter box for this key, in the big box's region; with_options also sets the GPU when a drafter needs
    more than one L40S."""
    gpu = DRAFTERS[key]["gpu"]
    opts = {**({"gpu": gpu} if gpu != "L40S" else {}), **({"region": NEAR["region"]} if NEAR.get("region") else {})}
    return (Draft.with_options(**opts) if opts else Draft)(drafter=key)


def client_fn():
    return client.with_options(region=NEAR["region"]) if NEAR.get("region") else client


@app.function(image=image, secrets=[token], cpu=1, memory=1024, timeout=60 * MINUTES, scaledown_window=IDLE,
              region=REGION)
def switch_mode(url, mode):
    """Restart the big box's vLLM with another same-box mode (the bearer token stays inside Modal)."""
    r = big_client(url).post("/switch", json={"mode": mode}, timeout=None)
    r.raise_for_status()
    return r.json()


@app.function(image=image, volumes=VOLS, secrets=[token], cpu=2, memory=4096, timeout=2 * 60 * MINUTES,
              scaledown_window=IDLE, region=REGION)
def client(prompts, warm, plan, url):
    """CPU-only client for big-alone runs and the near-tie check (no drafter GPU)."""
    if plan["mode"] == "margins":
        cli = big_client(url)
        return [{**it, "top2": cli.post("/margin", json={"ctx": it["ctx"], "salt": f"margin:{i}"}).json()["top2"]}
                for i, it in enumerate(prompts)]
    if plan["mode"] == "rescore":
        cli = big_client(url)
        return [{"id": it["id"], **cli.post("/rescore", json={"prompt_ids": it["prompt_ids"], "out": it["out"],
                                                             "salt": f"rescore:{i}"}).json()}
                for i, it in enumerate(prompts)]
    return run_plan(prompts, warm, plan, url, tokenizer(CFG["tok"]), None)


def big_client(url):
    import httpx

    hdr = {"Authorization": f"Bearer {os.environ['SPEC_TOKEN']}"}
    return httpx.Client(base_url=url, headers=hdr, timeout=httpx.Timeout(140, connect=30), follow_redirects=True,
                        max_redirects=12)


def run_plan(prompts, warm, plan, url, tok, local):
    """plan: name, mode (draft_alone | big_alone | spec), max_tokens, k, adaptive, pipeline, free, extra_rtt_ms."""
    import specplus

    cli, mt, mode, name = big_client(url), plan["max_tokens"], plan["mode"], plan["name"]
    extra = plan.get("extra_rtt_ms", 0) / 1e3
    eos = set(family(CFG["tok"])["eos"])
    rtt, srv, trace = [], [], []  # trace: one row per verify round, see TRACE_COLS

    def verify(ctx, d, salt):
        t0 = time.perf_counter()
        if extra:
            time.sleep(extra)  # emulated extra network delay, counted in the round trip
        r = cli.post("/verify", json={"ctx": ctx, "draft": d, "salt": salt})
        r.raise_for_status()
        j = r.json()
        rtt.append((time.perf_counter() - t0) * 1e3)
        srv.append(j["server_ms"])
        trace.append([len(ctx), len(d), j["m"], round(j["server_ms"], 1), round(rtt[-1], 1), j.get("hit"),
                      int(bool(j.get("fb")))])
        return j["m"], j["next"]

    def one(p, tag):
        ids = encode(tok, CFG["tok"], p["messages"])
        salt = f"{name}:{tag}:{p['id']}"  # every run starts every prompt cold; rounds reuse their own cache only
        rec = {"id": p["id"], "kind": p.get("kind", ""), "prompt_ids": ids}
        t0 = time.perf_counter()
        if mode == "draft_alone":
            out = local.gen(ids, mt, salt)
        elif mode == "big_alone":
            r = cli.post("/generate", json={"ctx": ids, "max_tokens": mt, "salt": salt})
            r.raise_for_status()
            out, rec["server_ms"] = r.json()["ids"], r.json()["server_ms"]
        else:
            fd = specplus.FreeDrafter(n=3, m=8)
            out, st = core.spec_generate(
                lambda c, k: local.gen(c, k, salt), lambda c, d: verify(c, d, salt), ids, mt, k=plan.get("k", 4),
                eos=eos, choose=core.make_choose(specplus.choose_k) if plan.get("adaptive") else None,
                pipeline=plan.get("pipeline", False), free=(lambda c: fd.propose(c, 1)) if plan.get("free") else None)
            rec.update({k: getattr(st, k) for k in ("rounds", "drafted", "accepted", "misses", "free_drafted",
                                                    "free_accepted", "reused", "draft_ms", "verify_ms", "ks")})
        rec.update(wall_s=time.perf_counter() - t0, out=out)
        return rec

    stats0 = cli.get("/stats").json()
    for p in warm:  # warm-up prompts are not in the measured set
        one(p, "warm")
    pings = []  # bare transport cost of one call to the big box (no model work)
    for _ in range(20):
        t0 = time.perf_counter()
        cli.get("/ping")
        pings.append((time.perf_counter() - t0) * 1e3)
    rtt.clear()
    srv.clear()
    trace.clear()
    stats1 = cli.get("/stats").json()
    t_run = time.time()
    rows = [one(p, "run") for p in prompts]
    stats2 = cli.get("/stats").json()
    for r in rows:
        r["text"] = tok.decode(r["out"])
    return {"rows": rows, "rtt_ms": rtt, "server_ms": srv, "trace": trace, "trace_cols": TRACE_COLS,
            "t_run": t_run, "t_end": time.time(), "ping_ms": pings,
            "client_where": where(), "spec_counters": {"warm_delta": _delta(stats0, stats1), "run_delta": _delta(stats1, stats2)}}


def where():
    """Region and cloud of this container (explains the round trip between boxes)."""
    return {k: os.environ.get(k) for k in ("MODAL_REGION", "MODAL_CLOUD_PROVIDER")}


def _delta(a, b):
    return {k: b[k] - a.get(k, 0.0) for k in b}


TRACE_COLS = ["n_ctx", "n_draft", "accepted", "server_ms", "round_trip_ms", "cache_hit", "fallback"]


def mismatches(out_dir, base, names):
    """Runs whose output differs from the big model alone: the context up to the first difference."""
    eos = family(CFG["tok"])["eos"]
    if not (out_dir / f"{base}.json").exists():
        print(f"no {base}.json: near-tie check skipped", flush=True)
        return []
    b = {r["id"]: r for r in json.loads((out_dir / f"{base}.json").read_text())["rows"]}
    items = []
    for n in names:
        f = out_dir / f"{n}.json"
        if not f.exists():
            continue
        for r in json.loads(f.read_text())["rows"]:
            ref = b.get(r["id"])
            i = core.first_diff(r["out"], ref["out"], eos) if ref else -1
            if 0 <= i < min(len(core.strip_eos(r["out"], eos)), len(core.strip_eos(ref["out"], eos))):
                items.append({"run": n, "id": r["id"], "pos": i, "other_tok": r["out"][i], "big_tok": ref["out"][i],
                              "ctx": ref["prompt_ids"] + ref["out"][:i]})
    return items


class Pinger(threading.Thread):
    """Calls fn every `every` seconds until stopped: keeps the big box (or the next drafter) from idling out."""

    def __init__(self, fn, every):
        super().__init__(daemon=True)
        self.fn, self.every, self.stop = fn, every, threading.Event()

    def run(self):
        while not self.stop.wait(self.every):
            try:
                self.fn()
            except Exception:  # noqa: BLE001
                pass


@app.local_entrypoint()
def main():
    import httpx

    out = _repo / "bench" / ".scratch" / "spec_modal"
    ps = json.loads((out / "prompts.json").read_text())
    prompts, warm = ps["prompts"], ps["warm"]
    if CFG.get("subset"):
        prompts = [p for p in prompts if p["kind"] == CFG["subset"]]
    prompts = prompts[: CFG.get("n_prompts", len(prompts))]
    mt = CFG.get("max_tokens", 256)
    plans = [{"max_tokens": mt, "k": 4, **p} for p in CFG["plans"]]
    t0 = time.time()
    meta = {"job": JOB, "app": CFG["app"], "big": BIG, "gpu": GPU, "region": REGION, "t0": t0, "plans": [],
            "drafters": {}}
    warmers = {}

    def warm_drafter(key):  # boot the drafter box while something else runs, and keep it from idling out
        if key and key not in warmers:
            d = draft_for(key)
            d.info.spawn()
            warmers[key] = Pinger(lambda: d.info.remote(), 60)
            warmers[key].start()

    todo = [p for p in plans if p["mode"] == "switch" or not (out / f"{p['name']}.json").exists()]
    first = next((p["drafter"] for p in todo if p.get("drafter")), None)
    if not any(p["mode"] != "switch" for p in todo):
        print("nothing to do: every plan of this job has a result file", flush=True)
        return
    url = Big().api.get_web_url()
    with httpx.Client(follow_redirects=True, max_redirects=20, timeout=httpx.Timeout(200, connect=60)) as h:
        r = h.get(url + "/health")
        r.raise_for_status()
        meta["big_first_health_s"] = round(time.time() - t0, 1)
        meta["big_health"] = r.json()
    print("big up:", json.dumps(meta["big_health"]), flush=True)
    # every other box goes to the big box's region (account C's first job put the client in us-east and the big box
    # in us-west: 93 ms per bare call instead of 46 ms); the first drafter boots during big alone and the rescore
    NEAR["region"] = (meta["big_health"].get("where") or {}).get("MODAL_REGION")
    meta["near_region"] = NEAR["region"]
    warm_drafter(first)
    keep = Pinger(lambda: httpx.get(url + "/health", timeout=60, follow_redirects=True), 30)
    keep.start()
    failures, required, current, failed_modes, failed_drafters = 0, "plain", "plain", set(), set()
    meta["switches"] = []

    def save_meta():
        (out / f"meta_{JOB}.json").write_text(json.dumps({**meta, "t_end": time.time(), "failures": failures}))

    try:
        for i, plan in enumerate(plans):
            if plan["mode"] == "switch":  # sets the big box mode the plans below need; switched lazily
                required = plan["to"]
                continue
            f = out / f"{plan['name']}.json"
            if f.exists():
                print("skip (done):", f.name, flush=True)
                continue
            if required in failed_modes:
                print(f"skip ({required} did not start):", plan["name"], flush=True)
                continue
            if plan.get("drafter") in failed_drafters:  # one failed boot is enough: do not pay for it again
                print(f"skip (drafter {plan['drafter']} did not start):", plan["name"], flush=True)
                continue
            block = []  # the plans still to run in this mode block, for pre-warming the next drafter
            for p in plans[i + 1:]:
                if p["mode"] == "switch":
                    break
                if p.get("drafter") and not (out / f"{p['name']}.json").exists():
                    block.append(p["drafter"])
            nxt = next((d for d in block if d != plan.get("drafter")), None)
            t1 = time.time()
            try:
                if current != required:
                    if plan.get("drafter"):
                        warm_drafter(plan["drafter"])  # its boot overlaps the big box's restart
                    current = None
                    try:
                        st = switch_mode.remote(url, required)
                    except Exception:
                        failed_modes.add(required)
                        raise
                    current = required
                    meta["switches"].append({"mode": required, "s": round(time.time() - t1, 1), "start": st})
                    print(f"big box now in mode {required} after {time.time() - t1:.0f} s", flush=True)
                    t1 = time.time()
                if plan["mode"] == "margins":
                    items = mismatches(out, plan["base"], plan["runs"])
                    res = {"rows": client_fn().remote(items, [], plan, url) if items else []}
                elif plan["mode"] == "rescore":  # the big model's own answers, scored again in one pass
                    base_rows = json.loads((out / f"{plan['base']}.json").read_text())["rows"]
                    res = {"rows": client_fn().remote(base_rows, [], plan, url)}
                elif plan.get("drafter"):
                    warm_drafter(plan["drafter"])
                    if nxt and os.environ.get("SPEC_PREWARM", "1") == "1":
                        warm_drafter(nxt)  # the next drafter boots while this plan runs (one more L40S for a while)
                    d = draft_for(plan["drafter"])
                    if plan["drafter"] not in meta["drafters"]:
                        try:
                            meta["drafters"][plan["drafter"]] = {"first_use": time.time(), **d.info.remote()}
                        except Exception:
                            failed_drafters.add(plan["drafter"])
                            if plan["drafter"] in warmers:
                                warmers.pop(plan["drafter"]).stop.set()
                            raise
                    res = d.run.remote(prompts, warm, plan, url)
                    meta["drafters"][plan["drafter"]]["last_use"] = time.time()
                    later = [p.get("drafter") for p in plans[i + 1:] if not (out / f"{p['name']}.json").exists()]
                    if plan["drafter"] not in later and plan["drafter"] in warmers:
                        warmers.pop(plan["drafter"]).stop.set()  # done with it: let it scale down
                else:
                    res = client_fn().remote(prompts, warm, plan, url)
            except Exception as e:  # noqa: BLE001
                failures += 1
                (out / f"{plan['name']}.error.json").write_text(json.dumps({"plan": plan, "mode": required,
                                                                            "error": repr(e)[:2000]}))
                print(f"FAILED {plan['name']} (mode {required}): {e!r}"[:800], flush=True)
                save_meta()
                low = repr(e).lower()
                if "spend limit" in low or "is disabled" in low:
                    raise
                if required in failed_modes:
                    continue  # a mode that does not start: skip its plans, carry on with the next mode
                try:
                    hl = httpx.get(url + "/health", timeout=60, follow_redirects=True).json()
                except Exception:  # noqa: BLE001
                    hl = {"state": "unreachable"}
                if hl.get("state") != "ready":
                    raise RuntimeError(f"big box not ready after {plan['name']}: {hl.get('state')}") from e
                continue
            res.update(plan=plan, big_mode=current, elapsed_s=round(time.time() - t1, 1))
            f.write_text(json.dumps(res))
            meta["plans"].append({"name": plan["name"], "t_start": t1, "t_end": time.time()})
            save_meta()
            rows = [r for r in res["rows"] if "out" in r]
            toks, wall = sum(len(r["out"]) for r in rows), sum(r["wall_s"] for r in rows) or 1
            print(f"done {plan['name']}: {len(res['rows'])} rows, {toks / wall:.1f} tok/s, {res['elapsed_s']} s", flush=True)
    finally:
        keep.stop.set()
        for w in warmers.values():
            w.stop.set()
        try:
            meta["health_end"] = httpx.get(url + "/health", timeout=60, follow_redirects=True).json()
        except Exception as e:  # noqa: BLE001
            meta["health_end"] = repr(e)[:200]
        meta.update(t_end=time.time(), failures=failures)
        (out / f"meta_{JOB}.json").write_text(json.dumps(meta))
