# Modal H200 (gpu-large): results

**Verdict: not measured.** The H200 never served a request in two cold starts. There are no ladder, speculative-decoding, gateway or KV-cache numbers from Modal. Nothing here is a speedup or savings claim. The user stopped the app by hand at 22:26 PST, and no run was started after that.

## Setup

| Item | Value |
|---|---|
| App | `chimera-gpu-large`, file `deploy/modal/vllm_server.py` |
| Model | `Qwen/Qwen3.5-122B-A10B-GPTQ-Int4` (122B MoE, Qwen family) |
| Why this build | FP8 is about 127 GB and leaves almost no KV room on 141 GB. The 4-bit build is 78.9 GB. |
| GPU | 1x H200 (143,771 MiB seen in the earlier GPU test). List price about $4.54/hr. |
| Server | vLLM 0.33.0, `--quantization moe_wna16`, `--enable-prefix-caching`, `--max-logprobs 20`, `--max-model-len 32768`, `--gpu-memory-utilization 0.90` |
| Scaling | `min_containers=0`, `scaledown_window=120` s |
| Auth | Bearer token from Modal secret `chimera-vllm-token`. Local copy in `.env` only. |
| Weights | Volume `chimera-hf-cache`. Compile cache in `chimera-vllm-cache`. |
| Fallback (not tried) | `openai/gpt-oss-120b` (MXFP4, about 65 GB). Different family, so no speculative verify. |

## Cold-start attempts

| # | App id | Alive (PST, 13 Nov) | Result |
|---|---|---|---|
| 0 | `ap-mtBeVO40ImcVekiTgW8Vjt` (`chimera-h100-check`) | 22:03, under 1 min | GPU sanity check only. |
| 1 | `ap-EynMuiNwVDXTLhuy3jtxwI` | 22:06 to 22:19 | **Failed at model load.** CUDA image problem (below). |
| 2 | `ap-bxrD1t1A1mEhHoHZGP87m0` | 22:19 to 22:26 | **Never became ready.** Stopped by the user at 22:26. |

**Attempt 1 error.** Image `nvidia/cuda:13.0.1-devel-ubuntu22.04` with vLLM 0.33.0. The engine core died in `load_model` with:

- `nvrtc: error: failed to open libnvrtc-builtins.so.13.0`
- `NVRTC_ERROR_BUILTIN_OPERATION_FAILURE` while compiling a kernel under `/root/.humming/cache/`

So the runtime compile step could not find the CUDA 13 NVRTC builtins library. The file still uses the `cuda:13.0.1-devel` image. Attempt 2 got past this point (it reached shard loading), but I could not confirm from the logs what changed.

**Attempt 2.** The log shows checkpoint shards loading at 26/39 (67%) after 2 min 15 s, about 4.8 s per shard. Then the SIGINT from the stop at 06:26:27 UTC (22:26 PST). The log tail also holds many `CUDACachingAllocator` OOM warnings (free 13.9 MB of 150.1 GB, asking for 20 MB). They carry the same second as the stop. I can't tell whether they caused the stop or came from the shutdown. Load had not finished, so no health check, no `/v1/models` 200 and no first token happened.

Cold-start time, model load time and first-token time: **not measured** (load never finished).

## Cost so far

| Item | Value |
|---|---|
| Rate | $4.54/hr list price |
| Attempt 1 | about 13 min of app life, up to about $0.98 |
| Attempt 2 | about 7 min of app life, up to about $0.53 |
| Check app | under $0.08 |
| **Upper bound** | **about $1.6** |

These use app lifetime, not billed GPU seconds. The real bill is at or below this. Check the Modal dashboard for the exact figure. CPU image-build time is not in this number.

## Not run

Ladder with Modal, speculative decoding (K=4, 8), gateway smoke test, pair test (A to E), token-flow example, KV cache reuse on the H200 and vLLM `/metrics` hit rate. All need a live H200 endpoint. `bench/run_spec_modal.py` was not written. Any numbers in other `bench/results_*.md` files come from other tiers.

## Shutdown proof

`modal app list` at 22:30 PST, 13 Nov 2026:

```
chimera-gpu-large   ap-bxrD1t1A1mEhHoHZGP87m0   stopped   0 tasks   stopped 22:26 PST
chimera-gpu-large   ap-EynMuiNwVDXTLhuy3jtxwI   stopped   0 tasks   stopped 22:19 PST
chimera-h100-check  ap-mtBeVO40ImcVekiTgW8Vjt   stopped   0 tasks   stopped 22:03 PST
```

No `chimera-*` app is running or deployed. All show 0 tasks.

## Volumes (kept)

`chimera-hf-cache` and `chimera-vllm-cache` exist. Their size was not measured. `modal volume ls chimera-hf-cache /` shows only the `hub` and `xet` folders. The 4-bit weights are about 78.9 GB if the download finished, and attempt 2 had read 26 of 39 shards from the cache or disk. To delete: `.venv/bin/modal volume delete chimera-hf-cache` and `.venv/bin/modal volume delete chimera-vllm-cache`. Volumes cost storage only, nothing while idle compute is off.

## Start it again

```
make modal-up      # deploys, scales to zero on its own
make modal-down    # stop -y chimera-gpu-large, then lists apps
```

After `modal-up`, put the printed URL in `.env` as `MODAL_VLLM_URL`. `MODAL_VLLM_TOKEN` is already there. The first call cold-starts the container. Poll `/v1/models` with the bearer token. If it isn't 200 within about 5 min, run `make modal-down`.

## Next attempt

1. Verify the image first, with a cheap test: build and run `python -c "import vllm"` plus a small NVRTC compile on a small GPU. Or use the official `vllm/vllm-openai` image pinned to a CUDA 12.x build instead of `nvidia/cuda:13`, so `libnvrtc-builtins` matches the toolkit. This was the attempt 1 failure.
2. Pre-download the weights in a separate CPU-only Modal function that writes to `chimera-hf-cache` and commits the volume. Then the GPU container starts with weights on disk and bills no H200 time for download.
3. Capture the OOM. Run with `--gpu-memory-utilization 0.85`, `--max-num-seqs 16`, and `--enforce-eager` for the first boot. Print `nvidia-smi` at start. If load still runs out of memory at 4-bit, drop to `--max-model-len 16384`, or use the `openai/gpt-oss-120b` fallback (about 65 GB).
4. Poll `/v1/models` from a script with a hard 5 min cap that runs `modal app stop -y chimera-gpu-large` on timeout, so an idle app can't keep billing.
5. Once it is up, run in this order: `/v1/models` 200, one completion, speculative tokenizer-id check, then the ladder, spec and KV tests in one session, and stop the app.

Skipped: the CSV (`bench/results_modal.csv`), unit tests for the vLLM verify backend and all live tests. Risk: the `chimera.example.toml` gpu-large entry and the verify backend are untested against a real vLLM server.
