"""Cost-case tier on Modal: vLLM for Qwen3-30B-A3B-Instruct-2507 (the model behind Ollama qwen3:30b-instruct) on one H200.

  .venv/bin/modal deploy deploy/modal/vllm_qwen30b.py      (make modal-qwen-up)
  .venv/bin/modal app stop -y chimera-qwen30b              (make modal-qwen-down)

Separate app from chimera-gpu-large so the gpt-oss tier is untouched. Same bearer-token secret and cache volumes.
Instruct-2507 has no thinking mode, so thinking is off by construction. BF16 weights (~61 GB) fit one H200.
Scales to zero: min_containers=0, scaledown_window=120 s. Prefix caching on.
"""
import subprocess

import modal

MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
PORT = 8000
MINUTES = 60

app = modal.App("chimera-qwen30b")
hf_cache = modal.Volume.from_name("chimera-hf-cache", create_if_missing=True)
vllm_cache = modal.Volume.from_name("chimera-vllm-cache", create_if_missing=True)

image = (
    modal.Image.from_registry("vllm/vllm-openai:v0.33.0")  # same image the gpt-oss tier already starts on
    .entrypoint([])
    .run_commands("ln -sf $(command -v python3) /usr/local/bin/python")
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
@modal.concurrent(max_inputs=64)
@modal.web_server(port=PORT, startup_timeout=15 * MINUTES)
def serve() -> None:
    import os

    cmd = [
        "vllm", "serve", MODEL, "--served-model-name", MODEL,
        "--host", "0.0.0.0", "--port", str(PORT),
        "--api-key", os.environ["MODAL_VLLM_TOKEN"],
        "--max-model-len", "16384", "--gpu-memory-utilization", "0.90",
        "--max-num-seqs", "64",
        "--enable-prefix-caching", "--enable-prompt-tokens-details",
    ]
    subprocess.Popen(cmd)  # the token is in argv only inside the container
