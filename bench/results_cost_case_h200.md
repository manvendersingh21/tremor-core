# Cost case on a fast GPU: Qwen3-30B on a Modal H200 (vLLM, batched)

> **Correction, 2026-11-16 ([`results_akash_tuning.md`](results_akash_tuning.md)).** Earlier reports, this one included, said the Akash V100 was shared and busy, and blamed it for the slow 30B calls. That was wrong. The GPU was ours, and no one else used it. The 30B was slow because the box gives our container 4 CPUs, while Ollama ran the model with 149 threads, so it decoded 20 tokens/s instead of 98. In some runs our own jobs on the same box (other chats, the speculative-decoding verifier) may also have queued calls or held GPU memory; that part is not proven. Tuned (`num_thread = 4`, then our own Ollama with flash attention, q8 KV cache, 4 slots, `keep_alive = -1`), the 30B passes 270/301 cost-case tasks (was 269/301) at a median 2.7 s per call (was 78.0 s) and $0.18 to $0.52 per 1,000 calls (was $11.02). The numbers below are kept as measured, before tuning.

Question: the V100 run (`bench/results_cost_case.md`) found the 30B nearly as good as the 763B but about 70x the cost, because one V100 serves one request at a time (~78 s per call). Does a GPU that serves many requests at once change that?

Answer: yes for speed and cost per call. On the H200 the 30B costs $0.07 to $0.10 per 1,000 calls when the GPU is kept full, less than the 763B's $0.158. The quality gap is unchanged. The win exists only while the GPU is busy; an idle H200 costs $108.96 a day.

## Setup

