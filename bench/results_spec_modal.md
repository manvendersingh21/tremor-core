# Speculative decoding on Modal: a drafter box and a big verifier box, plus same-box methods

Single runs, no repeats except where named. Phase A (Qwen family, below 700B) is below. Phase B (other families) comes after it.

## Setup

- **Question.** Can a smaller model on its own GPU box (the "local machine") write tokens that a big model on another box (the "server") only checks, and is that faster than the big model alone? And how does it compare with speculative decoding inside the big model's own box?
- **Boxes.** Drafter: one Modal L40S running vLLM with the drafter model. Verifier: Modal H200s running vLLM with the big model (2 H200 for the 235B, 4 for the 480B and the 397B). Both use vLLM v0.33.0 (`vllm/vllm-openai:v0.33.0`), FP8 weights where the model ships them, prefix caching on, `--generation-config vllm` (no repo sampling defaults), thinking off.
- **Cross-box loop** (`bench/spec_modal_core.py`, run in the drafter box): the drafter writes K tokens with its own vLLM, sends the context and the K token ids to the big box (`/verify`, Modal's public HTTPS web endpoint, so every round is a real network round trip), and gets back how many were accepted plus the big model's next token. Greedy, so the output must equal the big model alone. The big box scores the draft with one forward pass (`prompt_logprobs`).
- **Spec+** (same loop, the parts of `inference/specplus.py` that apply to greedy decoding on real servers): adaptive K (`choose_k` fed with this run's measured acceptance and round times), pipelined drafting (the drafter writes the next block while the verify is on the wire, used only after a full accept), and free drafts copied from earlier in the context.
- **Same-box methods** (vLLM's own speculative decoding inside the big box): EAGLE-3 heads, n-gram prompt lookup, a small draft model, and Qwen3.5's built-in MTP. The big box restarts vLLM for each method; those restarts are cold starts and are reported apart.
- **Prompts.** 48 measured prompts, the same for every run: 28 code (10 trivial, 8 everyday and 4 hard from `bench/cost_case/tasks.jsonl`, 3 HumanEval and 3 MBPP from `bench/datasets/suite.jsonl`), 10 Dolly chat, 5 GSM8K, 5 MMLU. The Coder-480B runs use the 28 code prompts only. Two extra warm-up prompts run before every run and are not counted.
- **Fairness.** Temperature 0, max 256 new tokens, one request at a time. Every prompt starts with a cold prefix cache in every run (a cache salt per run and prompt); a spec run reuses only its own earlier rounds. tok/s = output tokens / wall time over all measured prompts, measured where the loop runs.
- **Warm GPUs.** Triton compiles some kernels on the first request of each new batch shape. In the smoke run one such compile (about 1 s) landed inside the first measured run and made "big alone" look 1.6x slower than it is. So every vLLM server now runs a warm-up before anything is measured (12 prompt lengths from 16 to 1,536 tokens, each extended by 1, 2, 4 and 8 tokens on its own cached prefix, plus the verify path and three longer decodes), and the compiled kernels are kept on the Modal volume. Cold starts and warm-ups are reported apart and are not in any tok/s number.
- **Lossless check.** Every spec run and every same-box method is compared token by token with the big model alone on all prompts. At each first different token, the big model's top-2 logprobs are read in one forward pass, to tell a near-tie between two GPU code paths from a bug. The big model alone is run twice to show its own run-to-run variation.
- **Tokenizers.** Every Qwen3 model here (4B to Coder-480B) has the same `tokenizer.json` (same SHA-256 on Hugging Face), so they can draft for each other. Qwen3.5 has its own tokenizer (248,320 tokens vs 151,936), so it is a separate chain. No open Qwen model is above 700B: the biggest Qwen3 is Coder-480B-A35B and the biggest Qwen3.5 is 397B-A17B. DeepSeek 763B on Crusoe has another tokenizer and its API rejects `echo`, so it cannot score drafts.
- **Code.** `deploy/modal/spec_modal.py` (boxes and jobs runner), `deploy/modal/spec_models.py` (models, modes, job plans), `deploy/modal/spec_download.py` (weights to Modal volumes, CPU only), `bench/run_spec_modal.py` (driver: runs one job, stops its app, saves `modal app list`; writes the tables below). Raw rows: `bench/.scratch/spec_modal/` (git-ignored).

## Phase A results

Three Modal accounts were used. Account A hit its spend limit before any GPU run. Account B ran the smoke test and most of the 235B job; its $30 of free credits ran out at 01:03 PST (the job stopped with "workspace is disabled"). Account C runs the rest. Every table below compares runs inside one account only, against that account's own "big alone" baseline, because the big box's GPUs and kernels can differ between accounts.

### Qwen3: 30B-A3B drafter, 235B-A22B verifier, account B (measured before its credits ran out)

<!-- tables:qa_235b -->
Speed, 48 prompts, greedy, max 256 new tokens, one request at a time (tok/s = all output tokens / all wall time; median = median of the per-prompt tok/s):

| Run | Who drafts -> who checks | Method | tok/s | median | vs big alone | code tok/s | chat tok/s | alpha (accepted / drafted) | tokens per round | same output as big alone |
|---|---|---|---|---|---|---|---|---|---|---|
| `a235_big_alone` | Qwen3-235B-A22B alone | no speculation | 89.8 | 87.0 |  | 87.2 | 99.0 |  |  |  |
| `a235_mid_alone` | Qwen3-30B-A3B alone (L40S) | no speculation | 129.7 | 128.2 | 1.44x | 125.1 | 136.2 |  |  |  |
| `a235_spec_k4` | Qwen3-30B-A3B (L40S) -> Qwen3-235B-A22B | plain spec, K=4 | 20.5 | 20.3 | 0.23x | 21.7 | 17.8 | 0.80 | 4.14 | 26/48 |
| `a235_specplus` | Qwen3-30B-A3B (L40S) -> Qwen3-235B-A22B | Spec+ (adaptive K, pipelined, free drafts) | 24.4 | 25.5 | 0.27x | 30.0 | 16.9 | 0.60 | 7.42 | 23/48 |
| `a235_spec_k8` | Qwen3-30B-A3B (L40S) -> Qwen3-235B-A22B | plain spec, K=8 | 22.7 | 24.3 | 0.25x | 25.5 | 17.2 | 0.67 | 6.22 | 30/48 |
| `a235_spec_k4_rtt100` | Qwen3-30B-A3B (L40S) -> Qwen3-235B-A22B | plain spec, K=4, +100 ms added per round | 14.0 | 14.3 | 0.16x | 15.4 | 11.9 | 0.80 | 4.14 | 26/48 |
| `a235_specplus_rtt100` | Qwen3-30B-A3B (L40S) -> Qwen3-235B-A22B | Spec+ (adaptive K, pipelined, free drafts), +100 ms added per round | 18.2 | 17.0 | 0.20x | 22.7 | 12.3 | 0.57 | 7.62 | 25/48 |
| `a235_big_eagle_q3_235b` | inside Qwen3-235B-A22B | same box: EAGLE-3 head | 162.2 | 157.0 | 1.80x | 164.8 | 159.7 | 0.63 (vLLM) | 2.88 (vLLM) | 27/48 |
| `a235_big_ngram` | inside Qwen3-235B-A22B | same box: n-gram (prompt lookup) | 100.6 | 84.8 | 1.12x | 106.8 | 88.4 | 0.09 (vLLM) | 1.38 (vLLM) | 48/48 |

Where a cross-box round goes (medians per round; network = round trip minus the big box's own time; full-scoring rounds = the cache-reading verify failed and the round was scored again from scratch):

| Run | rounds | draft ms | network ms | big box ms | round trip p50 / p90 ms | bare call (ping) p50 ms | mean K | full-scoring rounds | big box ms cached / full | tok/s at 20 ms network (projected) | tok/s at 0 ms (projected) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `a235_spec_k4` | 1567 | 47 | 59 | 41 | 102 / 306 | 46 | 4.0 | not traced |  | 25.5 | 29.1 |
| `a235_specplus` | 881 | 70 | 58 | 223 | 281 / 315 | 38 | 10.2 | not traced |  | 28.0 | 30.3 |
| `a235_spec_k8` | 1050 | 72 | 58 | 204 | 259 / 301 | 38 | 7.9 | not traced |  | 27.2 | 29.8 |
| `a235_spec_k4_rtt100` | 1567 | 46 | 157 | 40 | 199 / 389 | 44 | 4.0 | not traced |  | 26.7 | 30.6 |
| `a235_specplus_rtt100` | 854 | 76 | 160 | 223 | 383 / 410 | 45 | 11.2 | not traced |  | 27.5 | 29.7 |

Not measured in this account: `a235_big_draft_q3_4b` (stopped: the account's credits ran out), `a235_small_alone` (not reached), `a235_small_spec_k4` (not reached), `a235_small_specplus` (not reached), `a235_chain_alone` (not reached), `a235_chain_spec_k4` (not reached), `a235_chain_specplus` (not reached), `a235_mideagle_alone` (not reached), `a235_mideagle_specplus` (not reached), `a235_big_alone_rep` (not reached).

Hardware and cold starts (not in any number above): big box 4x H100 80GB HBM3, region us-east; drafter boxes 1x L40S, regions ['us-east']. Big box first answer 393 s after the job started (container, weights from the volume, vLLM start, warm-up, self-test; first vLLM start plain 350 s). Restarts for same-box modes: eagle_q3_235b 379 s, ngram 313 s. Drafter boxes boot: q3_30b 96 s. Job wall time 60 min.
<!-- /tables:qa_235b -->

### Qwen3: 4B and 30B-A3B drafters, 2-level chain, same-box draft model, 235B-A22B verifier, account C

<!-- tables:qb_235b -->
Speed, 0 prompts, greedy, max 256 new tokens, one request at a time (tok/s = all output tokens / all wall time; median = median of the per-prompt tok/s):

| Run | Who drafts -> who checks | Method | tok/s | median | vs big alone | code tok/s | chat tok/s | alpha (accepted / drafted) | tokens per round | same output as big alone |
|---|---|---|---|---|---|---|---|---|---|---|

Not measured in this account: `b235_big_alone` (not reached), `b235_chain_alone` (not reached), `b235_chain_spec_k4` (not reached), `b235_chain_specplus` (not reached), `b235_mid_alone` (not reached), `b235_small_alone` (not reached), `b235_small_spec_k4` (not reached), `b235_big_alone_rep` (not reached), `b235_big_draft_q3_4b` (not reached), `b235_big_eagle_q3_235b` (not reached), `b235_big_ngram` (not reached), `b235_spec_k4` (not reached), `b235_specplus` (not reached), `b235_small_specplus` (not reached), `b235_spec_k8` (not reached), `b235_mideagle_alone` (not reached), `b235_mideagle_specplus` (not reached).
<!-- /tables:qb_235b -->

### Qwen3-Coder-480B-A35B verifier (4 H200), code prompts only

<!-- tables:qa_480b -->
Speed, 0 prompts, greedy, max 256 new tokens, one request at a time (tok/s = all output tokens / all wall time; median = median of the per-prompt tok/s):

| Run | Who drafts -> who checks | Method | tok/s | median | vs big alone | code tok/s | chat tok/s | alpha (accepted / drafted) | tokens per round | same output as big alone |
|---|---|---|---|---|---|---|---|---|---|---|

Not measured in this account: `c480_big_alone` (not reached), `c480_mid_alone` (not reached), `c480_spec_k4` (not reached), `c480_specplus` (not reached), `c480_spec_k8` (not reached), `c480_spec_k4_rtt100` (not reached), `c480_specplus_rtt100` (not reached), `c480_big_eagle_q3c_480b` (not reached), `c480_big_ngram` (not reached), `c480_big_draft_q3_4b` (not reached), `c480_small_alone` (not reached), `c480_small_spec_k4` (not reached), `c480_small_specplus` (not reached), `c480_chain_alone` (not reached), `c480_chain_spec_k4` (not reached), `c480_chain_specplus` (not reached), `c480_coder_alone` (not reached), `c480_coder_spec_k4` (not reached), `c480_coder_specplus` (not reached), `c480_big_alone_rep` (not reached).
<!-- /tables:qa_480b -->

### Qwen3.5: 4B / 35B-A3B drafters, 397B-A17B verifier (4 H200)

<!-- tables:qa_397b -->
Speed, 0 prompts, greedy, max 256 new tokens, one request at a time (tok/s = all output tokens / all wall time; median = median of the per-prompt tok/s):

| Run | Who drafts -> who checks | Method | tok/s | median | vs big alone | code tok/s | chat tok/s | alpha (accepted / drafted) | tokens per round | same output as big alone |
|---|---|---|---|---|---|---|---|---|---|---|

Not measured in this account: `q397_big_alone` (not reached), `q397_mid_alone` (not reached), `q397_spec_k4` (not reached), `q397_specplus` (not reached), `q397_spec_k8` (not reached), `q397_spec_k4_rtt100` (not reached), `q397_specplus_rtt100` (not reached), `q397_big_mtp2` (not reached), `q397_big_eagle_q35_397b` (not reached), `q397_big_ngram` (not reached), `q397_big_draft_q35_4b` (not reached), `q397_small_alone` (not reached), `q397_small_spec_k4` (not reached), `q397_small_specplus` (not reached), `q397_chain_alone` (not reached), `q397_chain_spec_k4` (not reached), `q397_chain_specplus` (not reached), `q397_big_alone_rep` (not reached).
<!-- /tables:qa_397b -->

### Code-path check (smoke): Qwen3-30B-A3B as the "big" model on one L40S, Qwen3-4B drafts, 3 prompts, 48 tokens

<!-- tables:smoke -->
Speed, 3 prompts, greedy, max 48 new tokens, one request at a time (tok/s = all output tokens / all wall time; median = median of the per-prompt tok/s):

| Run | Who drafts -> who checks | Method | tok/s | median | vs big alone | code tok/s | chat tok/s | alpha (accepted / drafted) | tokens per round | same output as big alone |
|---|---|---|---|---|---|---|---|---|---|---|
| `s_big_alone` | Qwen3-30B-A3B alone | no speculation | 57.6 | 101.4 |  | 57.6 |  |  |  |  |
| `s_small_alone` | Qwen3-4B alone (L40S) | no speculation | 128.2 | 128.1 | 2.23x | 128.2 |  |  |  |  |
| `s_spec_k4` | Qwen3-4B (L40S) -> Qwen3-30B-A3B | plain spec, K=4 | 15.8 | 15.8 | 0.27x | 15.8 |  | 0.97 | 4.81 | 2/3 |
| `s_specplus` | Qwen3-4B (L40S) -> Qwen3-30B-A3B | Spec+ (adaptive K, pipelined, free drafts) | 25.8 | 25.4 | 0.45x | 25.8 |  | 0.89 | 8.12 | 2/3 |
| `s_rtt100` | Qwen3-4B (L40S) -> Qwen3-30B-A3B | plain spec, K=4, +100 ms added per round | 12.1 | 12.1 | 0.21x | 12.1 |  | 0.97 | 4.81 | 2/3 |
| `s_big_ngram` | inside Qwen3-30B-A3B | same box: n-gram (prompt lookup) | 80.4 | 77.3 | 1.40x | 80.4 |  | 0.02 (vLLM) | 1.09 (vLLM) | 2/3 |
| `s_big_eagle_q3_30b` | inside Qwen3-30B-A3B | same box: EAGLE-3 head | 97.1 | 94.6 | 1.68x | 97.1 |  | 0.73 (vLLM) | 3.20 (vLLM) | 2/3 |
| `s_big_draft_q3_4b` | inside Qwen3-30B-A3B | same box: Qwen3-4B draft model | 37.5 | 39.0 | 0.65x | 37.5 |  | 0.95 (vLLM) | 4.81 (vLLM) | 2/3 |

Where a cross-box round goes (medians per round; network = round trip minus the big box's own time; full-scoring rounds = the cache-reading verify failed and the round was scored again from scratch):

| Run | rounds | draft ms | network ms | big box ms | round trip p50 / p90 ms | bare call (ping) p50 ms | mean K | full-scoring rounds | big box ms cached / full | tok/s at 20 ms network (projected) | tok/s at 0 ms (projected) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `s_spec_k4` | 27 | 38 | 198 | 66 | 265 / 271 |  | 4.0 | not traced |  | 38.7 | 46.1 |
| `s_specplus` | 16 | 44 | 201 | 67 | 270 / 279 |  | 9.1 | not traced |  | 61.5 | 72.4 |
| `s_rtt100` | 27 | 37 | 296 | 66 | 362 / 369 |  | 4.0 | not traced |  | 38.9 | 46.4 |

Every output that differs from the big model alone, checked at its first different token: 6 cases. At 6 of them the big model's own top-1 token, scored in one forward pass, is the token the other run wrote, not the one big alone wrote. Top-1 minus top-2 logprob gap there (nats): [0.25, 0.25, 0.25, 0.25, 0.25, 0.25]; 6 of 6 are under 0.5.

Hardware and cold starts (not in any number above): big box L40S, region None; drafter boxes 1x L40S, regions []. Big box first answer 313 s after the job started (container, weights from the volume, vLLM start, warm-up, self-test; first vLLM start plain 155 s, ngram 132 s, eagle_q3_30b 156 s, draft_q3_4b 186 s, plain 74 s). Restarts for same-box modes: ngram 142 s, eagle_q3_30b 157 s, draft_q3_4b 187 s, plain 74 s. Drafter boxes boot: q3_4b 103 s. Job wall time 20 min.
<!-- /tables:smoke -->

## Phase A verdict

Coming after the runs.

## Cost and shutdown

Coming after the runs.
