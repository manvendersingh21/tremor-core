# What a company saves by not sending easy coding calls to a frontier API

Question: a company sends every coding call, FizzBuzz included, to a frontier API (GPT-5.5). What does it pay per 1,000 calls and per month if a cache, a bank of solved problems and a self-hosted 30B take the easy calls first?

## Cost per 1,000 coding calls

| Tier | $ per 1,000 calls | Pass on 301 coding tasks | Source |
|---|---|---|---|
| Supabase cache hit (exact or cosine 0.97) | $0 in tokens | 0 wrong in the repeats below | this file |
| Solved-problem bank hit (served after its tests pass) | $0 in tokens, plus one test run on CPU | 0 wrong served | this file, `results_bank.md` |
| 30B on one H200, busy 100% of the day (concurrency 64) | $0.070 | 270/301 = 90% | `results_cost_case_h200.md` |
| 30B on one H200, busy 50% of the day (concurrency 64) | $0.140 | 270/301 = 90% | `results_cost_case_h200.md` |
| 30B on one H200, busy 10% of the day (concurrency 64) | $0.700 | 270/301 = 90% | `results_cost_case_h200.md` |
| 30B on one H200, busy 1% of the day (concurrency 64) | $6.997 | 270/301 = 90% | `results_cost_case_h200.md` |
| 30B on one H200, busy 100% (concurrency 32) | $0.096 | 271/301 = 90% | `results_cost_case_h200.md` |
| 30B on one H200, one request at a time | $1.089 | 270/301 = 90% | `results_cost_case_h200.md` |
| 30B on the shared V100 (Akash), one request at a time | $11.02 | 269/301 = 89% | `results_cost_case.md` |
| DeepSeek-V4.1-Flash 763B (Crusoe list price) | $0.1576 | 286/301 = 95% | `results_cost_case.md` |
| GPT-5.5 (list price) | $4.02 | 60/60 = 100% (60-item subset) | `results_cost_case.md` |

An idle H200 still bills: an always-on H200 is $4.54 x 24 = **$108.96 a day** with or without calls. So its price per call is the full-GPU price divided by how busy it is: `$ per 1k = $0.0700 / busy share` at concurrency 64.

### Break-even: how busy the H200 must be

`break-even busy share = H200 $ per 1k when full / API $ per 1k`

| Against | API $ per 1k | Concurrency 64 (full: $0.0700) | Concurrency 32 (full: $0.0964) |
|---|---|---|---|
| 763B | $0.1576 | 44% busy | 61% busy |
| GPT-5.5 | $4.02 | 1.7% busy | 2.4% busy |

One H200 at concurrency 64 serves about 1.56 million short coding calls a day at 100% busy. Busy 1.7% of that is about 27,104 calls a day: above that, one H200 is cheaper per call than GPT-5.5. Against the 763B it needs about 691,371 calls a day (44% busy).

## Monthly cost at 100k, 1M and 10M coding calls a day

Math (30 days a month, D = calls a day, h = share served by the cache or bank):

```
frontier only  = D x 30 x P_api / 1000
H200s          = ceil(D x (1 - h) / (1,557,000 x 0.5))      # measured top rate, planned at half for peaks
cascade        = H200s x $108.96 x 30                         # always on
               + D x (1 - h) x 0.103 x 30 x P_fail / 1000  # the 30B's failures, caught by tests, re-asked
               + $25                                          # Supabase Pro base fee
```

P_api: GPT-5.5 $4.02, 763B $0.1576 per 1k (measured mix of 101 trivial, 120 everyday, 80 hard). P_fail is the same API's price weighted by where the 30B fails (2 trivial, 13 everyday, 16 hard): GPT-5.5 $6.04, 763B $0.221 per 1k.

### h = 0: no repeats at all (the cautious case)

| Coding calls a day | GPT-5.5 only | 30B + GPT-5.5 for failures | Saved vs GPT-5.5 | 763B only | 30B + 763B for failures | Saved vs 763B | H200s (busy) |
|---|---|---|---|---|---|---|---|
| 100,000 | $12,060 | $5,159 | $6,901 (57%) | $473 | $3,362 | -$2,889 (-611%) | 1 (6%) |
| 1,000,000 | $120,600 | $25,216 | $95,384 (79%) | $4,728 | $7,246 | -$2,518 (-53%) | 2 (32%) |
| 10,000,000 | $1,206,000 | $229,058 | $976,942 (81%) | $47,280 | $49,353 | -$2,073 (-4%) | 13 (49%) |

### h = 30%: three in ten calls are repeats or rewordings of solved problems

30% is the share the bank served on reworded copies of problems it had already solved (bank run 3 below). It is not a measured rate of company traffic. On open chat (oasst1, `results_replay.md`) under 1% of requests were repeats.

| Coding calls a day | GPT-5.5 only | 30B + GPT-5.5 for failures | Saved vs GPT-5.5 | 763B only | 30B + 763B for failures | Saved vs 763B | H200s (busy) |
|---|---|---|---|---|---|---|---|
| 100,000 | $12,060 | $4,600 | $7,460 (62%) | $473 | $3,342 | -$2,869 (-607%) | 1 (4%) |
| 1,000,000 | $120,600 | $16,351 | $104,249 (86%) | $4,728 | $3,772 | $956 (+20%) | 1 (45%) |
| 10,000,000 | $1,206,000 | $160,021 | $1,045,979 (87%) | $47,280 | $34,228 | $13,052 (+28%) | 9 (50%) |

