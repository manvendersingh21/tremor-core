"""Speculative decoding across two Modal boxes: a ~30B drafts on an L40S, a Qwen3-235B verifies on H200s.

App `chimera-spec-modal` (own name; it never touches chimera-gpu-large, chimera-qwen30b or the video app).

  modal run deploy/modal/spec_modal.py::download          # weights go to the Modal volume, never to the Mac
  modal deploy deploy/modal/spec_modal.py                 # classes Big and Draft (scale to zero)
  modal app stop -y chimera-spec-modal                    # always, at the end; then `modal app list`

Same family on purpose: every model below is Qwen3 Instruct-2507, one tokenizer.
Draft runs the loop (bench/spec_modal_core.py) next to its own vLLM, so the draft hop is local and the verify hop crosses
Modal's network, like a laptop next to a server. Big exposes /verify (compact: accepted count + next token, no logprobs on
the wire), /generate (big alone) and /health. Bearer token = the existing `chimera-vllm-token` secret.
shortcut: the verify call asks vLLM for prompt_logprobs, so the big model re-reads the whole context each round (vLLM skips
prefix-cache reuse for prompt_logprobs). Fine for 100-1,000 token contexts; a custom verifier would remove it.
"""
import os
import subprocess
import time

import modal

MINUTES = 60
MODELS = {
    "big": "Qwen/Qwen3-235B-A22B-Instruct-2507-FP8",
    "mid": "Qwen/Qwen3-30B-A3B-Instruct-2507-FP8",
    "small": "Qwen/Qwen3-4B-Instruct-2507",
}
BIG_GPUS = int(os.environ.get("SPEC_BIG_GPUS", "2"))
EOS = 151645  # <|im_end|>

app = modal.App("chimera-spec-modal")
hf = modal.Volume.from_name("chimera-spec-hf", create_if_missing=True)  # own volume: no overlap with the other chats
vcache = modal.Volume.from_name("chimera-spec-vllm-cache", create_if_missing=True)
token = modal.Secret.from_name("chimera-vllm-token")
image = (
    modal.Image.from_registry("vllm/vllm-openai:v0.33.0")  # the image the other tiers already start on
    .entrypoint([])
    .run_commands("ln -sf $(command -v python3) /usr/local/bin/python")
    .env({"HF_HOME": "/hf", "VLLM_CACHE_ROOT": "/vllm-cache", "HF_HUB_ENABLE_HF_TRANSFER": "0"})
    .add_local_file(os.path.join(os.path.dirname(__file__), "..", "..", "bench", "spec_modal_core.py"), "/root/spec_modal_core.py")
)


def path(key: str) -> str:
    return f"/hf/models/{MODELS[key].split('/')[-1]}"


def start_vllm(model_path: str, name: str, extra: list[str], port: int = 8000):
    cmd = ["vllm", "serve", model_path, "--served-model-name", name, "--host", "127.0.0.1", "--port", str(port),
           "--enable-prefix-caching", *extra]
    return subprocess.Popen(cmd)


def wait_ready(port: int = 8000, limit: int = 20 * MINUTES):
    import httpx

    t0 = time.time()
    while time.time() - t0 < limit:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=3).status_code == 200:
                return time.time() - t0
        except Exception:  # noqa: BLE001
            pass
        time.sleep(3)
    raise RuntimeError("vllm did not become healthy")


def complete(port: int, name: str, prompt_ids: list[int], max_tokens: int, **extra) -> dict:
    import httpx

    body = {"model": name, "prompt": prompt_ids, "max_tokens": max_tokens, "temperature": 0, "return_token_ids": True, **extra}
    r = httpx.post(f"http://127.0.0.1:{port}/v1/completions", json=body, timeout=600)
    r.raise_for_status()
    return r.json()["choices"][0]


def verify_local(port: int, name: str, ctx: list[int], d: list[int]) -> tuple[int, int]:
    """One forward over ctx+draft: returns (accepted count, big model's next token). Greedy, so lossless."""
    ch = complete(port, name, ctx + d, 1, prompt_logprobs=1)
    pl = ch["prompt_logprobs"]
    n = len(ctx)
    for i, t in enumerate(d):
        top = next(int(k) for k, v in pl[n + i].items() if v.get("rank") == 1)
        if top != t:
            return i, top
    return len(d), ch["token_ids"][0]


@app.function(image=image, volumes={"/hf": hf}, timeout=90 * MINUTES, cpu=4, memory=16384)
def download(keys: str = "small,mid,big"):
    from huggingface_hub import snapshot_download

    for k in keys.split(","):
        t0 = time.time()
        snapshot_download(MODELS[k], local_dir=path(k), max_workers=16)
        hf.commit()
        print(k, MODELS[k], f"{time.time() - t0:.0f}s")


# SPEC_MODE picks the big server's own speculative setting; each mode is its own container pool (its own cold start).
BIG_EXTRA = {
    "plain": [],
    "ngram": ["--speculative-config", '{"method":"ngram","num_speculative_tokens":5,"prompt_lookup_max":4}'],
    "draft4b": ["--speculative-config",
                '{"method":"draft_model","model":"%s","num_speculative_tokens":4}' % path("small")],
}


@app.cls(image=image, gpu=f"H200:{BIG_GPUS}", volumes={"/hf": hf, "/vllm-cache": vcache}, secrets=[token],
         min_containers=0, scaledown_window=20 * MINUTES, timeout=60 * MINUTES)
