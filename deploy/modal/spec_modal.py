"""Speculative decoding across two Modal boxes: a Qwen3 ~30B drafts on an L40S, a Qwen3-235B verifies on H200s.

One job = one `modal run` = one EPHEMERAL app named chimera-spec-modal. Never `modal deploy` this file. The app stops by
itself when the job ends or the client dies; `bench/run_spec_modal.py job NAME` also stops any leftover by its App ID
and saves `modal app list` as proof. Every GPU class scales down after 2 idle minutes (user rule).

  python bench/run_spec_modal.py job download      # CPU only: weights to the Modal volume, never to the Mac
  python bench/run_spec_modal.py job smoke         # 3 prompts, 48 tokens: checks the APIs end to end
  python bench/run_spec_modal.py job cross         # the main runs (see JOBS)

Same family on purpose: every model is Qwen3 (one tokenizer.json, checked by hash). Draft runs the loop
(bench/spec_modal_core.py) next to its own vLLM, so drafting is local and each verify crosses Modal's public HTTPS edge,
like a laptop calling a server. Big serves /verify (reply: accepted count + next token), /generate (big alone),
/margin (top-2 at a position, for the lossless check), /stats (vLLM's own spec-decode counters) and /health.
Own volumes (chimera-spec-hf, chimera-spec-vllm-cache) and own app name: the other chats' apps are never touched.
"""
import json
import os
import pathlib
import subprocess
import sys
import threading
import time

import modal

_here = pathlib.Path(__file__).resolve().parent
_repo = _here.parents[1] if len(_here.parents) > 1 else _here  # in the container this file sits in /root
try:
    import spec_modal_core as core  # container: /root/spec_modal_core.py
except ImportError:
    sys.path.insert(0, str(_repo / "bench"))
    import spec_modal_core as core

MINUTES = 60
IDLE = 2 * MINUTES  # user rule: a GPU that waits 2 minutes is turned off
REPOS = {
    "small": "Qwen/Qwen3-4B-Instruct-2507-FP8",
    "mid": "Qwen/Qwen3-30B-A3B-Instruct-2507-FP8",
    "big": "Qwen/Qwen3-235B-A22B-Instruct-2507-FP8",
    "coder480": "Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8",
    "eagle_big": "RedHatAI/Qwen3-235B-A22B-Instruct-2507-speculator.eagle3",
    "eagle_mid": "RedHatAI/Qwen3-30B-A3B-Instruct-2507-speculator.eagle3",
}
# The Big server's model and its own (same-box) speculative setting are fixed per job by env vars, set by the driver.
BIG_MODEL = os.environ.get("SPEC_BIG_MODEL", "big")
BIG_MODE = os.environ.get("SPEC_BIG_MODE", "plain")
BIG_GPUS = int(os.environ.get("SPEC_BIG_GPUS", "4" if BIG_MODEL == "coder480" else "2"))


def path(key: str) -> str:
    return f"/hf/models/{REPOS[key].split('/')[-1]}"


def spec_cfg(method: str, key: str = "", n: int = 4, **kw) -> list[str]:
    c = {"method": method, "num_speculative_tokens": n, **kw}
    if key:
        c["model"] = path(key)
    return ["--speculative-config", json.dumps(c)]


BIG_EXTRA = {
    "plain": [],
    "ngram": spec_cfg("ngram", n=4, prompt_lookup_min=2, prompt_lookup_max=5),
    "eagle3": spec_cfg("eagle3", "eagle_big", n=3),  # 3 = the head's own setting (its config.json)
    "draft4b": spec_cfg("draft_model", "small", n=4),
    "suffix": spec_cfg("suffix", n=8),
}
DRAFTS = {  # Draft box variants (parameter `model`): which model drafts, and its own same-box helper
    "mid": ("mid", []),
    "small": ("small", []),
    "mid+small": ("mid", spec_cfg("draft_model", "small", n=4)),  # 2-level chain: 4B -> 30B on one L40S, then -> 235B
    "mid+eagle": ("mid", spec_cfg("eagle3", "eagle_mid", n=3)),
}

