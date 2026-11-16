# Real-dataset suite: TOP-only vs POOL

> **Correction, 2026-11-16 ([`results_akash_tuning.md`](results_akash_tuning.md)).** Earlier reports, this one included, said the Akash V100 was shared and busy, and blamed it for the slow 30B calls. That was wrong. The GPU was ours, and no one else used it. The 30B was slow because the box gives our container 4 CPUs, while Ollama ran the model with 149 threads, so it decoded 20 tokens/s instead of 98. In some runs our own jobs on the same box (other chats, the speculative-decoding verifier) may also have queued calls or held GPU memory; that part is not proven. Tuned (`num_thread = 4`, then our own Ollama with flash attention, q8 KV cache, 4 slots, `keep_alive = -1`), the 30B passes 270/301 cost-case tasks (was 269/301) at a median 2.7 s per call (was 78.0 s) and $0.18 to $0.52 per 1,000 calls (was $11.02). The numbers below are kept as measured, before tuning.

Single run, no repeats. Items: 300 of 300 in suite.jsonl. Quality is graded by tests, exact match or choice letter; Dolly rows (open QA) are scored 1-5 by the cheap GMI model `zai-org/GLM-5.3-Flash` (blind, both answers in one call), pass = score >= 4. Pair rows are not graded for quality; they feed the cache table.

## Setup

- TOP: every item to Crusoe `deepseek-ai/DeepSeek-V4.1-Flash` (763B, thinking off), through `SpeculativeCascadeRouter.generate()` with a one-tier pool, no semantic cache.
- POOL: Supabase cache (exact hash, then cosine >= 0.97, guard on; own tenant `eval-suite`, purged before and after) -> GPU `qwen3:30b-instruct` (Ollama on a V100, SSH tunnel to your GPU box, confidence gate 0.95) -> the same 763B. No Mac 3B (stopped by the owner) and no local cache. `gpu-large` (Modal H200) off. The earlier 116-row POOL run that had the 3B tier is not used; it is kept only as a reference file.
- Pool routing by `complexity_score` (gpu-small <= 0.6, top = all); a low-confidence or failed tier climbs. max_tokens 1024 on both. Prices are Crusoe list: $0.29/M in, $1.20/M out, no cached-token discount, owned hardware $0.
- Mac and GPU were shared with other workers during the run, so latency is indicative only.

## Datasets

| Source | Dataset | License | Rows used | Type | Grader |
|---|---|---|---|---|---|
| mmlu | cais/mmlu (6 subjects, test) | MIT | 60 | easy | choice |
| dolly | databricks/databricks-dolly-15k | CC-BY-SA-3.0 | 60 | easy | llm |
| qqp | nyu-mll/glue qqp (validation; stands in for Kaggle Quora pairs) | Quora terms via GLUE (license 'other', research use) | 60 | repeat | pair |
| humaneval | openai/openai_humaneval | MIT | 55 | code, hard | unit_test |
| mbpp | google-research-datasets/mbpp (sanitized, test) | CC-BY-4.0 | 35 | code | unit_test |
| gsm8k | openai/gsm8k (main, test) | MIT | 30 | hard | exact |

Kaggle was skipped (no credentials). GLUE QQP from Hugging Face stands in for the Quora pairs, here and in the cache eval.

## Totals

| | TOP | POOL |
|---|---|---|
| 763B calls | 300 | 123 |
| 763B tokens in / out | 23,828 / 79,239 | 3,154 / 60,360 |
| $ (list price) | 0.1020 | 0.0733 |
| Pass rate (graded items) | 222/238 (93%) | 214/238 (90%) |
| Latency median / p90 (ms) | 1120 / 4451 | 85974 / 136073 |
| Sum of latencies (s) | 570 | 26206 |
| Calls that errored | 0 | 0 |

**Top-model tokens saved: 38.4%. Dollars saved: 28.1%.** POOL answered by tier: {"gpu-small": 175, "cloud-deepseek": 123, "semantic_cache": 2}.

