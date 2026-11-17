# gpu-120b: a ~120B model on your own GPU, between the 30B and the 763B

Status: prepared, never run. No GPU was rented and $0 was spent. The tier is in `chimera.example.toml` (and the local
`chimera.toml`) and stays off until `CHIMERA_120B_URL` is set in `.env`. `bin/chimera doctor` shows it as off until then:

    ⏸  gpu-120b off (CHIMERA_120B_URL not set in .env)

## What it is

- Model: `openai/gpt-oss-120b`, MXFP4 MoE weights, about 65 GB. Same model as the Modal `gpu-large` tier, which served
  it on an H200 (`bench/results_modal.md`: same 24/24 asserts as the 763B, but slower and dearer per call there).
- Server: vLLM `vllm/vllm-openai:v0.33.0` in Docker (`deploy/gpu120b/serve_vllm.sh`), OpenAI-compatible, bound to
  `127.0.0.1:8000` on the box only. The Mac reaches it through an SSH tunnel to your GPU box.
- Router: `[[tiers]] name = "gpu-120b"`, backend `openai`, `max_complexity = 0.85`, cost 0 (owned hardware). The pool
  sorts owned tiers small first, so the order is: cache, `gpu-h200` (only while warm), `gpu-small` (30B, 0.6),
  `gpu-120b` (0.85), `cloud-deepseek` (763B, 1.0). Checked in `tests/test_tiers.py`.
  - A task the 30B answers below the 0.95 confidence gate climbs to the 120B before the 763B.
  - A task with complexity 0.6 to 0.85 now goes to the 120B first, not straight to the 763B. Above 0.85: the 763B.
  - This tier has no confidence gate (vLLM logprobs are off, like `gpu-large`), so its answers are served unless a
    caller's check fails, which climbs to the 763B. `logprobs = true` exists but is untested with gpt-oss.
  - `teacher = true`: its checked answers are stored as N+1 memory for the 30B.
- Off switch: with `CHIMERA_120B_URL` unset the tier's probe fails at once (no request is sent), so the pool skips it,
  and `chimera doctor` reports it as off (`tiers.unset_env`). Remove the line from `.env` when the box is returned.

## Which GPU fits

