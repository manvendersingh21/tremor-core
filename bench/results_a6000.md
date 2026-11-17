# Owned-hardware proof: cache + answer check on a shared RTX A6000 (GPU 1 only)

## Verdict

- **qwen3:30b-instruct: cache + answer check cut 76.7% of big-model calls with 0 wrong answers from the cache on owned hardware** (6 first-pass runs, 1041 items, against sending every item to the 763B). 

**Interim report** (runs still going; this file is rebuilt as rows land).

## Setup

- Box: a shared server with two RTX A6000 (48 GB each). Another user's job ran on GPU 0 the whole time; we never touched it. Our server ran on GPU 1 only (`CUDA_VISIBLE_DEVICES` set to GPU 1's UUID).
- Yield rule (`bench/a6000/watchdog.sh`): poll `nvidia-smi` every 5 s. On a GPU we use, a compute process that is not ours, more than 300 MiB not held by our pids, one of our pids on the wrong GPU, or a box load above its 32 cores kills our server at once (literal pids: TERM, KILL after 3 s) and drops the tunnel. We restart only after 5 minutes clear (GPU 0: 10 minutes clear, since its owner's job may run in stages). A row cut by a yield is dropped and redone, so a yield never becomes a 763B call.
- Server (`bench/a6000/serve.sh`): Ollama `qwen3:30b-instruct` (Qwen3-30B-A3B, Q4_K_M, the product's 30B) and `gemma2:9b` (Q4_0), 16 parallel slots, 16k context each, flash attention, q8 KV cache, kept loaded. One model loaded at a time.
- Access: a Cloudflare quick tunnel to a bearer-token proxy (`bench/a6000/auth_proxy.py`; 401 without the token). The URL lives only in `.env` and the git-ignored scratch folder; it dies with each yield and at the end.
- Runs (`bench/run_a6000.py`, every call through `SpeculativeCascadeRouter.generate()`), all from the Mac over the tunnel:
  - **PLAIN**: every item to the self-hosted model alone.
  - **POOL** (first pass, empty cache): Supabase cache (exact hash on the normalized prompt, then cosine >= 0.97 with the guard; own tenant per repeat) -> self-hosted model (confidence gate 0.95; prompts above complexity 0.6 go straight to the 763B) -> Crusoe `DeepSeek-V4.1-Flash` (763B). Code runs its tests on the 30B answer and a failing answer climbs to the 763B. Only answers that pass their tests (code) or the gate (plain Q&A) are cached.
  - **WARM**: the same items again on the cache its POOL repeat filled (repeat traffic).
- Data: the 300-question suite (`bench/datasets/suite.jsonl`: MMLU, Dolly, Quora pairs, HumanEval, MBPP, GSM8K) and the 301 cost-case coding tasks (`bench/cost_case/tasks.jsonl`). Gemma ran a fixed slice: 12 items per suite source plus 12 Quora pairs, and 25 cost-case tasks per difficulty.
- Grading: code by running its tests (sandboxed, no network), GSM8K by the number, MMLU by the letter, Dolly scored 1-5 by the 763B as judge (pass >= 4; it wrote some of the POOL answers, so Dolly POOL scores lean its way), Quora pairs by whether a hit returned the duplicate's answer.
- Prices: Crusoe list $0.29/M in, $1.20/M out (763B only, about $0.16 per 1,000 cost-case calls). The A6000 is owned hardware, priced $0 here.
- Streams ran in parallel (up to 12 at once on 16 slots), so latency is measured under that load.
- The 763B-only column is the earlier run on the same items (`results_suite.md`, `results_cost_case.md`); no new 763B-only run was made.

## Server speed (GPU 1)

| Model | Load (s) | Decode tok/s, 1 stream | Per stream, 16 streams | Total tok/s, 16 streams | Prompt tok/s | VRAM used on GPU 1 |
|---|---|---|---|---|---|---|
| qwen3:30b-instruct | 4.5 | 176 | 46 | 687 | 3265 | 31596 MiB |

Load time is from the disk cache right after download (a first load from cold disk is slower).

## qwen3:30b-instruct on the 300-question suite

Mean ± sd over repeats (repeats per mode: PLAIN 3, POOL 3).

| | 763B only (earlier run) | PLAIN | POOL |
|---|---|---|---|
| Items | 300 | 115 ± 2 | 107 ± 0 |
| Cache hits (exact + cosine) | 0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
| Cache hit rate % | 0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
| Answered by the self-hosted model | 0 | 115 ± 2 | 57.3 ± 1.2 |
| Answered by the 763B | 300 | 0.0 ± 0.0 | 49.7 ± 1.2 |
| 763B calls (incl. climbs) | 300 | 0.0 ± 0.0 | 49.7 ± 1.2 |
| Big-model calls cut % | 0 | 100 ± 0 | 53.6 ± 1.1 |
| Code answers that failed tests and climbed | - | 0.0 ± 0.0 | 5.7 ± 1.2 |
| 763B tokens | 103,067 | 0.0 ± 0.0 | 23,425 ± 675 |
| 763B $ (list price) | 0.1020 | 0.0 ± 0.0 | 0.0263 ± 0.0005 |
| Graded correct | 170/180 | 84.7 ± 2.9 | 89.3 ± 1.5 |
| Graded items | 180 | 100 ± 2 | 94.0 ± 0.0 |
| **Wrong answers served (graded)** | 10 | 15.3 ± 2.5 | 4.7 ± 1.5 |
| **Wrong answers from the cache** | 0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
| Latency p50 (ms) | 1,120 | 12,645 ± 284 | 13,037 ± 89 |
| Latency p90 (ms) | 4,451 | 42,529 ± 1,547 | 46,938 ± 238 |
| Wall time, first to last row (s) | - | 1,934 ± 8 | 1,932 ± 10 |
| Quora duplicates served from cache | - | 0.0 ± 0.0 | 0.0 ± 0.0 |

PLAIN answered by, per repeat: gpu-small 116; gpu-small 116; gpu-small 113.
POOL answered by, per repeat: cloud-deepseek 49, gpu-small 58; cloud-deepseek 49, gpu-small 58; cloud-deepseek 51, gpu-small 56.

## qwen3:30b-instruct on the 301 cost-case tasks

Mean ± sd over repeats (repeats per mode: PLAIN 3, POOL 3).

| | 763B only (earlier run) | PLAIN | POOL |
|---|---|---|---|
| Items | 301 | 263 ± 5 | 240 ± 3 |
| Cache hits (exact + cosine) | 0 | 0.0 ± 0.0 | 1.0 ± 0.0 |
| Cache hit rate % | 0 | 0.0 ± 0.0 | 0.4167 ± 0.0046 |
| Answered by the self-hosted model | 0 | 263 ± 5 | 208 ± 4 |
| Answered by the 763B | 301 | 0.0 ± 0.0 | 31.3 ± 1.2 |
| 763B calls (incl. climbs) | 301 | 0.0 ± 0.0 | 31.3 ± 1.2 |
| Big-model calls cut % | 0 | 100 ± 0 | 86.9 ± 0.6 |
| Code answers that failed tests and climbed | - | 0.0 ± 0.0 | 26.7 ± 0.6 |
| 763B tokens | 66,923 | 0.0 ± 0.0 | 12,641 ± 544 |
| 763B $ (list price) | 0.0489 | 0.0 ± 0.0 | 0.0098 ± 0.0006 |
| Graded correct | 286/301 | 232 ± 5 | 233 ± 3 |
| Graded items | 301 | 263 ± 5 | 240 ± 3 |
| **Wrong answers served (graded)** | 15 | 31.0 ± 1.0 | 7.3 ± 0.6 |
| **Wrong answers from the cache** | 0 | 0.0 ± 0.0 | 0.0 ± 0.0 |
| Latency p50 (ms) | 710 | 3,388 ± 61 | 3,769 ± 36 |
| Latency p90 (ms) | 1,338 | 17,782 ± 316 | 18,013 ± 511 |
| Wall time, first to last row (s) | - | 1,944 ± 7 | 1,941 ± 4 |

PLAIN answered by, per repeat: gpu-small 265; gpu-small 267; gpu-small 258.
POOL answered by, per repeat: cloud-deepseek 32, exact_cache 1, gpu-small 208; cloud-deepseek 32, exact_cache 1, gpu-small 204; cloud-deepseek 30, exact_cache 1, gpu-small 211.

## GPU yields

- None. No other process touched GPU 1 during the runs (watchdog log on the box).

Rows: `bench/.scratch/a6000/` (git-ignored, mirrored to the run folder on the box), csv `bench/.scratch/a6000/results_a6000.csv`.
Judge (763B) calls: qwen: 28 calls, 74,704 tokens.