- **Model:** `Qwen/Qwen3-30B-A3B-Instruct-2507`, BF16, the model family behind Ollama `qwen3:30b-instruct` (Ollama's build is quantized, so output is not byte-identical). This Instruct-2507 release has no thinking mode, so thinking is off.
- **Server:** vLLM v0.33.0 (the image the gpt-oss tier already used), one H200, prefix caching on, `--max-num-seqs 64`, max length 16,384. App `chimera-qwen30b`, `deploy/modal/vllm_qwen30b.py` (`make modal-qwen-up` / `modal-qwen-down`). The gpt-oss app was not touched.
- **Tasks:** the same 301 in `bench/cost_case/tasks.jsonl` (101 trivial, 120 everyday, 80 hard), same prompts, max_tokens 1536, sampling at the vLLM defaults from the model's config, one run each, no repeats.
- **Grader:** the same sandbox grader (`bench/datasets/grade.py`), run after generation so grading time is never counted as GPU time.
- **Runner:** `bench/cost_case/run_h200.py` (`gen <concurrency>`, then `grade <concurrency>`). Rows are in `bench/.scratch/cost_case_h200/` (git-ignored), one per task, resumable.
- **Price:** Modal H200 GPU meter $4.54/hour = $0.001261/s, from [Modal's H200 announcement](https://modal.com/blog/introducing-b200-h200) (also quoted in [Modal's July 2026 rate list via Spheron](https://www.spheron.network/blog/modal-gpu-pricing-2026-per-second-billing/)). Modal also bills CPU and memory meters; they are not included, so true cost is slightly higher.
- **$ per 1,000 calls** = generation wall seconds x $0.001261 / 301 x 1000. Wall time is the time the 301 calls took with the GPU busy. Idle time between runs and the cold start are counted separately below.

## Numbers

| Run | Wall (s) | Output tokens | Throughput (tok/s) | Latency p50 / p90 (s) | $ per 1k calls | Pass |
|---|---|---|---|---|---|---|
| H200, concurrency 1 | 259.9 | 35,335 | 136 | 0.61 / 1.65 | $1.089 | 270/301 = 90% (86-93) |
| H200, concurrency 32 | 23.0 | 36,381 | 1,584 | 1.18 / 3.80 | $0.0962 | 271/301 = 90% (86-93) |
| H200, concurrency 64 | 16.7 | 36,249 | 2,174 | 1.30 / 4.45 | $0.0699 | 270/301 = 90% (86-93) |

Mean tokens per call: 121 in, 117 to 121 out. No request errors in any run. Concurrency 64 beat 32 by 38% in throughput; p90 latency rose from 3.8 s to 4.4 s. I did not try higher.

Pass rate by difficulty (concurrency 1; the other two runs differ by at most 2 items):

| Difficulty | n | Pass (95% interval) |
|---|---|---|
| trivial | 101 | 99/101 = 98% (93-99) |
| everyday | 120 | 107/120 = 89% (82-94) |
| hard | 80 | 64/80 = 80% (70-87) |
| FizzBuzz variants | 9 | 9/9 |

### Next to the other tiers (rows from `results_cost_case.md`)

| Tier | Pass (301 tasks) | Latency p50 (s) | $ per 1k calls |
|---|---|---|---|
| V100 Qwen3-30B (Ollama, one request at a time) | 269/301 = 89% | 78.0 | $11.02 |
| **H200 Qwen3-30B, concurrency 1** | 270/301 = 90% | 0.61 | **$1.09** |
| **H200 Qwen3-30B, concurrency 32** | 271/301 = 90% | 1.18 | **$0.096** |
| **H200 Qwen3-30B, concurrency 64** | 270/301 = 90% | 1.30 | **$0.070** |
| DeepSeek-V4.1-Flash 763B (API, list price) | 286/301 = 95% | 0.7 | $0.158 |
| GPT-5.5 (API, 60-item subset, 60/60) | 100% on 60 | 1.9 | $4.02 |
| Grok-4.5 (API, 60-item subset, 60/60) | 100% on 60 | 2.7 | $1.71 |

The H200 rows assume the GPU is busy for the whole run. The API rows are paid per call whether or not anyone else is calling.

## Cold start and spend

- **Cold start:** 470 s from the first request to a ready server (image start, weights download into the volume, vLLM load). At $0.001261/s that is about $0.59. A later start would skip the weights download, so it would be shorter; I did not measure a second one. A user who waits for a cold start waits about 8 minutes.
- **Total Modal spend for this item:** the app ran 874 s from deploy to stop, about **$1.10** at the GPU price. That includes the cold start, the three runs, grading pauses and a 3-call smoke test. The $15 cap was never near.

## Break-even: always-on H200 vs each API

An always-on H200 costs 24 x $4.54 = **$108.96 per day**, whatever the traffic. It beats an API once calls per day x the API's $ per call exceeds that, as long as the traffic fits the GPU.

| Compared with | API $ per call | Break-even calls/day | Same quality? |
|---|---|---|---|
| 763B (DeepSeek-V4.1-Flash) | $0.000158 | about 691,000 | No: 90% vs 95% |
| Grok-4.5 | $0.00171 | about 63.7 million | Not shown (60 items, 100%) |
| GPT-5.5 | $0.00402 | about 27.1 million | Not shown (60 items, 100%) |

How many calls one H200 can serve in a day, from this run's speed on short coding prompts at 100% busy: about 1.13 million at concurrency 32 and about 1.56 million at concurrency 64.

- **Against the 763B** the window is narrow: about 0.69 million to 1.56 million calls a day for one H200. At 50% busy it serves 0.78 million (concurrency 64), barely above break-even. Below roughly 44% busy at concurrency 64 (61% at concurrency 32), the 763B API is cheaper.
- **Against GPT-5.5 and Grok-4.5**, one H200 cannot serve enough calls to reach break-even (27 and 64 million a day). GPT-5.5's break-even volume (27.1M a day) would need at least 17 H200s (27.1M / 1.56M), each kept busy. Per call at full load the H200 is cheaper by 57x (GPT-5.5) and 24x (Grok-4.5), but the premium models scored 100% on their 60 items against the 30B's 90%.
- The break-even for the API comparison ignores engineering, on-call and idle-GPU risk.

## Verdict

- **Speed is fixed by the GPU, not the model.** The same model went from 78 s per call on the V100 to 0.6 s at concurrency 1 and 1.2 s at concurrency 32. The V100 result said more about a shared single-stream box than about the 30B.
- **Cost per call drops 100x or more** (V100 $11.02 to H200 $0.07-$0.10 per 1,000 at 32-64 concurrent). It beats the 763B's $0.158 per 1,000 only when the H200 is more than about half busy. This is cost of the GPU being full, not a saving a small company will see.
- **Quality failure:** the 30B still fails 31 of 301 tasks (10%) against 15 for the 763B, and 16 of 80 hard tasks. If wrong answers are served unchecked, the cheaper tier costs correctness. The earlier router run, which accepted every 30B answer, already showed this.
- **Against the 763B the saving is small in dollars and negative in quality.** The 763B costs $0.158 per 1,000 calls, so even a perfect H200 saves $0.09 per 1,000 calls. At 1 million calls a day that is about $90 a day, before the 5-point quality loss.
- **Against GPT-5.5 or Grok-4.5 the price gap is large** ($0.07 vs $4.02 and $1.71 per 1,000), which supports the "companies overpay a big model for FizzBuzz" case for trivial work: 98% pass on trivial tasks, 9/9 FizzBuzz. It needs a router that sends only easy work to the 30B, plus checks; the premium rows come from 60 items only.
- **Caveats:** single runs, no repeats. Concurrency 32 and 64 ran right after concurrency 1 on the same prompts, so vLLM's prefix cache was warm (33,680 prompt tokens cached in each; prompts are about 121 tokens, so prefill is a small part of the time, but the batched numbers are somewhat favorable). Calls come from one Mac in a single process, so network time is in the latency. Traffic here is a burst of 301 short prompts; real traffic with longer prompts will lower throughput. The model is BF16 here and quantized on the V100, so the two 30B rows are not the identical model. The p90 grows with concurrency (1.65 s, 3.8 s, 4.45 s).

## Rerun

```
make modal-qwen-up
export MODAL_QWEN_URL=<url printed by modal deploy>     # MODAL_VLLM_TOKEN is read from .env
for c in 1 32 64; do .venv/bin/python bench/cost_case/run_h200.py gen $c; .venv/bin/python bench/cost_case/run_h200.py grade $c; done
make modal-qwen-down
```

Shutdown proof: after `modal app stop`, `modal app list` showed `chimera-qwen30b` as `stopped` with no running tasks at 2026-11-15 00:45 PST, and `chimera-gpu-large` was not running.