app = modal.App("chimera-spec-modal")
hf = modal.Volume.from_name("chimera-spec-hf", create_if_missing=True)
vcache = modal.Volume.from_name("chimera-spec-vllm-cache", create_if_missing=True)
token = modal.Secret.from_name("chimera-vllm-token")
image = (
    modal.Image.from_registry("vllm/vllm-openai:v0.33.0")  # the image the other tiers already start on
    .entrypoint([])
    .run_commands("ln -sf $(command -v python3) /usr/local/bin/python")
)
if BIG_MODE == "suffix":  # suffix decoding needs Arctic Inference
    image = image.run_commands("pip install arctic-inference")
image = (
    image.env({"HF_HOME": "/hf", "VLLM_CACHE_ROOT": "/vllm-cache", "VLLM_SERVER_DEV_MODE": "1",
               "SPEC_BIG_MODEL": BIG_MODEL, "SPEC_BIG_MODE": BIG_MODE, "SPEC_BIG_GPUS": str(BIG_GPUS)})
    .add_local_file(_repo / "bench" / "spec_modal_core.py", "/root/spec_modal_core.py")
    .add_local_file(_repo / "packages" / "chimera-core" / "inference" / "specplus.py", "/root/specplus.py")
)


# ---------- one local vLLM server per box ----------
def start_vllm(model_path: str, name: str, extra: list[str], util: float):
    cmd = ["vllm", "serve", model_path, "--served-model-name", name, "--host", "127.0.0.1", "--port", "8000",
           "--max-model-len", "4096", "--max-num-seqs", "8", "--gpu-memory-utilization", str(util),
           "--enable-prefix-caching", "--max-logprobs", "5",
           "--generation-config", "vllm",  # ignore the repo's sampling defaults (the 480B sets repetition_penalty 1.05)
           *extra]
    print("vllm:", " ".join(cmd), flush=True)
    return subprocess.Popen(cmd)


def wait_ready(proc, limit=30 * MINUTES) -> float:
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


def test_ids(tok):
    msg = [{"role": "user", "content": "Write a Python function fib(n) that returns the n-th Fibonacci number."}]
    return tok.apply_chat_template(msg, add_generation_prompt=True, tokenize=True)


# ---------- the big model (server) ----------
@app.cls(image=image, gpu=f"H200:{BIG_GPUS}", volumes={"/hf": hf, "/vllm-cache": vcache}, secrets=[token],
         min_containers=0, scaledown_window=IDLE, timeout=60 * MINUTES)
@modal.concurrent(max_inputs=8)
class Big:
    @modal.enter()
    def boot(self):
        from transformers import AutoTokenizer

        t0 = time.time()
        self.proc = start_vllm(path(BIG_MODEL), "big", ["--tensor-parallel-size", str(BIG_GPUS), *BIG_EXTRA[BIG_MODE]], 0.93)
        self.vllm_s = wait_ready(self.proc)
        self.v = core.VLLM("big")
        self.st = self.v.selftest(test_ids(AutoTokenizer.from_pretrained(path("mid"))))
        self.boot_s = time.time() - t0
        print("selftest:", json.dumps(self.st), flush=True)

    @modal.asgi_app()
    def api(self):
        import httpx
        from fastapi import Depends, FastAPI, Header, HTTPException

        web, key = FastAPI(), os.environ["MODAL_VLLM_TOKEN"]

        def auth(authorization: str = Header(default="")):
            if authorization != f"Bearer {key}":
                raise HTTPException(401)

        def timed(fn):
            t0 = time.perf_counter()
            out = fn()
            return out, (time.perf_counter() - t0) * 1e3

        @web.get("/health")
        def health():
            return {"model": REPOS[BIG_MODEL], "mode": BIG_MODE, "gpus": BIG_GPUS, "vllm_start_s": round(self.vllm_s, 1),
                    "boot_s": round(self.boot_s, 1), "selftest": self.st, "fast_fallbacks": self.v.fallbacks}

        @web.post("/verify", dependencies=[Depends(auth)])
        def verify(b: dict):
            (m, nxt), ms = timed(lambda: self.v.verify(b["ctx"], b["draft"], b["salt"]))
            return {"m": m, "next": nxt, "server_ms": ms}

        @web.post("/generate", dependencies=[Depends(auth)])
        def generate(b: dict):
            ids, ms = timed(lambda: self.v.gen(b["ctx"], b["max_tokens"], b["salt"]))
            return {"ids": ids, "server_ms": ms}

        @web.post("/margin", dependencies=[Depends(auth)])
        def margin(b: dict):
            return {"top2": self.v.top2(b["ctx"], b["salt"])}

        @web.get("/stats", dependencies=[Depends(auth)])
        def stats():  # vLLM's Prometheus counters for its own speculative decoding, summed over labels
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


