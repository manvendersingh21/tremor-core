# Self-hosted 30B on the V100: why it was slow, and the tuned setup

Date: 2026-11-16. Model: Ollama `qwen3:30b-instruct` (Qwen3-30B-A3B-Instruct-2507, Q4_K_M, 18 GB), thinking off,
`logprobs` on (the product's confidence gate), max 1,536 output tokens. Box: Tesla V100-PCIE-32GB, reached over an SSH
tunnel to your GPU box. Runner: `bench/cost_case/run_akash_tuning.py`. Rows: `bench/.scratch/akash_tuning/` (git-ignored).

## Verdict

- **The slowness was CPU threads, not a shared GPU.** The GPU held nothing else, and the 30B was fully on it.
  The box's container gets a 4-CPU quota, while Ollama starts its runner with threads for the host's cores
  (the runner had 149 threads). Setting `num_thread = 4` raised decode speed from 20 to 98 tokens per second.
- **Winning config:** our own Ollama 0.40.16 in `/root/chimera-llm` (`bench/akash/chimera_ollama.sh`): flash attention on,
  q8_0 KV cache, 4 parallel slots, `keep_alive = -1`, plus `num_thread = 4` per call from `chimera.toml`.
- **All 301 cost-case tasks on the winner, 4 calls at once:** 270/301 pass (cost case: 269/301), median 2.7 s per call
  (cost case: 78.0 s), 98.8 tokens/s across all calls, **$0.18 to $0.52 per 1,000 calls** (cost case: $11.02).
- One call at a time the 30B now answers in a median 1.5 s on the 20 tasks.

## Setup

- Tasks: the fixed stratified 20 of `bench/cost_case/tasks.jsonl` (5 trivial, 10 everyday, 5 hard), graded by running the code.
  Run one at a time (conc 1), then 4 at once (conc 4). The winner was then run on all 301 tasks.
- One untimed warm-up call per run loads the model. Grading runs after generation, so it never counts as GPU time.
- "decode tok/s per call" is the server's own `eval_count / eval_duration`, median over calls. "tok/s all calls" is all
  output tokens divided by the run's wall time.
- $ per 1,000 calls = box price per hour x wall seconds of the run / calls x 1,000. It assumes the box is kept busy;
  idle hours are not included. Prices: $0.52 and $1.53 per hour.
- Each config ran once. Sampling is at Ollama's default temperature (0.7), so 20-task pass counts move by about 2
  between identical runs (`base2` and `base3` matched on only 9 to 10 of 20 answers byte for byte). That is why the
  pass rate was checked on all 301 tasks.

## Diagnosis (read-only)

| What | Found |
|---|---|
| GPU processes | none before the test; 0 MiB of 32,768 MiB in use |
| 30B placement | `size_vram` = `size` = 19.4 GB: all layers on the GPU (`num_gpu` needs no change) |
| Existing Ollama | 0.40.14, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_CONTEXT_LENGTH=8192`, `OLLAMA_MAX_LOADED_MODELS=2`, default keep_alive (5 min) |
| CPU | container quota 4 CPUs (`cpu.max 400000 100000`); the host shows 96. Load average 8 to 13. Other jobs on the box used about 3 CPUs |
| Runner threads | 149 threads in the 30B's runner |
| Throttling | `nr_throttled` 740,189 of 10,114,668 periods (7%) since the container started |
| Cold load | 37 s for the 30B |

The existing Ollama server belongs to another app's folder on the box, so it was not restarted or changed. Only
per-call options and an unload of the 30B (`keep_alive: 0`) were sent to it. Our own server runs from its own folder,
with its own copy of the same model (same id `19e422b02313`).

## Before and after (20 tasks)

| Config | Conc | Pass | p50 s | p90 s | Decode tok/s per call | Tok/s all calls | Wall s | $ per 1k calls ($0.52 / $1.53 per hr) |
|---|---|---|---|---|---|---|---|---|
| base: existing server, defaults (our own model download was running) | 1 | 19/20 | 7.6 | 39.6 | 14.5 | 10.5 | 300.6 | $2.17 / $6.39 |
| base2: existing server, defaults | 1 | 19/20 | 4.3 | 27.3 | 20.0 | 17.9 | 177.5 | $1.28 / $3.77 |
| base3: same again, after the thread tests | 1 | 19/20 | 4.7 | 31.8 | 20.0 | 16.0 | 195.4 | $1.41 / $4.15 |
| base3 | 4 | 17/20 | 24.1 | 83.6 | 20.0 | 18.5 | 170.1 | $1.23 / $3.62 |
| t4: existing server, `num_thread` 4 | 1 | 17/20 | 1.5 | 6.7 | 97.7 | 65.1 | 50.0 | $0.36 / $1.06 |
| t2: existing server, `num_thread` 2 | 1 | 17/20 | 1.5 | 6.7 | 98.0 | 64.8 | 48.8 | $0.35 / $1.04 |
| t4 | 4 | 18/20 | 5.4 | 18.2 | 97.8 | 81.5 | 38.2 | $0.28 / $0.81 |
| own-p4: own server, 4 slots, no flash attention, f16 KV | 1 | 17/20 | 1.7 | 7.4 | 86.2 | 58.3 | 56.0 | $0.40 / $1.19 |
| own-p4 | 4 | 17/20 | 3.6 | 29.3 | 23.2 | 70.5 | 46.0 | $0.33 / $0.98 |
| own-fa-p2: own server, 2 slots, flash attention, q8_0 KV | 1 | 16/20 | 2.1 | 7.6 | 84.6 | 53.4 | 59.2 | $0.43 / $1.26 |
| own-fa-p2 | 4 | 17/20 | 3.1 | 11.6 | 57.8 | 104.4 | 30.2 | $0.22 / $0.64 |
| **own-fa-p4: own server, 4 slots, flash attention, q8_0 KV (winner)** | 1 | 18/20 | 1.5 | 7.3 | 87.6 | 59.8 | 53.2 | $0.38 / $1.13 |
| **own-fa-p4 (winner)** | 4 | 18/20 | 2.4 | 16.0 | 34.8 | 112.8 | 30.0 | **$0.22 / $0.64** |

What each fix did:

| Fix | Effect |
|---|---|
| `num_thread` 4 (or 2) | decode 20 -> 98 tok/s, p50 4.3 -> 1.5 s. The main fix. base3 went back to 20 tok/s with default threads, so the thread count is the cause |
| all layers on GPU (`num_gpu`) | not needed: already 100% on the GPU |
| `keep_alive = -1` | removes the 37 s cold load after 5 idle minutes |
| 4 parallel slots | with flash attention: 81.5 -> 112.8 tok/s across 4 calls, p50 at 4 at once 5.4 -> 2.4 s. One call alone gets about 10% slower (98 -> 88 tok/s) |
| flash attention + q8_0 KV | needed for the slots to pay off: 4 slots without it gave 70.5 tok/s and p90 29.3 s |
| smaller `num_ctx` | not tried apart: prompts are under 400 tokens, and the 8,192 context already fits 4 slots on the GPU (19.8 GB used) |
| llama.cpp or vLLM server | not tried. Ollama 0.40.16 already runs llama.cpp's `llama-server` underneath. vLLM's current engine needs compute capability 8.0; the V100 is 7.0 |

## All 301 tasks on the winner (4 at once)

| Run | Trivial | Everyday | Hard | All | p50 s | p90 s | $ per 1k calls |
|---|---|---|---|---|---|---|---|
| Cost case 30B (`bench/results_cost_case.md`), one at a time | 99/101 | 108/120 | 62/80 | 269/301 = 89% | 78.0 | 127.2 | $11.02 at $0.50/hr |
| Tuned 30B, 4 at once | 99/101 | 108/120 | 63/80 | 270/301 = 90% | 2.7 | 11.2 | $0.18 at $0.52/hr, $0.52 at $1.53/hr |

Wall time 369.9 s for 301 calls, 0 errors. For scale, the same cost-case table lists the 763B (DeepSeek-V4.1-Flash)
at $0.16 per 1,000 calls (286/301) and GPT-5.5 at $4.02 (60 items). So a busy tuned V100 at $0.52/hr costs about the
same as the 763B per call, and 8 to 22 times less than GPT-5.5. It is not cheaper than the 763B, and an idle box still bills.

One product-path call after the switch (`bin/chimera ask`, leap-year function): the router picked `gpu-small`,
and the 30B call took 4.4 s for 310 output tokens.

## Why the cost case saw 78 s per call

Not proven. The cost case ran at 0.9 tok/s median, which is about 20 times slower than today's untuned baseline
(20 tok/s). So threads alone do not explain it. A likely extra cause: something else held GPU memory then (the
speculative-decoding verifier on this box kept 30 of 49 layers of a 30B on the GPU), which would push part of
Ollama's 30B onto the 4 CPUs. Nothing held the GPU today. Keep one 30B on the GPU at a time: if the old Ollama
server also loads its own copy, both copies (2 x 19.4 GB) do not fit in 32 GB.

## The RTX 4000 Ada x2 box ($1.34/hr, 2 x 20 GB)

It would not help speed. The Q4 30B with its KV cache (19.8 GB) does not fit on one 20 GB card, so it would be split
across both. A split model reads its weights card after card, and each RTX 4000 Ada has about 360 GB/s of memory
bandwidth against the V100's 900 GB/s. Decode would likely be slower. It costs more per hour than the low V100 price.
It only makes sense as a second box for more calls at once or as a spare. Not measured.

## How to run it

On the GPU box (our folder only):

```
/root/chimera-llm/chimera_ollama.sh install   # official Ollama build into /root/chimera-llm/ollama
/root/chimera-llm/chimera_ollama.sh start     # flash attention, q8_0 KV, 4 slots, keep_alive -1, own model store
/root/chimera-llm/chimera_ollama.sh pull      # qwen3:30b-instruct into /root/chimera-llm/models
```

On the Mac: set `CHIMERA_GPU_REMOTE` in `.env` to our server's address on the box, then `make gpu-keep`.
`chimera.toml` (and `chimera.example.toml`) carry `options = { num_thread = 4 }` and `keep_alive = -1` on `gpu-small`.
Undo: remove `CHIMERA_GPU_REMOTE` from `.env` and restart the tunnel; `chimera_ollama.sh stop` stops our server.

## Limits

- Each config ran once; the 20-task pass counts are within sampling noise of each other. The 301-task run is the quality check.
- The $ per 1,000 calls assumes a busy box. Other jobs on the box share the 4 CPUs, so numbers can move with their load.
- `num_ctx`, a 4-bit build smaller than Q4_K_M, and a plain llama.cpp server were not measured apart.
