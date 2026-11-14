"""gpu-large tier on Modal: vLLM OpenAI-compatible server for Qwen3.5-122B-A10B (GPTQ-Int4) on one H200.

  modal secret create chimera-vllm-token MODAL_VLLM_TOKEN=<random>   (make modal-up does this)
  modal deploy deploy/modal/vllm_server.py                           (make modal-up)
  modal app stop chimera-gpu-large                                   (make modal-down)

Scales to zero: min_containers=0, scaledown_window=120 s. Bearer token comes from the Modal secret.
Weights live in the `chimera-hf-cache` Volume, so a cold start does not download them again.
"""
import subprocess

import modal

MODEL = "Qwen/Qwen3.5-122B-A10B-GPTQ-Int4"  # 78.9 GB; the FP8 build is 127 GB and leaves no KV room on 141 GB
PORT = 8000
MINUTES = 60

app = modal.App("chimera-gpu-large")
hf_cache = modal.Volume.from_name("chimera-hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("chimera-vllm-cache", create_if_missing=True)

image = (
    modal.Image.from_registry("nvidia/cuda:13.0.1-devel-ubuntu22.04", add_python="3.12")
    .entrypoint([])
    .uv_pip_install("vllm==0.33.0", "huggingface_hub[hf_xet]")
    .env({"HF_HOME": "/hf", "VLLM_CACHE_ROOT": "/vllm-cache"})
)


@app.function(
    image=image,
    gpu="H200",
    min_containers=0,
    scaledown_window=2 * MINUTES,
    timeout=60 * MINUTES,
    volumes={"/hf": hf_cache, "/vllm-cache": vllm_cache},
    secrets=[modal.Secret.from_name("chimera-vllm-token")],
)
@modal.concurrent(max_inputs=16)
@modal.web_server(port=PORT, startup_timeout=25 * MINUTES)
def serve() -> None:
    import os

    cmd = [
        "vllm", "serve", MODEL, "--served-model-name", MODEL,
        "--host", "0.0.0.0", "--port", str(PORT),
        "--api-key", os.environ["MODAL_VLLM_TOKEN"],
        "--quantization", "moe_wna16", "--language-model-only",
        "--max-model-len", "32768", "--gpu-memory-utilization", "0.90",
        "--enable-prefix-caching", "--max-logprobs", "20",
        "--reasoning-parser", "qwen3",
    ]
    subprocess.Popen(cmd)  # the token is in argv only inside the container
