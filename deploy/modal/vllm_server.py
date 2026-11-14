"""gpu-large tier on Modal: vLLM OpenAI-compatible server for openai/gpt-oss-120b (MXFP4, ~65 GB) on one H200.

  modal secret create chimera-vllm-token MODAL_VLLM_TOKEN=<random>   (make modal-up does this)
  modal deploy deploy/modal/vllm_server.py                           (make modal-up)
  modal app stop -y chimera-gpu-large                                (make modal-down)

Scales to zero: min_containers=0, scaledown_window=120 s. Bearer token comes from the Modal secret.
Weights live in the `chimera-hf-cache` Volume, so a cold start does not download them again.
Image: official vllm/vllm-openai v0.33.0. The cuda:13 + pip vllm image lacked libnvrtc-builtins.so.13.0, and the
v0.32.0-cu129 tag crashed on import (torchcodec wants libnvrtc.so.13). See bench/results_modal.md.
"""
import subprocess

import modal

MODEL = "openai/gpt-oss-120b"  # MXFP4 is native; vLLM picks the Hopper MXFP4 MoE kernels, no --quantization flag
PORT = 8000
MINUTES = 60

app = modal.App("chimera-gpu-large")
hf_cache = modal.Volume.from_name("chimera-hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("chimera-vllm-cache", create_if_missing=True)

image = (
    modal.Image.from_registry("vllm/vllm-openai:v0.33.0")  # torch 2.14 cu130; import checked on an L4 first
    .entrypoint([])
    .run_commands("ln -sf $(command -v python3) /usr/local/bin/python")  # Modal reads `python --version`
    .env({"HF_HOME": "/hf", "VLLM_CACHE_ROOT": "/vllm-cache"})
)


@app.function(
    image=image,
    gpu="H200",
    min_containers=0,
    scaledown_window=2 * MINUTES,
    timeout=30 * MINUTES,
    volumes={"/hf": hf_cache, "/vllm-cache": vllm_cache},
    secrets=[modal.Secret.from_name("chimera-vllm-token")],
)
@modal.concurrent(max_inputs=16)
@modal.web_server(port=PORT, startup_timeout=15 * MINUTES)
def serve() -> None:
    import os

    cmd = [
        "vllm", "serve", MODEL, "--served-model-name", MODEL,
        "--host", "0.0.0.0", "--port", str(PORT),
        "--api-key", os.environ["MODAL_VLLM_TOKEN"],
        "--max-model-len", "32768", "--gpu-memory-utilization", "0.90",
        "--enable-prefix-caching", "--max-logprobs", "20",
    ]
    subprocess.Popen(cmd)  # the token is in argv only inside the container
