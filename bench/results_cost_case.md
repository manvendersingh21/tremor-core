# Cost case: what share of everyday coding a local or self-hosted model solves

Single run per tier, no repeats, thinking off, temperature as each server defaults (Mac 0.2). Every answer is graded by running its code against asserts in a subprocess (10 s timeout, empty environment, network blocked). 301 tasks: 101 trivial, 120 everyday, 80 hard.

## Summary in plain words

- FizzBuzz-class tasks (9 items): the V100 Qwen3-30B passes 9/9 (100%), the 763B passes 9/9. Cost per 1,000 calls: $12.92 on the V100 vs $0.1276 on the 763B (list price).
- Trivial tier (101 items): V100 Qwen3-30B 98% vs 763B 100%. Hard tier: V100 Qwen3-30B 78% vs 763B 92%.
- The real router (cache, self-hosted 30B, 763B; no 3B) passed 88% against 95% for the 763B alone (table below). Details and the failures are in the sections that follow.

## Setup

- **Task set** (`bench/cost_case/tasks.jsonl`, built by `build_tasks.py`): trivial = 101 hand-written FizzBuzz-class tasks (9 FizzBuzz variants, strings, lists, dates, small classes, dataclasses); everyday = regex, SQL (sqlite in memory) and JSON tasks written for this run plus random HumanEval and MBPP items; hard = the longest HumanEval/MBPP prompts and 5 multi-function tasks. Every hand-written task has a reference solution that passes its own asserts (checked at build time). 'Hard' is chosen by prompt length, not by a measured low pass rate.
- **Mac:** Qwen2.5-3B-Instruct q4_k_m on llama.cpp, tokens in = server tokenizer on the ChatML prompt, tokens out and mean token probability from the server.
- **30B:** Ollama `qwen3:30b-instruct` on a V100 behind an SSH tunnel; tokens and `total_duration` from Ollama. The box was shared with other runs, so wall latency includes queue time; compute time is shown apart.
- **763B:** Crusoe `deepseek-ai/DeepSeek-V4.1-Flash`, thinking off, list price $0.29/M in, $0.007/M cached, $1.20/M out.
- **Premium models (60-item subset, stratified: 15 trivial, 30 everyday, 15 hard):** GMI `openai/gpt-5.5` (reasoning_effort none, $5/$30 per M) and `x-ai/grok-4.5` (reasoning_effort low, its lowest; $2/$6 per M). Prices from GMI's model list.
- **H200 / Modal gpt-oss-120b:** not run. The backend owner manages that app and it has not served a request.
- max_tokens 1536 on every tier. Pass-rate brackets are 95% Wilson intervals.

## Per tier and difficulty