Worked example, 1,000,000 calls a day, no cache or bank hits, failures to GPT-5.5:

```
GPT-5.5 only   = 1,000,000 x 30 x $4.02 / 1000                    = $120,600
H200s          = ceil(1,000,000 / (1,557,269 x 0.5))                 = 2
GPU            = 2 x $108.96 x 30                                   = $6,538
failures       = 1,000,000 x 0.103 (31 of 301 fail)                = 102,990 a day
failure price  = GPT-5.5 $ per 1k weighted by where the 30B fails     = $6.04
escalation     = 102,990 x 30 x $6.04 / 1000                       = $18,654
database       = Supabase Pro base fee                                = $25.00
cascade total  = GPU + escalation + database                          = $25,216
```

## Repeated tests (3 runs each)

Each repeat ran in its own Supabase tenant or namespace, which was deleted after the repeat. Only Supabase, Crusoe and the GPU 30B on the Akash V100 were used. No Modal GPU was started.

### Supabase cache: one client stores 18 answers, a second client asks 60 questions

Same sets as `bench/run_cache.py`: 18 same text, 18 changed case and spacing, 18 with "Quick question:" in front (cosine), 6 near-misses (similar words, other answer: any hit is wrong). Product settings: no local fallback, guard on, 300 ms budget, cosine 0.97.

| Repeat | Asked | Hits | Exact | Cosine | Same text | Case/spacing | Prefix added | Near-miss hits | Wrong | DB unavailable | Lookup p50 / p90 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 60 | 49 | 36 | 13 | 18/18 | 18/18 | 13/18 | 0/6 | 0 | 0 | 122 / 139 |
| 2 | 60 | 49 | 36 | 13 | 18/18 | 18/18 | 13/18 | 0/6 | 0 | 0 | 125 / 148 |
| 3 | 60 | 49 | 36 | 13 | 18/18 | 18/18 | 13/18 | 0/6 | 0 | 0 | 120 / 134 |
| **mean ± sd (range)** | 60 | 49.0 in all 3 | 36.0 in all 3 | 13.0 in all 3 | | | | 0.0 in all 3 | 0.0 in all 3 | | 122 ± 3 (120-125) / 140 ± 7 (134-148) |

### Solved-problem bank: run 2 (same 80 problems) and run 3 (80 reworded copies)

Each repeat: a fresh tenant, run 1 replays saved answers to fill the bank with the test problems, then the 260-problem train fill, run 2, run 3. Run 3 misses make fresh 30B and 763B calls (temperature 0). The graph write is off: it is not part of the lookup.

| Run | Repeat | Served (exact/cosine) | Hint only | Miss | 30B calls | 763B calls | 763B $ | Solved | Median lookup ms |
|---|---|---|---|---|---|---|---|---|---|
| 2 same problems | earlier single run | 75 (75/0) | 2 | 3 | 5 | 5 | $0.0026 | 75 | 472 |
| 2 same problems | 1 | 75 (75/0) | 2 | 3 | 5 | 5 | $0.0026 | 75 | 459 |
| 2 same problems | 2 | 75 (75/0) | 2 | 3 | 5 | 5 | $0.0026 | 75 | 437 |
| 2 same problems | 3 | 75 (75/0) | 2 | 3 | 5 | 5 | $0.0026 | 75 | 446 |
| **2 same problems** | **mean ± sd (range)** | 75.0 in all 3 | 2.0 in all 3 | 3.0 in all 3 | 5.0 in all 3 | 5.0 in all 3 | $0.0026 in all 3 | 75.0 in all 3 | 448 ± 11 (437-459) |
| 3 reworded copies | earlier single run | 24 (0/24) | 40 | 16 | 56 | 7 | $0.0065 | 75 | 336 |
| 3 reworded copies | 1 | 24 (0/24) | 40 | 16 | 56 | 7 | $0.0066 | 75 | 278 |
| 3 reworded copies | 2 | 24 (0/24) | 40 | 16 | 56 | 8 | $0.0068 | 74 | 261 |
| 3 reworded copies | 3 | 24 (0/24) | 40 | 16 | 56 | 8 | $0.0065 | 74 | 274 |
| **3 reworded copies** | **mean ± sd (range)** | 24.0 in all 3 | 40.0 in all 3 | 16.0 in all 3 | 56.0 in all 3 | 7.7 ± 0.6 (7.0-8.0) | $0.0066 ± $0.0002 ($0.0065-$0.0068) | 74.3 ± 0.6 (74.0-75.0) | 271 ± 9 (261-278) |

### 60-question ladder check: BASE (763B only), COLD (empty cache), WARM (same questions again)

`bench/run_backend.py` unchanged: Supabase cache -> GPU 30B on the Akash V100 (gate 0.95) -> 763B. The 30B here is the slow shared V100, not the H200.

Not run yet.

## Rerun

```
# .env: CHIMERA_DB_URL, CRUSOE_API_KEY, CHIMERA_GPU_URL (an SSH tunnel to your GPU box)
.venv/bin/python bench/company_cost/run_repeats.py cache 3
.venv/bin/python bench/company_cost/run_repeats.py bank 3
.venv/bin/python bench/company_cost/run_repeats.py ladder 3
.venv/bin/python bench/company_cost/report.py
```

Rows: `bench/.scratch/company_cost/` (git-ignored, one row per item, a rerun skips done rows). Price sources: [Modal H200](https://modal.com/blog/introducing-b200-h200), [Supabase pricing](https://supabase.com/pricing), Crusoe and GMI list prices as in `results_cost_case.md`.
