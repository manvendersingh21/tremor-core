"""Target-side verifier for speculative decoding (runs on the GPU box, binds 127.0.0.1 only).

Loads the same GGUF Ollama uses with llama-cpp-python (logits_all=True). For prompt ids + K draft ids
it runs ONE forward pass over the new tokens and returns, per draft token, the target logprob, and
for each of the K+1 positions one token sampled from the target. Its KV cache is its own: the
longest common prefix with the previous request is reused, nothing KV-shaped leaves this process.

  python verify_server.py --model <gguf> --port 18101 --n-gpu-layers 24
"""
from __future__ import annotations

import argparse
import time

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel


class VerifyReq(BaseModel):
    prompt_ids: list[int]
    draft_ids: list[int]
    temperature: float = 1.0
    seed: int | None = None


class TokReq(BaseModel):
    text: str


def build_app(llm) -> FastAPI:
    app = FastAPI()
    rng = np.random.default_rng()

    @app.post("/tokenize")
    def tokenize(r: TokReq):
        return {"ids": llm.tokenize(r.text.encode(), add_bos=False, special=True)}

    @app.post("/verify")
    def verify(r: VerifyReq):
        t0 = time.perf_counter()
        ids = r.prompt_ids + r.draft_ids
        n_p, k = len(r.prompt_ids), len(r.draft_ids)
        cached = llm.input_ids[: llm.n_tokens].tolist()
        common = 0
        for a, b in zip(cached, ids):
            if a != b:
                break
            common += 1
        keep = min(common, n_p - 1)  # always re-run the last prompt token to get its logits
        llm._ctx.kv_cache_seq_rm(-1, keep, -1)
        llm.n_tokens = keep
        llm.eval(ids[keep:])
        rows = np.asarray(llm.scores[n_p - 1 : n_p + k], dtype=np.float32) / max(r.temperature, 1e-6)
        rows -= rows.max(axis=1, keepdims=True)
        logp = rows - np.log(np.exp(rows).sum(axis=1, keepdims=True))
        g = np.random.default_rng(r.seed) if r.seed is not None else rng
        nxt = [int(g.choice(logp.shape[1], p=np.exp(lp) / np.exp(lp).sum())) for lp in logp]
        return {
            "logprobs": [float(logp[j, t]) for j, t in enumerate(r.draft_ids)],
            "next_ids": nxt,
            "reused_tokens": keep,
            "ms": round((time.perf_counter() - t0) * 1000, 1),
        }

    return app


if __name__ == "__main__":
    import uvicorn
    from llama_cpp import Llama

    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--port", type=int, default=18101)
    ap.add_argument("--n-gpu-layers", type=int, default=24)
    ap.add_argument("--n-ctx", type=int, default=2048)
    a = ap.parse_args()
    model = Llama(model_path=a.model, n_gpu_layers=a.n_gpu_layers, n_ctx=a.n_ctx, n_batch=512,
                  logits_all=True, verbose=False)
    uvicorn.run(build_app(model), host="127.0.0.1", port=a.port, log_level="warning")