| Tier (Mac 3B = reference only, not in the ladder) | Difficulty | n | Pass (95% interval) | Tokens in / out (mean) | Latency p50 / p90 (s) | Compute p50 / p90 (s) | $ per 1k calls |
|---|---|---|---|---|---|---|---|
| V100 Qwen3-30B | trivial | 101 | 99/101 = 98% (93-99) | 50 / 46 | 81.5 / 120.5 | 81.1 / 120.1 | $11.31 |
| V100 Qwen3-30B | everyday | 120 | 108/120 = 90% (83-94) | 104 / 92 | 71.2 / 118.0 | 70.6 / 117.6 | $10.15 |
| V100 Qwen3-30B | hard | 80 | 62/80 = 78% (67-85) | 235 / 283 | 81.9 / 138.3 | 81.3 / 137.5 | $11.94 |
| V100 Qwen3-30B | all | 301 | 269/301 = 89% (85-92) | 121 / 128 | 78.0 / 127.2 | 77.6 / 126.1 | $11.02 |
| DeepSeek-V4.1-Flash 763B | trivial | 101 | 101/101 = 100% (96-100) | 47 / 47 | 0.7 / 0.8 | 0.7 / 0.8 | $0.0696 |
| DeepSeek-V4.1-Flash 763B | everyday | 120 | 111/120 = 92% (86-96) | 97 / 80 | 0.7 / 1.0 | 0.7 / 1.0 | $0.1241 |
| DeepSeek-V4.1-Flash 763B | hard | 80 | 74/80 = 92% (85-97) | 227 / 226 | 1.2 / 1.6 | 1.2 / 1.6 | $0.3190 |
| DeepSeek-V4.1-Flash 763B | all | 301 | 286/301 = 95% (92-97) | 115 / 107 | 0.7 / 1.3 | 0.7 / 1.3 | $0.1576 |
| GPT-5.5 (60 items) | trivial | 15 | 15/15 = 100% (80-100) | 50 / 45 | 1.8 / 2.1 | 1.8 / 2.1 | $1.60 |
| GPT-5.5 (60 items) | everyday | 30 | 30/30 = 100% (89-100) | 97 / 68 | 1.9 / 2.4 | 1.9 / 2.4 | $2.52 |
| GPT-5.5 (60 items) | hard | 15 | 15/15 = 100% (80-100) | 275 / 269 | 2.9 / 3.8 | 2.9 / 3.8 | $9.45 |
| GPT-5.5 (60 items) | all | 60 | 60/60 = 100% (94-100) | 130 / 113 | 1.9 / 3.2 | 1.9 / 3.2 | $4.02 |
| Grok-4.5 (60 items) | trivial | 15 | 15/15 = 100% (80-100) | 540 / 71 | 2.3 / 3.1 | 2.3 / 3.1 | $0.9308 |
| Grok-4.5 (60 items) | everyday | 30 | 30/30 = 100% (89-100) | 589 / 126 | 2.6 / 3.9 | 2.6 / 3.9 | $1.36 |
| Grok-4.5 (60 items) | hard | 15 | 15/15 = 100% (80-100) | 771 / 371 | 3.9 / 6.5 | 3.9 / 6.5 | $3.19 |
| Grok-4.5 (60 items) | all | 60 | 60/60 = 100% (94-100) | 622 / 173 | 2.7 / 4.6 | 2.7 / 4.6 | $1.71 |

$ per 1k calls: cloud = list price on measured tokens; 30B = V100 $0.5/hr x measured compute time (queue excluded), i.e. hourly price / measured throughput at one request at a time; Mac = electricity only (30 W x latency x $0.15/kWh), no hardware charge. Compute columns equal latency for every tier except the 30B. The 30B $ is a single-stream figure; batching would lower it, and no batched run was made.

30B queue time (wall minus Ollama compute): median 0.5 s, p90 0.6 s, per call. Compute-only median 77.6 s. Mean 30B output speed 1.6 tok/s of compute.

### Same 60 items on every tier

| Tier | n | Pass | $ per 1k calls | Tokens out (mean) | Latency p50 (s) |
|---|---|---|---|---|---|
| V100 Qwen3-30B | 60 | 54/60 = 90% (80-95) | $10.81 | 160 | 75.5 |
| DeepSeek-V4.1-Flash 763B | 60 | 58/60 = 97% (89-99) | $0.1764 | 124 | 0.7 |
| GPT-5.5 (60 items) | 60 | 60/60 = 100% (94-100) | $4.02 | 113 | 1.9 |
| Grok-4.5 (60 items) | 60 | 60/60 = 100% (94-100) | $1.71 | 173 | 2.7 |

## Where the local tiers lose

| Task kind | n | 30B pass | 763B pass |
|---|---|---|---|
| humaneval | 68 | 57/68 | 65/68 |
| json | 12 | 12/12 | 12/12 |
| mbpp | 88 | 76/88 | 78/88 |
| multi | 6 | 2/6 | 5/6 |
| reg | 14 | 11/14 | 13/14 |
| sql | 12 | 12/12 | 12/12 |
| triv | 101 | 99/101 | 101/101 |

Kinds: triv = hand-written trivial, reg = regex, sql = SQL on sqlite, json = JSON/dict transforms, multi = multi-function, humaneval / mbpp = benchmark items (everyday and hard mixed).

30B failures where the 763B passed: 20 of 301. By difficulty: trivial 2, everyday 4, hard 14.
Items both fail (likely a hard task or a test the prompt does not fully specify): ['humaneval-132', 'humaneval-160', 'mbpp-143', 'mbpp-229', 'mbpp-301', 'mbpp-415', 'mbpp-430', 'mbpp-434', 'mbpp-438', 'mbpp-452', 'mbpp-462', 'reg-url_domain']

## Routing result (the real policy)