## Per source and type

| Group | n | Pass TOP | Pass POOL | Delta (pts) | 763B calls TOP/POOL | 763B tokens TOP/POOL | $ TOP/POOL | Median ms TOP/POOL | p90 ms TOP/POOL | POOL answered by |
|---|---|---|---|---|---|---|---|---|---|---|
| dolly/easy | 60 | 52/58 (90%) | 52/58 (90%) | +0 | 60/54 | 23,746/23,304 | 0.0277/0.0273 | 2812/101876 | 4612/145333 | {"cloud-deepseek": 54, "gpu-small": 6} |
| gsm8k/hard | 30 | 29/30 (97%) | 30/30 (100%) | +3 | 30/4 | 10,053/2,163 | 0.0092/0.0021 | 1200/86634 | 1831/123088 | {"gpu-small": 26, "cloud-deepseek": 4} |
| humaneval/code | 40 | 38/40 (95%) | 36/40 (90%) | -5 | 40/1 | 12,404/273 | 0.0095/0.0002 | 961/87280 | 1339/119271 | {"gpu-small": 39, "cloud-deepseek": 1} |
| humaneval/hard | 15 | 15/15 (100%) | 11/15 (73%) | -27 | 15/1 | 9,232/652 | 0.0071/0.0005 | 1521/104659 | 1847/140432 | {"gpu-small": 14, "cloud-deepseek": 1} |
| mbpp/code | 35 | 29/35 (83%) | 27/35 (77%) | -6 | 35/2 | 6,923/818 | 0.0046/0.0008 | 709/74951 | 952/112181 | {"gpu-small": 33, "cloud-deepseek": 2} |
| mmlu/easy | 60 | 59/60 (98%) | 58/60 (97%) | -2 | 60/3 | 4,637/223 | 0.0015/0.0001 | 533/67740 | 724/98003 | {"gpu-small": 57, "cloud-deepseek": 3} |
| qqp/repeat | 60 | n/a | n/a | n/a | 60/58 | 36,072/36,081 | 0.0424/0.0424 | 3978/97949 | 6063/144652 | {"cloud-deepseek": 58, "semantic_cache": 2} |
| ALL | 300 | 222/238 (93%) | 214/238 (90%) | -3 | 300/123 | 103,067/63,514 | 0.1020/0.0733 | 1120/85974 | 4451/136073 | {"gpu-small": 175, "cloud-deepseek": 123, "semantic_cache": 2} |

## Semantic cache on real Quora pairs

