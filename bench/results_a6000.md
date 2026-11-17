# Owned-hardware proof: cache + answer check on a shared RTX A6000 box (free GPUs only, yield to anyone)

## Verdict

- **qwen3:30b-instruct: cache + answer check cut 70.7% of big-model calls with 0 wrong answers from the cache on owned hardware** (8 first-pass runs over both sets, 2404 items, against sending every item to the 763B). Asked the same items again, the cache answered 586 of 601 and big-model calls fell 97.5%; the cache caused 1 wrong answer(s) there.
- **gemma2:9b: cache + answer check cut 40.5% of big-model calls with 0 wrong answers from the cache on owned hardware** (6 first-pass runs over both sets, 477 items, against sending every item to the 763B). Asked the same items again, the cache answered 156 of 159 and big-model calls fell 98.1%; the cache caused 0 wrong answer(s) there.

What held, with the 30B (the product's model), mean of 4 first-pass repeats:

| | 763B only | Plain 30B | Ladder (cache + 30B + check) |
|---|---|---|---|
| Cost case: 763B calls of 301 | 301 | 0 | **37.5** |
| Cost case: correct of 301 | 286 | 267 | **292** |
| Cost case: 763B $ per 1,000 calls | $0.162 | $0 | **$0.036** |
| Suite: 763B calls of 300 | 300 | 0 | **138** |
| Suite: correct of 180 (no Dolly) | 170 | 159 | **173** |
| Suite: 763B $ per 1,000 calls | $0.340 | $0 | **$0.256** |
| Same items again: 763B calls of 601 | 601 | 0 | **15** |

- **The answer check is what made the 30B safe to use.** The plain 30B served 34 wrong answers on each set. The ladder
  served 9.5 (cost case) and 12.5 (suite, Dolly included). 31 of 301 cost-case answers failed their tests on the 30B and
  climbed to the 763B, and the ladder passed more tasks than the 763B alone (292 vs 286): a failed test gets a second model.
- **The cache served no answer for a different question in any first pass** (0 in 8 runs), and only 3 of 24 Quora
  duplicates at cosine 0.97 (2 of 24 in `results_backend_v3.md`). The first-pass savings come from the 30B plus the check.
  The cache pays on repeats: asked again, 586 of 601 items came from the cache in under 0.2 s (p50 147-186 ms), and
  763B calls fell 97.5%.
- **One wrong answer did come from the cache, from a product bug, now fixed.** `memory/safety.py` `scrub()` rewrote
  `f"Unexpected token: {tokens[pos]}"` to `[SECRET]` before the answer was stored, so a passing calculator (`multi-calc`)
  came back from the cache as code that does not run. Fix in `router.py`: an answer that `scrub()` would change is not
  cached; test `test_answer_that_scrub_would_rewrite_is_not_cached`.
- **The cache repeats a wrong answer the gate let through.** 8 suite items (5 Dolly, 2 MMLU with the 30B; 1 GSM8K with
  Gemma) were wrong on the first pass and the cache served the same wrong text again. Plain Q&A has no test, only the
  0.95 confidence gate, so this is the gate's error, kept. Code is cached only after its tests pass.
- **Gemma 2 9B (never tuned for this): the safety holds, the savings shrink.** 0 wrong answers from the cache, and
  correct went from 51 to 72 of 75 cost-case tasks. But its confidence is lower, so more items climb: 763B calls cut
  52.9% (cost slice) and 29.4% (suite slice), against 87.5% and 53.8% for the 30B.

Failures, by name:
- **The ladder is slower than the 763B on a first pass.** p50 3.1 s vs 0.7 s (cost case) and 6.1 s vs 1.1 s (suite),
  p90 13.6 s and 26.3 s. These runs had 12 streams sharing one or two GPUs and every call crossed the internet tunnel.
  Only repeats are fast (cache p50 under 0.2 s).
- **Supabase ran out of client slots mid-run.** Its session pooler allows 15 clients; 18 streams with 4 connections each
  filled it, and 270 cache lookups fell back to the model (no wrong answer, the call just went on to the 30B). The three
  repeat-pass runs that started during it were set aside (`bench/.scratch/a6000/affected/`). The repeat-pass rows above
  are from a clean 4th repeat with one connection per stream; the first-pass hit counts were the same (3 suite, 1 cost)
  in all 4 repeats.
- The 763B-only column is the earlier run, not rerun here. Dolly is scored by the 763B, which also wrote some ladder
  answers, so the Dolly part of the suite leans its way; the no-Dolly row avoids that.
- The A6000 is priced $0. The $ columns are 763B tokens only.

## Setup

- Box: a shared server with two RTX A6000 (48 GB each). At the start another user's job held GPU 0, so we ran on GPU 1 only (`CUDA_VISIBLE_DEVICES` set to that GPU's UUID). When that job ended and GPU 0 had been empty for 10 minutes, the watchdog added a second server on GPU 0 (times under GPU yields). Their job was never touched.
- Yield rule (`bench/a6000/watchdog.sh`, current version): poll `nvidia-smi` every 5 s. If anyone else touches EITHER GPU while we hold any (a process that is not ours on our GPU, a new process on the other GPU, others' memory rising over 300 MiB, one of our pids on the wrong GPU, or box load above its 32 cores), every server of ours on both GPUs is killed at once (literal pids: TERM, KILL after 3 s) and the tunnel drops. We restart only after the whole box has been quiet for 5 minutes (GPU 0: 10 minutes empty first). A row cut by a yield is dropped and redone, so a yield never becomes a 763B call. The runs below used the earlier per-GPU version; no yield was needed either way. `bench/a6000/selftest.sh` checks the rule with a fake `nvidia-smi`.
- Server (`bench/a6000/serve.sh`): Ollama `qwen3:30b-instruct` (Qwen3-30B-A3B, Q4_K_M, the product's 30B) and `gemma2:9b` (Q4_0), 16 parallel slots, 16k context each, flash attention, q8 KV cache, kept loaded. One model loaded at a time.
- Access: a Cloudflare quick tunnel to a bearer-token proxy (`bench/a6000/auth_proxy.py`; 401 without the token). The URL lives only in `.env` and the git-ignored scratch folder; it dies with each yield and at the end.
- Runs (`bench/run_a6000.py`, every call through `SpeculativeCascadeRouter.generate()`), all from the Mac over the tunnel:
  - **PLAIN**: every item to the self-hosted model alone.
  - **POOL** (first pass, empty cache): Supabase cache (exact hash on the normalized prompt, then cosine >= 0.97 with the guard; own tenant per repeat) -> self-hosted model (confidence gate 0.95; prompts above complexity 0.6 go straight to the 763B) -> Crusoe `DeepSeek-V4.1-Flash` (763B). Code runs its tests on the 30B answer and a failing answer climbs to the 763B. Only answers that pass their tests (code) or the gate (plain Q&A) are cached.
  - **WARM**: the same items again on the cache its POOL repeat filled (repeat traffic).
- Data: the 300-question suite (`bench/datasets/suite.jsonl`: MMLU, Dolly, Quora pairs, HumanEval, MBPP, GSM8K) and the 301 cost-case coding tasks (`bench/cost_case/tasks.jsonl`). Gemma ran a fixed slice: 12 items per suite source plus 12 Quora pairs, and 25 cost-case tasks per difficulty.
- Grading: code by running its tests (sandboxed, no network), GSM8K by the number, MMLU by the letter, Dolly scored 1-5 by the 763B as judge (pass >= 4; it wrote some of the POOL answers, so Dolly POOL scores lean its way), Quora pairs by whether a hit returned the duplicate's answer.
- Prices: Crusoe list $0.29/M in, $1.20/M out (763B only, about $0.16 per 1,000 cost-case calls). The A6000 is owned hardware, priced $0 here.
- Streams ran in parallel (12 model-calling streams at once, 16 slots per server; one server until GPU 0 freed, then two), so latency is measured under that load and over the internet tunnel from the Mac.
- The 763B-only column is the earlier run on the same items (`results_suite.md`, `results_cost_case.md`); no new 763B-only run was made.

## Server speed (GPU 1)

| Model | Load (s) | Decode tok/s, 1 stream | Per stream, 16 streams | Total tok/s, 16 streams | Prompt tok/s | VRAM used on GPU 1 |
|---|---|---|---|---|---|---|
| qwen3:30b-instruct | 4.5 | 176 | 46 | 687 | 3265 | 31596 MiB |
| gemma2:9b | 3.9 | 92 | 43 | 635 | 1018 | 24480 MiB |

Load time is from the disk cache right after download (a first load from cold disk is slower).

## qwen3:30b-instruct on the 300-question suite

Mean ± sd over repeats (repeats per mode: PLAIN 3, POOL 4, WARM 1).

| | 763B only (earlier run) | PLAIN | POOL | WARM |
|---|---|---|---|---|
| Items | 300 | 300 ± 0 | 300 ± 0 | 300 |
| Cache hits (exact + cosine) | 0 | 0.0 ± 0.0 | 3.0 ± 0.0 | 294 |
| Cache hit rate % | 0 | 0.0 ± 0.0 | 1.0 ± 0.0 | 98 |
| Answered by the self-hosted model | 0 | 300 ± 0 | 158 ± 2 | 0 |
| Answered by the 763B | 300 | 0.0 ± 0.0 | 138 ± 2 | 6 |
| 763B calls (incl. climbs) | 300 | 0.0 ± 0.0 | 138 ± 2 | 6 |
| Big-model calls cut % | 0 | 100 ± 0 | 53.8 ± 0.6 | 98 |
| Code answers that failed tests and climbed | - | 0.0 ± 0.0 | 12.2 ± 1.0 | 4 |
| 763B tokens | 103,067 | 0.0 ± 0.0 | 68,140 ± 1,248 | 1,213 |
| 763B $ (list price) | 0.1020 | 0.0 ± 0.0 | 0.0767 ± 0.0014 | 0.000955 |
| Graded correct | 170/180 | 206 ± 5 | 228 ± 2 | 227 |
| Graded items | 180 | 240 ± 0 | 240 ± 0 | 240 |
| **Wrong answers served (graded)** | 10 | 34.0 ± 5.3 | 12.5 ± 1.9 | 13 |
| Wrong-answer rate % (of graded) | 5.6 | 14.2 ± 2.2 | 5.2 ± 0.8 | 5.42 |
| Graded correct without Dolly (same items as the 763B column) | 170/180 | 159 ± 2 | 173 ± 1 | 173 |
| **Wrong answers caused by the cache** (other question, or stored text changed) | 0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 0 |
| Wrong first-pass answers the cache repeated | - | 0.0 ± 0.0 | 0.0 ± 0.0 | 8 |
| Latency p50 (ms) | 1,120 | 7,404 ± 1,295 | 6,079 ± 2,634 | 186 |
| Latency p90 (ms) | 4,451 | 28,006 ± 1,198 | 26,324 ± 9,760 | 218 |
| Wall time, first to last row (s) | - | 3,502 ± 257 | 3,152 ± 1,179 | 129 |
| Quora duplicates served from cache (of 24) | - | 0.0 ± 0.0 | 3.0 ± 0.0 | 0 |

PLAIN answered by, per repeat: gpu-small 300; gpu-small 300; gpu-small 300.
POOL answered by, per repeat: cloud-deepseek 139, gpu-small 158, semantic_cache 3; cloud-deepseek 139, gpu-small 158, semantic_cache 3; cloud-deepseek 140, gpu-small 157, semantic_cache 3; cloud-deepseek 136, gpu-small 161, semantic_cache 3.
WARM answered by, per repeat: cloud-deepseek 6, exact_cache 291, semantic_cache 3.

## qwen3:30b-instruct on the 301 cost-case tasks

Mean ± sd over repeats (repeats per mode: PLAIN 3, POOL 4, WARM 1).

| | 763B only (earlier run) | PLAIN | POOL | WARM |
|---|---|---|---|---|
| Items | 301 | 301 ± 0 | 301 ± 0 | 301 |
| Cache hits (exact + cosine) | 0 | 0.0 ± 0.0 | 1.0 ± 0.0 | 292 |
| Cache hit rate % | 0 | 0.0 ± 0.0 | 0.3322 ± 0.0000 | 97 |
| Answered by the self-hosted model | 0 | 301 ± 0 | 262 ± 2 | 0 |
| Answered by the 763B | 301 | 0.0 ± 0.0 | 37.5 ± 1.9 | 9 |
| 763B calls (incl. climbs) | 301 | 0.0 ± 0.0 | 37.5 ± 1.9 | 9 |
| Big-model calls cut % | 0 | 100 ± 0 | 87.5 ± 0.6 | 97 |
| Code answers that failed tests and climbed | - | 0.0 ± 0.0 | 31.0 ± 0.8 | 8 |
| 763B tokens | 66,923 | 0.0 ± 0.0 | 14,108 ± 1,094 | 4,572 |
| 763B $ (list price) | 0.0489 | 0.0 ± 0.0 | 0.0109 ± 0.0011 | 0.00377 |
| Graded correct | 286/301 | 267 ± 1 | 292 ± 2 | 291 |
| Graded items | 301 | 301 ± 0 | 301 ± 0 | 301 |
| **Wrong answers served (graded)** | 15 | 34.0 ± 1.0 | 9.5 ± 1.7 | 10 |
| Wrong-answer rate % (of graded) | 5.0 | 11.3 ± 0.3 | 3.2 ± 0.6 | 3.32 |
| **Wrong answers caused by the cache** (other question, or stored text changed) | 0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 1 |
| Wrong first-pass answers the cache repeated | - | 0.0 ± 0.0 | 0.0 ± 0.0 | 0 |
| Latency p50 (ms) | 710 | 3,414 ± 54 | 3,122 ± 1,241 | 147 |
| Latency p90 (ms) | 1,338 | 16,890 ± 631 | 13,584 ± 6,037 | 182 |
| Wall time, first to last row (s) | - | 2,145 ± 28 | 1,860 ± 783 | 157 |

PLAIN answered by, per repeat: gpu-small 301; gpu-small 301; gpu-small 301.
POOL answered by, per repeat: cloud-deepseek 37, exact_cache 1, gpu-small 263; cloud-deepseek 39, exact_cache 1, gpu-small 261; cloud-deepseek 35, exact_cache 1, gpu-small 265; cloud-deepseek 39, exact_cache 1, gpu-small 261.
WARM answered by, per repeat: cloud-deepseek 9, exact_cache 292.

## gemma2:9b on the 300-question suite (slice)

Mean ± sd over repeats (repeats per mode: PLAIN 3, POOL 3, WARM 1).

| | 763B only (earlier run) | PLAIN | POOL | WARM |
|---|---|---|---|---|
| Items | 84 | 84.0 ± 0.0 | 84.0 ± 0.0 | 84 |
| Cache hits (exact + cosine) | 0 | 0.0 ± 0.0 | 1.0 ± 0.0 | 83 |
| Cache hit rate % | 0 | 0.0 ± 0.0 | 1.2 ± 0.0 | 98.8 |
| Answered by the self-hosted model | 0 | 84.0 ± 0.0 | 23.7 ± 3.2 | 0 |
| Answered by the 763B | 84 | 0.0 ± 0.0 | 59.3 ± 3.2 | 1 |
| 763B calls (incl. climbs) | 84 | 0.0 ± 0.0 | 59.3 ± 3.2 | 1 |
| Big-model calls cut % | 0 | 100 ± 0 | 29.4 ± 3.8 | 98.8 |
| Code answers that failed tests and climbed | - | 0.0 ± 0.0 | 3.7 ± 1.5 | 0 |
| 763B tokens | 33,948 | 0.0 ± 0.0 | 27,702 ± 523 | 163 |
| 763B $ (list price) | 0.0348 | 0.0 ± 0.0 | 0.0297 ± 0.0005 | 9.91e-05 |
| Graded correct | 46/48 | 45.3 ± 0.6 | 57.0 ± 1.0 | 58 |
| Graded items | 48 | 60.0 ± 0.0 | 60.0 ± 0.0 | 60 |
| **Wrong answers served (graded)** | 2 | 14.7 ± 0.6 | 3.0 ± 1.0 | 2 |
| Wrong-answer rate % (of graded) | 4.2 | 24.4 ± 1.0 | 5.0 ± 1.7 | 3.33 |
| Graded correct without Dolly (same items as the 763B column) | 46/48 | 36.3 ± 0.6 | 45.0 ± 1.0 | 46 |
| **Wrong answers caused by the cache** (other question, or stored text changed) | 0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 0 |
| Wrong first-pass answers the cache repeated | - | 0.0 ± 0.0 | 0.0 ± 0.0 | 1 |
| Latency p50 (ms) | 1,370 | 14,514 ± 658 | 14,515 ± 746 | 205 |
| Latency p90 (ms) | 4,811 | 35,250 ± 1,310 | 41,392 ± 1,404 | 235 |
| Wall time, first to last row (s) | - | 1,479 ± 20 | 1,568 ± 17 | 43 |
| Quora duplicates served from cache (of 10) | - | 0.0 ± 0.0 | 1.0 ± 0.0 | 0 |

PLAIN answered by, per repeat: gpu-small 84; gpu-small 84; gpu-small 84.
POOL answered by, per repeat: cloud-deepseek 58, gpu-small 25, semantic_cache 1; cloud-deepseek 57, gpu-small 26, semantic_cache 1; cloud-deepseek 63, gpu-small 20, semantic_cache 1.
WARM answered by, per repeat: cloud-deepseek 1, exact_cache 82, semantic_cache 1.

## gemma2:9b on the 301 cost-case tasks (slice)

Mean ± sd over repeats (repeats per mode: PLAIN 3, POOL 3, WARM 1).

| | 763B only (earlier run) | PLAIN | POOL | WARM |
|---|---|---|---|---|
| Items | 75 | 75.0 ± 0.0 | 75.0 ± 0.0 | 75 |
| Cache hits (exact + cosine) | 0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 73 |
| Cache hit rate % | 0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 97.3 |
| Answered by the self-hosted model | 0 | 75.0 ± 0.0 | 39.7 ± 2.9 | 0 |
| Answered by the 763B | 75 | 0.0 ± 0.0 | 35.3 ± 2.9 | 2 |
| 763B calls (incl. climbs) | 75 | 0.0 ± 0.0 | 35.3 ± 2.9 | 2 |
| Big-model calls cut % | 0 | 100 ± 0 | 52.9 ± 3.8 | 97.3 |
| Code answers that failed tests and climbed | - | 0.0 ± 0.0 | 16.7 ± 1.2 | 1 |
| 763B tokens | 18,627 | 0.0 ± 0.0 | 11,004 ± 1,236 | 629 |
| 763B $ (list price) | 0.0137 | 0.0 ± 0.0 | 0.0080 ± 0.0010 | 0.000512 |
| Graded correct | 73/75 | 51.3 ± 1.5 | 72.0 ± 1.0 | 73 |
| Graded items | 75 | 75.0 ± 0.0 | 75.0 ± 0.0 | 75 |
| **Wrong answers served (graded)** | 2 | 23.7 ± 1.5 | 3.0 ± 1.0 | 2 |
| Wrong-answer rate % (of graded) | 2.7 | 31.6 ± 2.0 | 4.0 ± 1.3 | 2.67 |
| **Wrong answers caused by the cache** (other question, or stored text changed) | 0 | 0.0 ± 0.0 | 0.0 ± 0.0 | 0 |
| Wrong first-pass answers the cache repeated | - | 0.0 ± 0.0 | 0.0 ± 0.0 | 0 |
| Latency p50 (ms) | 774 | 8,642 ± 171 | 8,978 ± 341 | 146 |
| Latency p90 (ms) | 1,437 | 39,603 ± 7,328 | 38,948 ± 2,920 | 185 |
| Wall time, first to last row (s) | - | 1,106 ± 85 | 1,154 ± 37 | 79.3 |

PLAIN answered by, per repeat: gpu-small 75; gpu-small 75; gpu-small 75.
POOL answered by, per repeat: cloud-deepseek 37, gpu-small 38; cloud-deepseek 37, gpu-small 38; cloud-deepseek 32, gpu-small 43.
WARM answered by, per repeat: cloud-deepseek 2, exact_cache 73.

## Minor result: same-box speculative decoding (one run)

`bench/a6000/spec_job.sh`: llama.cpp on GPU 1 alone, the same Q4_K_M 30B file, greedy, 256 tokens, one request at a time, 48 cost-case prompts (16 per difficulty). Draft: `qwen3:1.7b` (same tokenizer), up to 16 draft tokens per step.

| | 30B alone | 30B + 1.7B draft |
|---|---|---|
| Decode tok/s (median) | 183 | 119 |
| Time for all 48 prompts (s) | 30.6 | 43.6 |
| Draft tokens accepted | - | 4,611 of 8,900 (52%) |
| Same text as the 30B alone, word for word | - | 42 of 48 |

The draft made the 30B **1.53x slower** (0.65x speed). The 30B is a mixture of experts with about 3B active weights per token, so a 1.7B draft saves little per step and its rejected tokens cost a full verify. 6 of 48 answers drifted from the plain run (greedy on both; batch-size numeric differences, not a draft bug). This supports keeping speculative decoding out of the product path; the savings come from the cache and the answer check.

## GPU yields

- None. No other process touched a GPU we were using (watchdog log on the box).

Our server starts and stops (box time, EST):

- started GPU 1 at 2026-11-17T04:19:17-05:00
- started GPU 0 at 2026-11-17T05:09:43-05:00
- stopped GPU 0 at 2026-11-17T06:04:52-05:00 (want=stop)
- stopped GPU 1 at 2026-11-17T06:04:53-05:00 (want=stop)

Rows: `bench/.scratch/a6000/` (git-ignored, mirrored to the run folder on the box), csv `bench/.scratch/a6000/results_a6000.csv`.

## Crusoe 763B spend for this report

| Use | Calls | Tokens | $ (list) |
|---|---|---|---|
| Climbs from the self-hosted model (all runs, all repeats) | 1,006 | 451,687 | 0.4687 |
| Judge for Dolly answers (no runnable test) | 99 | 208,385 | 0.0630 |
| **Total** | 1,105 | 660,072 | **0.5317** |