# ---------- the drafter box (the "local machine") ----------
@app.cls(image=image, gpu="L40S", volumes={"/hf": hf, "/vllm-cache": vcache}, secrets=[token],
         min_containers=0, scaledown_window=IDLE, timeout=60 * MINUTES)
class Draft:
    model: str = modal.parameter(default="mid")

    @modal.enter()
    def boot(self):
        from transformers import AutoTokenizer

        t0 = time.time()
        key, extra = DRAFTS[self.model]
        self.proc = start_vllm(path(key), key, extra, 0.92)
        self.vllm_s = wait_ready(self.proc)
        self.tok = AutoTokenizer.from_pretrained(path("mid"))  # one tokenizer for the whole family
        self.v = core.VLLM(key)
        self.v.pick_transport(test_ids(self.tok))
        self.boot_s = time.time() - t0

    @modal.method()
    def info(self):
        return {"draft": self.model, "vllm_start_s": round(self.vllm_s, 1), "boot_s": round(self.boot_s, 1),
                "transport": self.v.transport}

    @modal.method()
    def run(self, prompts, warm, plan, url):
        return run_plan(prompts, warm, plan, url, self.tok, self.v)


@app.function(image=image, volumes={"/hf": hf}, secrets=[token], cpu=2, memory=4096, timeout=60 * MINUTES,
              scaledown_window=IDLE)
def client(prompts, warm, plan, url):
    """CPU-only client for big-alone runs and the near-tie check (no draft GPU needed)."""
    from transformers import AutoTokenizer

    if plan["mode"] == "margins":
        cli = big_client(url)
        return [{**it, "top2": cli.post("/margin", json={"ctx": it["ctx"], "salt": f"margin:{i}"}).json()["top2"]}
                for i, it in enumerate(prompts)]
    return run_plan(prompts, warm, plan, url, AutoTokenizer.from_pretrained(path("mid")), None)


def big_client(url):
    import httpx

    hdr = {"Authorization": f"Bearer {os.environ['MODAL_VLLM_TOKEN']}"}
    return httpx.Client(base_url=url, headers=hdr, timeout=httpx.Timeout(200, connect=30), follow_redirects=True)


def run_plan(prompts, warm, plan, url, tok, local):
    """plan: name, mode (draft_alone | big_alone | spec), max_tokens, k, adaptive, pipeline, free."""
    import specplus

    cli, mt, mode, name = big_client(url), plan["max_tokens"], plan["mode"], plan["name"]
    rtt, srv = [], []

    def verify(ctx, d, salt):
        t0 = time.perf_counter()
        r = cli.post("/verify", json={"ctx": ctx, "draft": d, "salt": salt})
        r.raise_for_status()
        j = r.json()
        rtt.append((time.perf_counter() - t0) * 1e3)
        srv.append(j["server_ms"])
        return j["m"], j["next"]

    def one(p, tag):
        ids = tok.apply_chat_template(p["messages"], add_generation_prompt=True, tokenize=True)
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
                eos=set(core.EOS), choose=core.make_choose(specplus.choose_k) if plan.get("adaptive") else None,
                pipeline=plan.get("pipeline", False), free=(lambda c: fd.propose(c, 1)) if plan.get("free") else None)
            rec.update({k: getattr(st, k) for k in ("rounds", "drafted", "accepted", "misses", "free_drafted",
                                                    "free_accepted", "reused", "draft_ms", "verify_ms", "ks")})
        rec.update(wall_s=time.perf_counter() - t0, out=out)
        return rec

    stats0 = cli.get("/stats").json()
    for p in warm:  # warm-up prompts are not in the measured set
        one(p, "warm")
    rtt.clear()
    srv.clear()
    stats1 = cli.get("/stats").json()
    rows = [one(p, "run") for p in prompts]
    stats2 = cli.get("/stats").json()
    for r in rows:
        r["text"] = tok.decode(r["out"])
    return {"rows": rows, "rtt_ms": rtt, "server_ms": srv,
            "spec_counters": {"warm_delta": _delta(stats0, stats1), "run_delta": _delta(stats1, stats2)}}