- Duplicate pairs: 24. Correct hits (B returned A's answer): 2 (8%). Hits that returned some other answer: 0.
- Non-duplicate pairs: 6. False hits: 0.
- Other rows (no real duplicate exists): 270. False hits: 0.

## Where the pool lost

- Graded items TOP passed and POOL failed: 12. The reverse: 4.
- Losses by (source, answering tier): humaneval via gpu-small: 8, mbpp via gpu-small: 3, mmlu via gpu-small: 1.
- Items where POOL was slower than TOP: 298 of 300.
- Escalated items pay for the failed lower-tier attempt in time: median POOL latency on items answered by the 763B was 102036 ms, against 3425 ms for TOP on the same items.

## Verdict

POOL cut 763B tokens by 38.4% and list-price dollars by 28.1% against TOP-only on this 300-item mix, and its pass rate moved by -3.4 points. Median latency went from 1120 ms to 85974 ms and p90 from 4451 ms to 136073 ms. The cache served 2 of 24 real duplicate questions and gave 0 wrong-source hits.

Failures and losses, by name:
- Quality: POOL lost 12 graded items that TOP passed (code: humaneval and mbpp via the 30B; one MMLU) and won 4. On the 15 hard HumanEval items POOL passed 11/15. The 30B's confidence gate does not catch wrong code: those answers passed the gate and were served.
- Latency is much worse: 298 of 300 items were slower than TOP. The Akash GPU was shared with other chats and queued, so the 30B calls took 40 to 140 s each (median 86 s). This number says the shared box was slow, not what a free GPU does; it was not re-measured on an idle GPU.
- Open chat does not stay on the 30B: most Dolly answers had low confidence and climbed to the 763B (54 of 60), so Dolly saved almost nothing. The savings come from MMLU, GSM8K and code.
- The cache barely mattered here: 2 hits in 300 items, because this mix has only 24 repeated questions. The 1,000-question Quora replay below is the real cache test. Its best safe setting (guard on, 0.97) still missed most paraphrases.
- Judge: GLM-5.3-Flash scored Dolly. Two Dolly items got no score (judge reply not parseable) and are left out of the pass rate. A cheap judge is a weaker grader than tests; the 52/58 versus 52/58 tie on Dolly is not strong evidence.
- One run, no repeats, 300 items. Differences of a few points (MMLU -2, MBPP -6) are within noise.
- Kaggle Quora data was not used; GLUE QQP from Hugging Face stands in.

## Per 1,000 requests (this mix)

This mix is 300 items, not real traffic: 1/5 of it is MMLU, 1/5 Dolly, 1/5 Quora pairs, the rest code and math. Numbers are the run's totals scaled by 1000/300.

| Per 1,000 requests | TOP only | POOL |
|---|---|---|
| Answered without a 763B call | 0 | 590 |
| 763B tokens (in + out) | 343,557 | 211,713 |
| 763B dollars at list price | $0.340 | $0.244 |
| Wrong cache hits | 0 | 0.0 |
| Items TOP passed and POOL failed | 0 | 40.0 |

Eval log: 660 rows (both runs and every judge call) in `bench/.scratch/eval_log.jsonl`, imported with `bin/chimera evals import`.

## Token savings: what this means for users

Dataset: Quora Question Pairs via GLUE QQP train (Hugging Face). 1000 real Quora questions replayed in arrival order, 181 of them repeat a question (same meaning) that came before, so 18% is the most any cache could serve. Duplicate labels come from the dataset. A hit is **wrong** when the cached question is not a labelled duplicate of the new one.

Money is priced at DeepSeek-V4.1-Flash list ($0.29/M in, $1.20/M out). Prompt tokens are counted with the real DeepSeek-V4.1-Flash tokenizer; each avoided answer counts 171 tokens (the median answer in the TOP run). Only correct hits count as savings. Every cache hit also skips the Mac, GPU and cloud tiers, so those numbers are questions answered without any GPU.

### Quora Question Pairs via GLUE QQP train (Hugging Face): per 1,000 questions

| Cache | Guard | Threshold | Answered without a GPU | Of those, wrong | Wrong answers | Tokens saved | $ saved |
|---|---|---|---|---|---|---|---|
| Supabase pgvector (shared) | off | 0.94 | 58 | 17% | 10 | 8,710 | $0.0100 |
| Supabase pgvector (shared) | off | 0.97 | 31 | 13% | 4 | 4,894 | $0.0056 |
| Supabase pgvector (shared) | on | 0.94 | 44 | 9% | 4 | 7,258 | $0.0083 |
| Supabase pgvector (shared) | on | 0.97 | 24 | 4% | 1 | 4,167 | $0.0048 |

In plain words: with the guard on and threshold 0.97 the cache answers about 24 of every 1,000 questions without any GPU or cloud call and gets 1 of them wrong. It saves about 4,167 tokens and $0.0048 per 1,000 questions. The ceiling for this data is 181 per 1,000, so most real paraphrases are still missed. Hit rate depends on how often users repeat themselves; a Quora stream is a modest case.

Crusoe tokens used for this report: 166,581 (TOP run 103,067, POOL run 63,514, warm-up and retried calls excluded). Judge (GMI zai-org/GLM-5.3-Flash): 60 calls, 97,170 tokens.