`SpeculativeCascadeRouter.generate()` over a `TierPool`: exact + semantic cache (0.97) -> self-hosted 30B (complexity <= 0.6; its answers are accepted with no check, the pool has no 30B confidence signal) -> 763B. The Mac 3B is not in the ladder. Nothing in `packages/` or `apps/` was edited. The tasks are not duplicates of each other, so the cache has little to do here.

| Answered by | Items | Share |
|---|---|---|
| gpu-small | 300 | 100% |
| exact_cache | 1 | 0% |

| | 763B alone | Router |
|---|---|---|
| Pass rate | 286/301 = 95.0% | 264/301 = 87.7% |
| 763B calls | 301 | 0 |
| 763B tokens in / out | 34,568 / 32,355 | 0 / 0 |
| 763B $ (list) | $0.0474 | $0.0000 |
| 30B compute $ (V100 time) | $0 | $3.31 |
| Latency p50 / p90 (s) | 0.7 / 1.3 | 6.0 / 22.6 |

Tokens kept off the 763B: 100.0%. $ kept off the 763B: 100.0%. Quality change: -7.3 points. Router latency includes failed lower-tier attempts and 30B queue time.

| Difficulty | Items | Router pass | 763B pass | 763B calls (router) | Answered by 30B / 763B |
|---|---|---|---|---|---|
| trivial | 101 | 99/101 | 101/101 | 0 | 100 / 0 |
| everyday | 120 | 105/120 | 111/120 | 0 | 120 / 0 |
| hard | 80 | 60/80 | 74/80 | 0 | 80 / 0 |

Wrong answers the router served from a cheaper tier: 37 (all from the 30B). Of the 300 items the 30B answered, the pool accepts them with no check, so a 30B failure is not escalated.

### Upper bound: a test gate in front of every escalation