| GPUs | Memory | gpt-oss-120b | How | Tested here |
|---|---|---|---|---|
| 1x H100 80 GB | 80 GB | Fits (65 GB weights, the rest for the KV cache at 32k context) | `serve_vllm.sh`, tensor parallel 1 | No |
| 1x H200 141 GB | 141 GB | Fits with room for long contexts and more parallel calls | `serve_vllm.sh`, tensor parallel 1 | Yes, on Modal (`bench/results_modal.md`) |
| 2x 48 GB (L40S, RTX 6000 Ada, A6000) | 96 GB | Weights fit, but vLLM does not serve gpt-oss MXFP4 on Ada or Ampere yet ([vLLM recipe](https://docs.vllm.ai/projects/recipes/en/stable/OpenAI/GPT-OSS.html) lists H100, H200 and B200; Ampere and Ada are in progress) | llama.cpp, below | No |
| 4x 24 GB (L4, RTX 4090, A10) | 96 GB | Same as above and tight: about 16 GB of weights per card plus the KV cache; expect it to be slow | llama.cpp, below | No |
| 1x V100 32 GB (the Akash 30B box) | 32 GB | Does not fit | none | - |

`serve_vllm.sh` checks this itself: it refuses a GPU below compute capability 9.0 (Hopper) or under 80 GB in total,
and splits the weights over all GPUs (tensor parallel = GPU count) when no single GPU has 80 GB.

Other ~120-130B open models: Qwen3.5-122B is about 122 GB in FP8 (one H200, or 2x 80 GB) and about 244 GB in BF16
(4x 80 GB). This repo never got it served on Modal (`bench/results_modal.md`), so gpt-oss-120b is the pick: it is the
smallest ~120B model (65 GB) and the only one this repo has served.

## Setup, when the GPU arrives

1. Make a token on the Mac and put it in `.env` as `CHIMERA_120B_TOKEN=` (for example `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`).
   Put the box's ssh alias (a Host entry in your ssh config) in `.env` as `CHIMERA_120B_SSH=`.
2. On the box (NVIDIA driver and Docker with the NVIDIA runtime installed), copy `deploy/gpu120b/serve_vllm.sh` and run:

       export CHIMERA_120B_TOKEN=<the same value>
       bash serve_vllm.sh

   The first start downloads about 65 GB; the script waits up to 30 min for `/health`. `docker logs -f chimera-120b`
   shows progress. The port is bound to the box's loopback only; do not publish it.
3. On the Mac, open the tunnel. Pick a free local port `<port>`, with the box's vLLM on 127.0.0.1:8000:

       ssh -N -o BatchMode=yes -o ServerAliveInterval=10 -L 127.0.0.1:<port>:127.0.0.1:8000 "$CHIMERA_120B_SSH" </dev/null

   For a self-healing tunnel, the existing keeper takes the same settings from the environment (it shares its log,
   `bench/.scratch/gpu_tunnel.log`, with the 30B tunnel):

       set -a; . ./.env; set +a
       CHIMERA_GPU_SSH="$CHIMERA_120B_SSH" CHIMERA_GPU_URL=http://127.0.0.1:<port> CHIMERA_GPU_REMOTE=127.0.0.1:8000 scripts/gpu_tunnel_keep.sh &

4. Set `CHIMERA_120B_URL=http://127.0.0.1:<port>` in `.env`.
5. Check: `bin/chimera doctor` shows `✅ gpu-120b`. Then restart `make web` so the router reads the tier.
6. Smoke test without the web page: `bin/chimera ask "Explain the difference between a mutex and a semaphore"`. The
   telemetry line names the tier that answered.

Stop: `docker rm -f chimera-120b` on the box (the weights stay in `~/.cache/huggingface`), close the tunnel
(`lsof -ti tcp:<port>`, then kill that number), and remove `CHIMERA_120B_URL` from `.env`.

## Other GPUs (Ada or Ampere): llama.cpp, not tested

llama.cpp runs the GGUF of gpt-oss-120b on these cards and splits layers over several GPUs. Its `llama-server` is
OpenAI-compatible, so the same `gpu-120b` tier works unchanged (`/v1/models`, `/v1/chat/completions`). On the box,
with llama.cpp built for CUDA:

    LLAMA_ARG_API_KEY="$CHIMERA_120B_TOKEN" llama-server -hf ggml-org/gpt-oss-120b-GGUF \
        --host 127.0.0.1 --port 8000 -ngl 99 --split-mode layer -c 16384 --jinja

Then follow steps 3 to 6 above. Not run here: the speed on 2x 48 GB or 4x 24 GB is unknown.

## Cost

The tier has per-token prices of 0 because you pay the box by the hour. In the one Modal pair run, gpt-oss-120b on
an H200 cost about $0.11 of GPU time against $0.0058 of 763B tokens for the same calls (`bench/results_modal.md`).
A rented 120B box only pays off when it is kept busy. Measure it with `bench/run_ladder.py` before calling it a saving.

## Files

- `deploy/gpu120b/serve_vllm.sh`: the box side (checked with `bash -n` only).
- `chimera.example.toml`: the `gpu-120b` `[[tiers]]` block. `.env.example`: `CHIMERA_120B_URL`, `CHIMERA_120B_TOKEN`, `CHIMERA_120B_SSH`.
- `packages/chimera-core/tiers.py`: `unset_env()` names the unset `$VAR` of a tier URL (such a tier fails its probe and is skipped).
- `apps/kiro-trimmer/cli.py`: `chimera doctor` prints such a tier as off, not as a failure.
- Tests: `tests/test_tiers.py` (`test_gpu_120b_tier_is_off_until_its_url_is_set`, `test_doctor_shows_an_unset_tier_as_off`).
