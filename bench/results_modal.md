# Modal H200 (gpu-large): results

Two models were tried. Qwen3.5-122B (attempt 1) never served. `openai/gpt-oss-120b` (attempt 2) served after a 376 s cold start, and pair runs A and D finished. Runs E, B and C, the KV test and the gateway smoke test did not run: the work was stopped by a handoff order at 22:54 PST.

## Verdict (single run, 30 prompts)

| Run | 763B calls | 763B in / out / cached | 763B $ | H200 time | H200 $ | local tokens | median ms | p90 ms | asserts |
|---|---|---|---|---|---|---|---|---|---|
| A: 763B only | 25 | 1,167 / 4,539 / 0 | $0.0058 | 0 | $0 | 0 | 728 | 2,799 | 24/24 |
| D: H200 120B -> 763B | **0** | 0 / 0 / 0 | $0 | about 90 s | about $0.11 | 22,395 | 1,352 | 8,125 | 24/24 |

5 of 30 prompts were cache hits in both runs. Quality ties on asserts. No blind grade was run.

- **Cost:** A wins. The 763B is so cheap ($0.0058 for 25 calls) that 90 s of H200 time costs about 20x more. D only wins on cost if the H200 is already up and busy with other traffic.
- **Speed:** A wins. Median 728 ms vs 1,352 ms, and heavy-prompt median 2.6 s vs 6.6 s.
- **Quality:** a tie, 24/24 each.
- **Best pair: A (763B only).** The H200 tier adds no value at this traffic level. Recommend dropping `gpu-large` unless traffic is steady enough to keep it busy, or the data must stay off Crusoe.
- **Speculative verify:** skipped on gpt-oss. It is not a Qwen model, so its token ids don't match the Mac Qwen 3B.

Raw rows: `bench/results_modal.csv` (runs A and D).

---

# Attempt 1: Qwen3.5-122B (failed)

**Verdict: not measured.** The H200 never served a request in two cold starts. The user stopped the app by hand at 22:26 PST.

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

---

# Attempt 2: openai/gpt-oss-120b

## Setup

| Item | Value |
|---|---|
| Model | `openai/gpt-oss-120b`, MXFP4 (native), `reasoning_effort=low` |
| GPU | 1x H200, $4.54/hr list |
| Image | `vllm/vllm-openai:v0.33.0` (torch 2.14 cu130) |
| Flags | `--enable-prefix-caching`, `--max-logprobs 20`, `--max-model-len 32768`, `--gpu-memory-utilization 0.90` |
| Memory | weights plus graphs 62.4 GiB of 139.8 GiB; the rest is KV cache |
| Scaling | `min_containers=0`, `scaledown_window=120` s, bearer token from Modal secret |

## Deploys

| # | App id | Time (PST) | Result |
|---|---|---|---|
| 2a | `ap-diKaSKgzuJnkfdCh3FFOCr` | 22:33 to 22:37 | Deploy refused: Modal couldn't read the Python version. Fixed with a `python` symlink. No GPU used. |
| 2b | `ap-yjcGHZwcr6Jbz1StbEzjG4` | 22:37 to 22:40 | Image `v0.32.0-cu129` crashed on import: `libnvrtc.so.13` missing (torchcodec). Stopped at once. |
| check | `ap-jnG6BFAxKctwFzht99b1pf` | 22:40 to 22:45 | L4 import test of `v0.33.0`: OK. |
| 2c | `ap-0WpQuCjxibIkA2hScBskOi` | 22:45 to 22:54 | **Served.** Stopped at 22:54:45. |

## Cold start (2c)

| Step | Time |
|---|---|
| Deploy to first `/v1/models` 200 | **376 s** |
| GPU wait plus weight download (first time, about 65 GB to the Volume) | about 3.5 min |
| Engine init (profile, KV cache, warmup) | 147 s, of which torch.compile 16 s |
| CUDA graph capture | 34 s |

The weights are now in `chimera-hf-cache`, so the next cold start skips the download.

## Cost of attempt 2

| Item | Minutes | $ (upper bound) |
|---|---|---|
| 2b H200 | about 1.5 | about $0.11 |
| L4 check | about 4.5 | about $0.06 |
| 2c H200 | about 9.3 | about $0.70 |
| **Total** | | **about $0.87** |

Both attempts together: about **$2.5** upper bound, from app lifetimes. Check the Modal dashboard for the real bill.

## Not run (stopped for handoff)

Run E crashed in 6 s with `Connection refused` on one tier URL; I did not find which one before the stop order. Runs B and C, the KV test (`bench/run_kv.py`), the gateway smoke test (`$KIROCREW_SCRATCH/gw_smoke.py`, not committed) and the blind grade did not run.

## Shutdown proof (attempt 2)

`modal app list --json` at 22:55 PST:

```
ap-0WpQuCjxibIkA2hScBskOi  chimera-gpu-large   stopped  0 tasks  stopped 22:54:45
ap-jnG6BFAxKctwFzht99b1pf  chimera-img-check   stopped  0 tasks  stopped 22:45:20
ap-yjcGHZwcr6Jbz1StbEzjG4  chimera-gpu-large   stopped  0 tasks  stopped 22:40:29
ap-diKaSKgzuJnkfdCh3FFOCr  chimera-gpu-large   stopped  0 tasks  stopped 22:37:23
ap-bxrD1t1A1mEhHoHZGP87m0  chimera-gpu-large   stopped  0 tasks  stopped 22:26:21
ap-EynMuiNwVDXTLhuy3jtxwI  chimera-gpu-large   stopped  0 tasks  stopped 22:19:21
ap-mtBeVO40ImcVekiTgW8Vjt  chimera-h100-check  stopped  0 tasks  stopped 22:03:25
```

No `chimera-*` app is running or deployed.