@modal.concurrent(max_inputs=8)
class Big:
    mode: str = modal.parameter(default="plain")

    @modal.enter()
    def boot(self):
        t0 = time.time()
        self.proc = start_vllm(path("big"), "big", [
            "--tensor-parallel-size", str(BIG_GPUS), "--max-model-len", "4096", "--max-num-seqs", "8",
            "--gpu-memory-utilization", "0.93", "--max-logprobs", "5", *BIG_EXTRA[self.mode]])
        self.cold_s = wait_ready()
        self.boot_s = time.time() - t0

    @modal.asgi_app()
    def api(self):
        from fastapi import Depends, FastAPI, Header, HTTPException

        web = FastAPI()
        key = os.environ["MODAL_VLLM_TOKEN"]

        def auth(authorization: str = Header(default="")):
            if authorization != f"Bearer {key}":
                raise HTTPException(401)

        @web.get("/health")
        def health():
            return {"mode": self.mode, "gpus": BIG_GPUS, "cold_start_s": round(self.boot_s, 1)}

        @web.post("/verify", dependencies=[Depends(auth)])
        def verify(b: dict):
            t0 = time.perf_counter()
            m, nxt = verify_local(8000, "big", b["ctx"], b["draft"])
            return {"m": m, "next": nxt, "server_ms": (time.perf_counter() - t0) * 1e3}

        @web.post("/generate", dependencies=[Depends(auth)])
        def generate(b: dict):
            t0 = time.perf_counter()
            ch = complete(8000, "big", b["ctx"], b["max_tokens"])
            return {"ids": ch["token_ids"], "server_ms": (time.perf_counter() - t0) * 1e3}

        return web


@app.cls(image=image, gpu="L40S", volumes={"/hf": hf, "/vllm-cache": vcache}, secrets=[token],
         min_containers=0, scaledown_window=20 * MINUTES, timeout=60 * MINUTES)
class Draft:
    model: str = modal.parameter(default="mid")  # "mid" (30B), "small" (4B), "mid+small" (30B drafted by the 4B, same box)

    @modal.enter()
    def boot(self):
        t0 = time.time()
        key = self.model.split("+")[0]
        extra = ["--max-model-len", "4096", "--max-num-seqs", "4", "--gpu-memory-utilization", "0.92"]
        if "+" in self.model:
            extra += ["--speculative-config",
                      '{"method":"draft_model","model":"%s","num_speculative_tokens":4}' % path("small")]
        self.name = key
        self.proc = start_vllm(path(key), key, extra)
        wait_ready()
        self.cold_s = time.time() - t0
        from transformers import AutoTokenizer

        self.tok = AutoTokenizer.from_pretrained(path("mid"))  # one tokenizer for the whole family

    def ids(self, messages):
        return self.tok.apply_chat_template(messages, add_generation_prompt=True, tokenize=True)

    @modal.method()
    def info(self):
        return {"model": self.model, "cold_start_s": round(self.cold_s, 1)}

    @modal.method()
    def run(self, prompts: list, plan: dict) -> list:
        """plan: mode = draft_alone | big_alone | spec ; k, adaptive, max_tokens, big_mode. prompts = [{id, messages}]."""
        import httpx
        import sys

        sys.path.insert(0, "/root")
        import spec_modal_core as core

        big = modal.Cls.from_name("chimera-spec-modal", "Big")(mode=plan.get("big_mode", "plain"))
        url = big.api.get_web_url()
        hdr = {"Authorization": f"Bearer {os.environ['MODAL_VLLM_TOKEN']}"}
        cli = httpx.Client(base_url=url, headers=hdr, timeout=600)
        mt, mode, rtts, srv = plan["max_tokens"], plan["mode"], [], []

        def draft(ctx, k):
            return complete(8000, self.name, ctx, k)["token_ids"]

        def verify(ctx, d):
            t0 = time.perf_counter()
            r = cli.post("/verify", json={"ctx": ctx, "draft": d}).json()
            rtts.append((time.perf_counter() - t0) * 1e3)
            srv.append(r["server_ms"])
            return r["m"], r["next"]

        def one(p):
            ids = self.ids(p["messages"])
            t0 = time.perf_counter()
            rec = {"id": p["id"], "prompt_tokens": len(ids)}
            if mode == "draft_alone":
                out = complete(8000, self.name, ids, mt)["token_ids"]
            elif mode == "big_alone":
                r = cli.post("/generate", json={"ctx": ids, "max_tokens": mt}).json()
                out = r["ids"]
                rec["server_ms"] = r["server_ms"]
            else:
                out, st = core.spec_generate(draft, verify, ids, mt, k=plan.get("k", 4), adaptive=plan.get("adaptive", False),
                                             eos={EOS})
                rec.update(rounds=st.rounds, alpha=st.alpha, draft_ms=st.draft_ms, verify_ms=st.verify_ms, ks=st.ks)
            rec.update(wall_s=time.perf_counter() - t0, out=out, text=self.tok.decode(out))
            return rec

        for p in prompts[:2]:  # warm caches, not counted
            one(p)
        rtts.clear()
        srv.clear()
        res = [one(p) for p in prompts]
        for r in res:
            r["mode"], r["plan"] = mode, plan
        if rtts:
            res[0]["rtt_ms_all"] = rtts
            res[0]["server_ms_all"] = srv
        return res