If a check (the task's own tests) decided each climb, replayed from the raw runs on the 301 items every tier ran: 30B 269, 763B 32. End pass rate 289/301 = 96.0% vs 763B alone 286/301. 763B tokens 12,273 of 66,923 (81.7% kept off). This is a bound, not the router's behaviour: it needs tests for every request, which most real requests do not have. Failed lower-tier attempts are counted in the 30B compute; the Mac's are free.

## Company-scale projection

Formulas (D = calls per day, 30 days per month):

- Frontier only: `monthly = D x 30 x P_front`, P_front = mean list-price $ per call measured on this mix.
- Cascade: `monthly = D x 30 x P_top + servers x $0.5 x 24 x 30`, P_top = measured mean 763B $ per call after routing (failed lower attempts cost the 763B nothing); `servers = ceil(D x S_gpu / (86400 x 0.5))` V100s, S_gpu = measured mean V100 compute seconds per call (single request at a time). The Mac tier is charged $0 (it runs on the user's machine); if a company hosted the 3B itself, add that hardware.

Measured inputs (this mix: 101 trivial, 120 everyday, 80 hard):

- P_front (763B only) = $0.0002 per call; P_top (cascade) = $0.0000 per call; S_gpu = 79.09 s per call; router pass 87.7% vs 763B pass 95.0%.
- The workload is assumed to look like this task mix. A real company mix has more or less trivial work; scale the shares accordingly. Utilisation 50% is an assumption (idle time, peaks).
- H200 ($4.54/hr) not used: no measured H200 run exists.

| Calls/day | Strategy | $/month | Saving vs frontier-only | Pass rate |
|---|---|---|---|---|
| 100,000 | 763B only | $472.80 | | 95.0% |
| 100,000 | Router -> 763B (184 V100) | $66,240.00 | $-65767.1962 (-13910%) | 87.7% (-7.3 pts) |
| 100,000 | GPT-5.5 only (60-item pass 60/60) | $12,162.93 | | see table above |
| 100,000 | Router -> GPT-5.5 (184 V100) | $66,240.00 | $-54077.0731 (-445%) | same routing as the 763B row |
| 100,000 | Grok-4.5 only (60-item pass 60/60) | $5,102.17 | | see table above |
| 100,000 | Router -> Grok-4.5 (184 V100) | $66,240.00 | $-61137.8326 (-1198%) | same routing as the 763B row |
| 1,000,000 | 763B only | $4,728.04 | | 95.0% |
| 1,000,000 | Router -> 763B (1831 V100) | $659,160.00 | $-654431.9617 (-13842%) | 87.7% (-7.3 pts) |
| 1,000,000 | GPT-5.5 only (60-item pass 60/60) | $121,629.27 | | see table above |
| 1,000,000 | Router -> GPT-5.5 (1831 V100) | $659,160.00 | $-537530.7309 (-442%) | same routing as the 763B row |
| 1,000,000 | Grok-4.5 only (60-item pass 60/60) | $51,021.67 | | see table above |
| 1,000,000 | Router -> Grok-4.5 (1831 V100) | $659,160.00 | $-608138.3256 (-1192%) | same routing as the 763B row |
| 10,000,000 | 763B only | $47,280.38 | | 95.0% |
| 10,000,000 | Router -> 763B (18308 V100) | $6,590,880.00 | $-6543599.6173 (-13840%) | 87.7% (-7.3 pts) |
| 10,000,000 | GPT-5.5 only (60-item pass 60/60) | $1,216,292.69 | | see table above |
| 10,000,000 | Router -> GPT-5.5 (18308 V100) | $6,590,880.00 | $-5374587.3090 (-442%) | same routing as the 763B row |
| 10,000,000 | Grok-4.5 only (60-item pass 60/60) | $510,216.74 | | see table above |
| 10,000,000 | Router -> Grok-4.5 (18308 V100) | $6,590,880.00 | $-6080663.2558 (-1192%) | same routing as the 763B row |

Premium-model rows: P_front = mean $ per call on that model's 60 items re-weighted to the 301-task mix by difficulty; the cascade row replaces P_top with that model's mean $ per call on the difficulties of the items the router escalated. They are projections from 60 items, not a router run on that model.

Quality delta in the router row is measured (301 items). If the delta is negative, the saving is bought with wrong answers the pool serves unchecked; the test-gated bound above shows what a check would recover.

## With N+1 memory

Not filled. The router now has the `memory` hook (`retrieve` before the 30B call, `store` after a verified big-model answer) and `packages/chimera-core/memory/` exists, but no memory-enabled run was made. A fair run needs a split: store the 763B's verified answers for one half of the tasks and measure the 30B on the other half. Running the same tasks twice would let the 30B copy the stored answer and overstate the gain, and storing writes to the shared Supabase tables the memory worker owns.

## Verdict

- **Quality:** the 30B solves 98% of trivial, 90% of everyday and 78% of hard tasks; the 763B solves 100%, 92%, 92%. The gap is mostly hard tasks and multi-function tasks.
- **Cost: not shown.** On the shared V100 the 30B took about 78 s per call (1.6 tok/s of compute, single stream), so $ per call is about 70x the 763B's list price, and the projection shows the cascade costing MORE than the frontier-only row at every volume. The 763B (DeepSeek-V4.1-Flash) is already very cheap. Savings would show only against a pricey frontier model such as GPT-5.5 or Grok-4.5, and only if the 30B ran far faster (batching, a faster GPU); no such run was made.
- **Router fails its goal here:** the pool accepts every 30B answer with no check, so it passed 87.7% vs 95.0% and escalated nothing. The test-gated bound (96.0%) is not available without tests.
- **Mac 3B reference row:** its raw rows were lost with the old scratch folder and are not in this report. **Not run:** H200, N+1 memory column.
- 21 763B rows hit HTTP 429 in the first pass; they were rerun and are the rows shown. Single run, no repeats.

## Rerun

```
bench/serve_local.sh                                  # Mac llama-server on 127.0.0.1:8080 if /health fails
ssh -i <key> -p <port> <user>@<gpu-host> -N -L 127.0.0.1:<local-port>:<remote-port>   # GPU tunnel
.venv/bin/python bench/cost_case/build_tasks.py
export GPU_PORT=<local-port>
for t in gpu top; do   # mac only for the reference row .venv/bin/python bench/cost_case/run_tiers.py $t; done
.venv/bin/python bench/cost_case/run_tiers.py gpt55 --subset 60    # GMI_API_KEY
.venv/bin/python bench/cost_case/run_tiers.py grok --subset 60
.venv/bin/python bench/cost_case/run_router.py
.venv/bin/python bench/cost_case/report.py
```

API spend for this run at list price: $0.3914 (763B raw run + router run + premium subsets). Warm-up and retried calls excluded.