def _delta(a, b):
    return {k: b[k] - a.get(k, 0.0) for k in b}


@app.function(image=image, volumes={"/hf": hf}, timeout=4 * 60 * MINUTES, cpu=8, memory=16384)
def download(keys: str):
    from huggingface_hub import snapshot_download

    for k in keys.split(","):
        t0 = time.time()
        snapshot_download(REPOS[k], local_dir=path(k), max_workers=16)
        hf.commit()
        print(k, REPOS[k], f"{time.time() - t0:.0f}s", flush=True)


# ---------- jobs ----------
def P(name, drafter, mode, **kw):
    return {"name": name, "drafter": drafter, "mode": mode, "max_tokens": 256, "k": 4, **kw}


PLUS = {"adaptive": True, "pipeline": True, "free": True}
JOBS = {  # job -> (big model, big mode, plans). Plans run in order; a finished plan file is skipped on a rerun.
    "smoke": ("big", "plain", [P("smoke_mid_alone", "mid", "draft_alone"), P("smoke_big_alone", "mid", "big_alone"),
                               P("smoke_spec_k4", "mid", "spec"), P("smoke_specplus", "mid", "spec", **PLUS)]),
    "cross": ("big", "plain", [  # most important first: a failure stops the job, a rerun skips finished plans
        P("mid_alone", "mid", "draft_alone"), P("big_alone", "mid", "big_alone"),
        P("spec_k4", "mid", "spec", k=4), P("specplus", "mid", "spec", **PLUS), P("spec_k8", "mid", "spec", k=8),
        P("big_alone_rep", "mid", "big_alone"),
        P("small_alone", "small", "draft_alone"), P("small_spec_k4", "small", "spec", k=4),
        P("small_specplus", "small", "spec", **PLUS),
        P("chain_alone", "mid+small", "draft_alone"), P("chain_spec_k4", "mid+small", "spec", k=4),
        P("chain_specplus", "mid+small", "spec", **PLUS),
        P("mideagle_alone", "mid+eagle", "draft_alone"), P("mideagle_specplus", "mid+eagle", "spec", **PLUS),
        P("margins", None, "margins", base="big_alone",
          runs=["spec_k4", "specplus", "spec_k8", "big_alone_rep", "small_spec_k4", "small_specplus", "chain_spec_k4",
                "chain_specplus", "mideagle_specplus"])]),
    **{m: ("big", m, [P(f"big_{m}", None, "big_alone"),
                      P(f"margins_{m}", None, "margins", base="big_alone", runs=[f"big_{m}"])])
       for m in ("eagle3", "ngram", "draft4b", "suffix")},
    "coder480": ("coder480", "plain", [P("c480_alone", "mid", "big_alone"), P("c480_spec_k4", "mid", "spec", k=4),
                                       P("c480_specplus", "mid", "spec", **PLUS),
                                       P("c480_margins", None, "margins", base="c480_alone",
                                         runs=["c480_spec_k4", "c480_specplus"])]),
}


