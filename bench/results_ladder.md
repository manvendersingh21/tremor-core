# Ladder benchmark: Mac 3B -> GPU Qwen3-30B -> Crusoe top model

> **Correction, 2026-11-16 ([`results_akash_tuning.md`](results_akash_tuning.md)).** Earlier reports, this one included, said the Akash V100 was shared and busy, and blamed it for the slow 30B calls. That was wrong. The GPU was ours, and no one else used it. The 30B was slow because the box gives our container 4 CPUs, while Ollama ran the model with 149 threads, so it decoded 20 tokens/s instead of 98. In some runs our own jobs on the same box (other chats, the speculative-decoding verifier) may also have queued calls or held GPU memory; that part is not proven. Tuned (`num_thread = 4`, then our own Ollama with flash attention, q8 KV cache, 4 slots, `keep_alive = -1`), the 30B passes 270/301 cost-case tasks (was 269/301) at a median 2.7 s per call (was 78.0 s) and $0.18 to $0.52 per 1,000 calls (was $11.02). The numbers below are kept as measured, before tuning.

30 prompts from `bench/prompts.jsonl`, one pass per mode. Real counts come from each server's usage field.

## Setup
| tier | model | size | price (per M tokens) |
|---|---|---|---|
| caches | exact SHA-256 + semantic MiniLM (cos >= 0.94) | - | free |
| 1 | Mac Qwen2.5-3B-Instruct Q4, llama.cpp, logprob gate 0.85 | 3B | free (own Mac) |
| 2 | GPU Ollama `qwen3:30b-instruct` (Q4_K_M, already running; `think:false`) | 30.5B (MoE) | free (own server) |
| 3 (T, L) | Crusoe `openai/gpt-oss-120b` (`reasoning_effort: low`) | 120.4B (published in /v1/models) | $0.05 in / $0.05 cached / $0.25 out |
| 4 = largest (T4, L4) | Crusoe `deepseek-ai/DeepSeek-V4.1-Flash` (`thinking: false`) | 763.2B | $0.29 in / $0.007 cached / $1.20 out |
| grader | Crusoe `Qwen/Qwen3.8-27B` (wrote no graded answer) | 27.8B | $0.25 / $0.15 / $2.00 |

Largest model on the key: DeepSeek-V4.1-Flash at 763.2B. No ~1T model is listed. Next: GLM-5.3 at 753.3B ($1.40 in / $4.40 out), GLM-5.3-Flash 321.3B, Nemotron-3.5-Super-VL 124.5B. Sizes are Crusoe's `parameter_count`; the MoE active size is not given except Nemotron (12B active).
Tunnel: GPU Ollama via `ssh -L 127.0.0.1:LOCAL_PORT:127.0.0.1:11434`.

Climb rules: 3B stays if mean token prob >= 0.85 (and asserts pass, when the prompt has them). Semantic cache threshold 0.97; 3B answers under 0.95 confidence are served but not cached. Every GPU call has a 90 s timeout, then the prompt climbs to the top. No brief unless the mode is Lb. Else the 30B answers. The 30B answer goes up if its self-check says ESCALATE or the asserts fail. Prompts with `complexity_score >= 0.6` skip both small answers: the 30B writes a brief of at most 200 tokens and the top model answers.

## T (top only) vs L (ladder)
| mode | top calls | top tokens (in/out) | top $ | median ms | p90 ms | GPU tokens |
|---|---|---|---|---|---|---|
| T | 30/30 | 14741 (3096/11645) | $0.00307 | 880 | 3865 | 0 |
| L | 6/30 | 8087 (1037/7050) | $0.00181 | 2205 | 46164 | 1312 |
| Lb | 4/6 | 5394 (1612/3782) | $0.00103 | 21622 | 109712 | 5156 |
| T4 | 30/30 | 6365 (1230/5135) | $0.00652 | 727 | 2615 | 0 |
| L4 | 4/30 | 2192 (546/1646) | $0.00213 | 1851 | 16006 | 4182 |

L vs T: top tokens saved 6654 (45.1%), top $ saved $0.00125 (40.8%).
T4/L4 use deepseek-ai/DeepSeek-V4.1-Flash as top. L4 vs T4: top tokens saved 4173 (65.6%), top $ saved $0.00439 (67.3%).
GPU/Mac tokens are not priced (own hardware). Grader used 0.00648 $ and 24272 tokens; total Crusoe tokens this benchmark: 61051.

## Which tier answered (L)
{'local': 17, 'gpu': 3, 'exact_cache': 3, 'semantic_cache': 1, 'top': 6}
L4: {'local': 19, 'gpu': 3, 'exact_cache': 3, 'semantic_cache': 1, 'top': 4}

## Quality
Pass counts (asserts for code_small, keyword match for the rest):