def mismatches(out_dir, base, names):
    """Runs whose output differs from the big model alone: the context up to the first difference."""
    if not (out_dir / f"{base}.json").exists():
        print(f"no {base}.json yet: near-tie check skipped", flush=True)
        return []
    b = {r["id"]: r for r in json.loads((out_dir / f"{base}.json").read_text())["rows"]}
    items = []
    for n in names:
        f = out_dir / f"{n}.json"
        if not f.exists():
            continue
        for r in json.loads(f.read_text())["rows"]:
            ref = b.get(r["id"])
            i = core.first_diff(r["out"], ref["out"]) if ref else -1
            if 0 <= i < min(len(core.strip_eos(r["out"])), len(core.strip_eos(ref["out"]))):
                items.append({"run": n, "id": r["id"], "pos": i, "spec_tok": r["out"][i], "big_tok": ref["out"][i],
                              "ctx": ref["prompt_ids"] + ref["out"][:i]})
    return items


class KeepAlive(threading.Thread):
    """Pings Big while this job runs (e.g. while the next drafter box boots), so it does not cold-start twice."""

    def __init__(self, url):
        super().__init__(daemon=True)
        self.url, self.stop = url, threading.Event()

    def run(self):
        import httpx

        while not self.stop.wait(30):
            try:
                httpx.get(self.url + "/health", timeout=60, follow_redirects=True)
            except Exception:  # noqa: BLE001
                pass


@app.local_entrypoint()
def main(job: str = "smoke", keys: str = "small,mid,big,eagle_big,eagle_mid"):
    import httpx

    out = _repo / "bench" / ".scratch" / "spec_modal"
    if job == "download":
        download.remote(keys)
        return
    model, mode, plans = JOBS[job]
    assert (model, mode) == (BIG_MODEL, BIG_MODE), f"job {job} needs SPEC_BIG_MODEL={model} SPEC_BIG_MODE={mode}"
    ps = json.loads((out / "prompts.json").read_text())
    prompts, warm = ps["prompts"], ps["warm"]
    if job == "smoke":
        prompts = prompts[:3]
        plans = [{**p, "max_tokens": 48} for p in plans]
    url = Big().api.get_web_url()
    t0 = time.time()
    # Modal answers a request that waits over 150 s with a 303 to keep waiting; cap the cold start at ~30 / 45 min.
    with httpx.Client(follow_redirects=True, max_redirects=18 if BIG_MODEL == "coder480" else 12,
                      timeout=httpx.Timeout(200, connect=60)) as h:
        r = h.get(url + "/health")
        r.raise_for_status()
        health = r.json()
    meta = {"job": job, "big_first_health_s": round(time.time() - t0, 1), "big": health, "drafters": {}}
    print("big up:", json.dumps(meta), flush=True)
    keep = KeepAlive(url)
    keep.start()
    try:
        for plan in plans:
            f = out / f"{plan['name']}.json"
            if f.exists():
                print("skip (done):", f.name, flush=True)
                continue
            t1 = time.time()
            if plan["mode"] == "margins":
                items = mismatches(out, plan["base"], plan["runs"])
                res = {"rows": client.remote(items, [], plan, url) if items else []}
            elif plan["drafter"]:
                d = Draft(model=plan["drafter"])
                if plan["drafter"] not in meta["drafters"]:
                    meta["drafters"][plan["drafter"]] = {**d.info.remote(), "first_call_s": round(time.time() - t1, 1)}
                res = d.run.remote(prompts, warm, plan, url)
            else:
                res = client.remote(prompts, warm, plan, url)
            res.update(plan=plan, big=health, elapsed_s=round(time.time() - t1, 1))
            f.write_text(json.dumps(res))
            rows = [r for r in res["rows"] if "out" in r]
            toks, wall = sum(len(r["out"]) for r in rows), sum(r["wall_s"] for r in rows) or 1
            print(f"done {plan['name']}: {len(res['rows'])} rows, {toks / wall:.1f} tok/s, {res['elapsed_s']} s", flush=True)
    finally:
        keep.stop.set()
        try:
            meta["health_end"] = httpx.get(url + "/health", timeout=60, follow_redirects=True).json()
        except Exception as e:  # noqa: BLE001
            meta["health_end"] = repr(e)[:200]
        (out / f"meta_{job}.json").write_text(json.dumps(meta))