| type | T pass | L pass | T4 pass | L4 pass |
|---|---|---|---|---|
| code_small | 6/6 | 6/6 | 6/6 | 6/6 |
| easy | 9/10 | 10/10 | 10/10 | 10/10 |
| paraphrase | 4/5 | 5/5 | 5/5 | 5/5 |
| repeat | 3/3 | 3/3 | 3/3 | 3/3 |

Heavy code, blind 1-5 grade by Qwen/Qwen3.8-27B, answers shuffled per prompt:

| prompt | T | L | Lb | T4 | L4 |
|---|---|---|---|---|---|
| h1 | 2 | 1 | 4 | 3 | 5 |
| h2 | 5 | 5 | 4 | 5 | 4 |
| h3 | 3 | 4 | 2 | 3 | 5 |
| h4 | 5 | 5 | 5 | 4 | 4 |
| h5 | 4 | 4 | 3 | 5 | 5 |
| h6 | 4 | 5 | 3 | 5 | 2 |
| mean | 3.83 | 4.00 | 3.50 | 4.17 | 4.17 |

## Brief vs no brief (heavy prompts)
Like for like: the 4 heavy prompts that reached the top in both L and Lb (h1, h3, h4, h5). h2 and h6 are left out: L's 30B timed out on them (90 s) and climbed, while in Lb it answered in 47 s and 62 s and stayed on the GPU. The brief is at most 200 tokens, written by the 30B.

| 4 prompts | top in | top out | total latency ms | top $ |
|---|---|---|---|---|
| no brief (L) | 785 | 4184 | 16165 | $0.00109 |
| brief by 30B (Lb) | 1612 | 3782 | 70918 | $0.00103 |

The brief added 827 input tokens (about 200 per prompt) and cut 402 output tokens. Cost came out equal. Time rose 4.4x (each brief took 10 to 21 s on the GPU). Mean heavy grade over all 6 prompts: L 4.00, Lb 3.50 (grader is noisy, one grade per cell).

## Verdict
**Yes on top-model tokens and $. No on speed. Quality held.**

- **Token and $ saving.** Against gpt-oss-120b only (T vs L): top tokens 14,741 -> 8,087 (-45.1%), top $ 0.00307 -> 0.00181 (-40.8%). Against the 763B DeepSeek-V4.1-Flash only (T4 vs L4): top tokens 6,365 -> 2,192 (-65.6%), top $ 0.00652 -> 0.00213 (-67.3%). The dearer the top model, the more the ladder saves in dollars. The 120B saving is small in dollars ($0.0012) because that model costs only $0.05/$0.25 per million tokens. Savings were smaller than the last run (69.7%) for L: the GPU 30B timed out on h2 and h6, so both climbed.
- **Who answered (L).** 3B 17, exact cache 3, semantic cache 1, GPU 30B 3, top 6. L4: 3B 19, caches 4, GPU 3, top 4.
- **Quality.** Every code_small assert passed in all modes (6/6). Easy, paraphrase and repeat prompts passed 100% in L, T4 and L4. T missed one easy and one paraphrase prompt (gpt-oss answered without the expected keyword). Cache fix worked: exact cache r1-r3 correct, p4 now misses the cache (threshold 0.97) and is answered by the GPU 30B correctly, and no cached answer was wrong. Mean heavy grade (noisy): T 3.83, L 4.00, T4 4.17, L4 4.17, Lb 3.50. The ladder is not worse than top-only on this sample.
- **Brief.** A 30B brief is not worth it: same cost, 4.4x slower. Send heavy prompts straight up (now the default, `use_brief=False`).
- **Speed.** The ladder is slower. L median 2.2 s vs T 0.9 s; L p90 46 s vs 3.9 s. All the slow calls are the GPU 30B (25 to 90 s per call), because the server is shared and Ollama queues calls. With a 90 s timeout, the 2 stalls (h2, h6) cost 90 s and then went to the top. Stall location: the time is spent inside the 30B call (`mid_ms` in the CSV), not in the Mac 3B (0.3 to 5 s) or Crusoe (0.4 to 3 s). An idle server (a lone call took 1.5 s) answers fast, so the stall is queueing, not the model.
- **Not proven.** One pass per mode, 30 prompts, 6 heavy. The grader is a model, not a human. Self-check by the 30B decided "OK" for 3 prompts and was not independently verified. Real Crusoe use: 61k tokens.

## Rerun
```
bench/serve_local.sh &        # Mac 3B on 127.0.0.1:8080
ssh -N -f -L 127.0.0.1:LOCAL_PORT:127.0.0.1:11434 <gpu-host>
.venv/bin/python bench/run_ladder.py T && .venv/bin/python bench/run_ladder.py L
.venv/bin/python bench/run_ladder.py Lb && .venv/bin/python bench/run_ladder.py T4 && .venv/bin/python bench/run_ladder.py L4
.venv/bin/python bench/run_ladder.py report   # delete $KIROCREW_SCRATCH/ladder_grades.json to regrade
```
Raw rows: `bench/results_ladder.csv`.
