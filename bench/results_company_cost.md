# What a company saves by not sending easy coding calls to a frontier API

Question: a company sends every coding call, FizzBuzz included, to a frontier API (GPT-5.5). What does it pay per 1,000 calls and per month if a cache, a bank of solved problems and a self-hosted 30B take the easy calls first?

## Verdict

- **Against GPT-5.5 the saving is real.** A 30B on always-on H200s, with GPT-5.5 re-asked for every call the 30B fails, costs 57% less than GPT-5.5 alone at 100k coding calls a day, 79% less at 1M and 81% less at 10M. That is with no repeats served from the cache or bank. If 30% of calls are repeats, the saving is 62%, 86% and 87%.
- **Most of what is left is the 30B's failures.** At 1M calls a day the cascade costs $25,216 a month: $6,538 of H200 time and $18,654 of GPT-5.5 calls for the 10% the 30B gets wrong. Those failures are mostly hard tasks, so they cost more per call ($6.04 per 1,000) than the GPT-5.5 average ($4.02).
- **Against the 763B there is no saving at today's volumes.** The 763B (DeepSeek-V4.1-Flash on Crusoe) costs $0.158 per 1,000 calls. With no repeats, the cascade costs 7.1x as much at 100k calls a day and 53% more at 1M, and about the same at 10M (4% more). With 30% repeats it saves 20% at 1M and 28% at 10M, and still costs more at 100k.
- **Break-even busy share of one H200** (always on, $108.96 a day, concurrency 64): 1.7% of its top rate (about 27,000 calls a day) to beat GPT-5.5 per call, and 44% (about 691,000 calls a day) to beat the 763B. At concurrency 32 it is 2.4% and 61%. Below 1.7% busy the H200 costs more per call than GPT-5.5 itself.
- **Our own tuned V100 is now a real option at small volume.** After tuning (`results_akash_tuning.md`), the same 30B on our Akash V100 answers a coding task in a median 2.7 s with 270/301 = 90% passing, for $0.178 to $0.522 per 1,000 calls when the box is kept busy ($0.52 to $1.53 an hour, always on, billed busy or idle). One box serves about 70,000 calls a day. At 100k coding calls a day, 3 tuned V100s with GPT-5.5 for failures cost $3,083 to $5,264 a month (74% or 56% less than GPT-5.5 alone), against $5,159 for one H200. From 1M calls a day the H200 is cheaper ($25,216 against $30,227 to $51,316), because one H200 does the work of about 22 V100s. A tuned V100 beats GPT-5.5 per call above about 3,100 calls a day ($0.52/hr) or 9,100 ($1.53/hr). It never beats the 763B per call: even 100% busy it costs $0.178 per 1,000 against $0.158. The H200 must be 39% busy to beat a full tuned V100 at $0.52/hr (13% at $1.53/hr).
- **Correction.** An earlier version of this file listed the 30B on "the shared V100" at $11.02 per 1,000 calls. The GPU was ours and idle; the 30B was held back by CPU threads (a 4-CPU quota against 149 runner threads), not by other users. $11.02 stays in the table, labelled before tuning.
- **Failure, named plainly: the 30B gets about 10% wrong.** It failed 31 of 301 coding tasks on the H200 (2 of 101 trivial, 13 of 120 everyday, 16 of 80 hard). The 763B failed 15 of 301. GPT-5.5 passed 60 of 60, a smaller sample. The savings above assume each request carries tests that catch every 30B failure and send it up. Most real requests have no tests. Without them, the cheaper bill comes with about 1 wrong answer in 10.
- **The repeated tests agree with the earlier single runs.** Cache: 49 of 60 served in each of 3 repeats (36 exact, 13 cosine), 0 wrong, 0 near-miss hits, lookup p50 122 ± 3 ms. Bank: run 2 served 75 of 80 and run 3 served 24 of 80 in every repeat, with 0 wrong served. Ladder: an empty cache cut 763B tokens by 56.2% ± 4.6% (range 50.9% to 59.2%) against the 763B alone. The second pass served 58 or 59 of 60 from the cache, with 0 wrong cache answers in 3 repeats.
- **Why the spread is small:** the embeddings, the 0.97 and 0.9 cut-offs and temperature 0 are fixed, so cache and bank counts repeat exactly. The spread is in lookup time, 763B tokens (the 763B does not answer the same way each time) and 30B latency. On the V100 before tuning (default Ollama threads), the ladder's median was 6.7 s against 1.3 s for the 763B alone; these repeats were not rerun after tuning.
- **Not measured here:** the H200 numbers are single runs. This item started no Modal GPU, so they were not repeated. The share of repeats in a real company's coding traffic is unknown; open chat (oasst1) had under 1%. Other costs left out: scale-to-zero cold starts ($0.59 to $1.07 each), Modal CPU and memory meters, the CPU time of the test runs, and a bigger Supabase compute tier at 10M calls a day. H200 sizing at half its top rate is an assumption.

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
| 30B on our tuned V100 (Akash), $0.52/hr, busy 100% of the day (4 at once) | $0.178 | 270/301 = 90% | `results_akash_tuning.md` |
| 30B on our tuned V100 (Akash), $0.52/hr, busy 50% of the day (4 at once) | $0.355 | 270/301 = 90% | `results_akash_tuning.md` |
| 30B on our tuned V100 (Akash), $0.52/hr, busy 10% of the day (4 at once) | $1.775 | 270/301 = 90% | `results_akash_tuning.md` |
| 30B on our tuned V100 (Akash), $1.53/hr, busy 100% of the day (4 at once) | $0.522 | 270/301 = 90% | `results_akash_tuning.md` |
| 30B on our tuned V100 (Akash), $1.53/hr, busy 50% of the day (4 at once) | $1.045 | 270/301 = 90% | `results_akash_tuning.md` |
| 30B on our tuned V100 (Akash), $1.53/hr, busy 10% of the day (4 at once) | $5.223 | 270/301 = 90% | `results_akash_tuning.md` |
| 30B on the Akash V100 before tuning (default threads), one request at a time | $11.02 | 269/301 = 89% | `results_cost_case.md` |
| DeepSeek-V4.1-Flash 763B (Crusoe list price) | $0.1576 | 286/301 = 95% | `results_cost_case.md` |
| GPT-5.5 (list price) | $4.02 | 60/60 = 100% (60-item subset) | `results_cost_case.md` |

An idle H200 still bills: an always-on H200 is $4.54 x 24 = **$108.96 a day** with or without calls. So its price per call is the full-GPU price divided by how busy it is: `$ per 1k = $0.0700 / busy share` at concurrency 64.

The tuned V100 works the same way at a smaller size: $0.52 to $1.53 an hour is $12.48 to $36.72 a day, and it served 301 calls in 369.9 s with 4 at once, about 70,307 calls a day at 100% busy. So `$ per 1k = $0.1775 (or $0.5223) / busy share`.

### Break-even: how busy the box must be

`break-even busy share = box $ per 1k when full / API $ per 1k`

| Against | API $ per 1k | H200, 64 at once (full: $0.0700) | H200, 32 at once (full: $0.0964) | Tuned V100 at $0.52/hr (full: $0.1775) | Tuned V100 at $1.53/hr (full: $0.5223) |
|---|---|---|---|---|---|
| 763B | $0.1576 | 44% busy | 61% busy | never (would need 113%) | never (would need 331%) |
| GPT-5.5 | $4.02 | 1.7% busy | 2.4% busy | 4.4% busy | 13% busy |
| tuned V100, full | $0.1775 or $0.5223 | 39% or 13% busy | 54% or 18% busy | | |

One H200 at concurrency 64 serves about 1.56 million short coding calls a day at 100% busy. Busy 1.7% of that is about 27,104 calls a day: above that, one H200 is cheaper per call than GPT-5.5. Against the 763B it needs about 691,371 calls a day (44% busy).

One tuned V100 beats GPT-5.5 per call above about 3,104 calls a day at $0.52/hr (9,134 at $1.53/hr). It never beats the 763B per call: even 100% busy it costs $0.178 per 1k against $0.158.

## Monthly cost at 100k, 1M and 10M coding calls a day

Math (30 days a month, D = calls a day, h = share served by the cache or bank):

```
frontier only  = D x 30 x P_api / 1000
H200s          = ceil(D x (1 - h) / (1,557,000 x 0.5))      # measured top rate, planned at half for peaks
cascade        = H200s x $108.96 x 30                         # always on
               + D x (1 - h) x 0.103 x 30 x P_fail / 1000  # the 30B's failures, caught by tests, re-asked
               + $25                                          # Supabase Pro base fee

V100s          = ceil(D x (1 - h) / (70,307 x 0.5))         # tuned V100, 4 at once, planned at half
cascade        = V100s x $ per hour x 24 x 30                 # always on, $0.52 or $1.53 an hour
               + D x (1 - h) x 0.103 x 30 x P_fail / 1000  # its own failures, re-asked
               + $25
```

P_api: GPT-5.5 $4.02, 763B $0.1576 per 1k (measured mix of 101 trivial, 120 everyday, 80 hard). P_fail is the same API's price weighted by where the 30B fails (2 trivial, 13 everyday, 16 hard): GPT-5.5 $6.04, 763B $0.221 per 1k.

For the tuned V100, P_fail uses its own failures (2 trivial, 12 everyday, 17 hard): GPT-5.5 $6.26, 763B $0.227 per 1k.

### h = 0: no repeats at all (the cautious case)

30B on H200s:

| Coding calls a day | GPT-5.5 only | 30B + GPT-5.5 for failures | Saved vs GPT-5.5 | 763B only | 30B + 763B for failures | Saved vs 763B | H200s (busy) |
|---|---|---|---|---|---|---|---|
| 100,000 | $12,060 | $5,159 | $6,901 (57%) | $473 | $3,362 | -$2,889 (-611%) | 1 (6%) |
| 1,000,000 | $120,600 | $25,216 | $95,384 (79%) | $4,728 | $7,246 | -$2,518 (-53%) | 2 (32%) |
| 10,000,000 | $1,206,000 | $229,058 | $976,942 (81%) | $47,280 | $49,353 | -$2,073 (-4%) | 13 (49%) |

30B on our tuned V100s (Akash), same math:

| Coding calls a day | V100 $ per hour | V100s (busy) | 30B + GPT-5.5 for failures | Saved vs GPT-5.5 | 30B + 763B for failures | Saved vs 763B |
|---|---|---|---|---|---|---|
| 100,000 | $0.52 | 3 (47%) | $3,083 | $8,977 (74%) | $1,218 | -$746 (-158%) |
| 100,000 | $1.53 | 3 (47%) | $5,264 | $6,796 (56%) | $3,400 | -$2,927 (-619%) |
| 1,000,000 | $0.52 | 29 (49%) | $30,227 | $90,373 (75%) | $11,585 | -$6,857 (-145%) |
| 1,000,000 | $1.53 | 29 (49%) | $51,316 | $69,284 (57%) | $32,674 | -$27,946 (-591%) |
| 10,000,000 | $0.52 | 285 (50%) | $300,174 | $905,826 (75%) | $113,757 | -$66,477 (-141%) |
| 10,000,000 | $1.53 | 285 (50%) | $507,426 | $698,574 (58%) | $321,009 | -$273,729 (-579%) |

### h = 30%: three in ten calls are repeats or rewordings of solved problems

30% is the share the bank served on reworded copies of problems it had already solved (bank run 3 below). It is not a measured rate of company traffic. On open chat (oasst1, `results_replay.md`) under 1% of requests were repeats.

30B on H200s:

| Coding calls a day | GPT-5.5 only | 30B + GPT-5.5 for failures | Saved vs GPT-5.5 | 763B only | 30B + 763B for failures | Saved vs 763B | H200s (busy) |
|---|---|---|---|---|---|---|---|
| 100,000 | $12,060 | $4,600 | $7,460 (62%) | $473 | $3,342 | -$2,869 (-607%) | 1 (4%) |
| 1,000,000 | $120,600 | $16,351 | $104,249 (86%) | $4,728 | $3,772 | $956 (+20%) | 1 (45%) |
| 10,000,000 | $1,206,000 | $160,021 | $1,045,979 (87%) | $47,280 | $34,228 | $13,052 (+28%) | 9 (50%) |

30B on our tuned V100s (Akash), same math:

| Coding calls a day | V100 $ per hour | V100s (busy) | 30B + GPT-5.5 for failures | Saved vs GPT-5.5 | 30B + 763B for failures | Saved vs 763B |
|---|---|---|---|---|---|---|
| 100,000 | $0.52 | 2 (50%) | $2,128 | $9,932 (82%) | $823 | -$350 (-74%) |
| 100,000 | $1.53 | 2 (50%) | $3,582 | $8,478 (70%) | $2,277 | -$1,805 (-382%) |
| 1,000,000 | $0.52 | 20 (50%) | $21,054 | $99,546 (83%) | $8,005 | -$3,277 (-69%) |
| 1,000,000 | $1.53 | 20 (50%) | $35,598 | $85,002 (70%) | $22,549 | -$17,821 (-377%) |
| 10,000,000 | $0.52 | 200 (50%) | $210,317 | $995,683 (83%) | $79,825 | -$32,545 (-69%) |
| 10,000,000 | $1.53 | 200 (50%) | $355,757 | $850,243 (71%) | $225,265 | -$177,985 (-376%) |

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
| **mean ± sd (range)** | 60 | 49 in all 3 | 36 in all 3 | 13 in all 3 | | | | 0 in all 3 | 0 in all 3 | | 122 ± 3 (120-125) / 140 ± 7 (134-148) |

### Solved-problem bank: run 2 (same 80 problems) and run 3 (80 reworded copies)

Each repeat: a fresh tenant, run 1 replays saved answers to fill the bank with the test problems, then the 260-problem train fill, run 2, run 3. Run 3 misses make fresh 30B and 763B calls (temperature 0). The graph write is off: it is not part of the lookup.

| Run | Repeat | Served (exact/cosine) | Hint only | Miss | 30B calls | 763B calls | 763B $ | Solved | Median lookup ms |
|---|---|---|---|---|---|---|---|---|---|
| 2 same problems | earlier single run | 75 (75/0) | 2 | 3 | 5 | 5 | $0.0026 | 75 | 472 |
| 2 same problems | 1 | 75 (75/0) | 2 | 3 | 5 | 5 | $0.0026 | 75 | 459 |
| 2 same problems | 2 | 75 (75/0) | 2 | 3 | 5 | 5 | $0.0026 | 75 | 437 |
| 2 same problems | 3 | 75 (75/0) | 2 | 3 | 5 | 5 | $0.0026 | 75 | 446 |
| **2 same problems** | **mean ± sd (range)** | 75 in all 3 | 2 in all 3 | 3 in all 3 | 5 in all 3 | 5 in all 3 | $0.0026 in all 3 | 75 in all 3 | 448 ± 11 (437-459) |
| 3 reworded copies | earlier single run | 24 (0/24) | 40 | 16 | 56 | 7 | $0.0065 | 75 | 336 |
| 3 reworded copies | 1 | 24 (0/24) | 40 | 16 | 56 | 7 | $0.0066 | 75 | 278 |
| 3 reworded copies | 2 | 24 (0/24) | 40 | 16 | 56 | 8 | $0.0068 | 74 | 261 |
| 3 reworded copies | 3 | 24 (0/24) | 40 | 16 | 56 | 8 | $0.0065 | 74 | 274 |
| **3 reworded copies** | **mean ± sd (range)** | 24 in all 3 | 40 in all 3 | 16 in all 3 | 56 in all 3 | 7.7 ± 0.6 (7.0-8.0) | $0.0066 ± $0.0002 ($0.0065-$0.0068) | 74.3 ± 0.6 (74.0-75.0) | 271 ± 9 (261-278) |

### 60-question ladder check: BASE (763B only), COLD (empty cache), WARM (same questions again)

`bench/run_backend.py` unchanged: Supabase cache -> GPU 30B on the Akash V100 (gate 0.95) -> 763B. The 30B here is the Akash V100 before tuning (default Ollama threads, about 20 tokens/s), not the H200 and not the tuned setup in `results_akash_tuning.md`. These repeats were not rerun after tuning.

| Pass | Repeat | 763B calls | GPU 30B calls | Cache hits | 763B tokens | 763B $ | Graded correct | p50 ms | p90 ms | Calls >= 90 s | Errors |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BASE | earlier single run (v2) | 60 | 0 | 0 | 12664 | $0.01150 | 45/48 | 1210 | 2670 | 0 | 0 |
| BASE | 1 | 60 | 0 | 0 | 12661 | $0.01150 | 45/48 | 1266 | 2965 | 0 | 0 |
| BASE | 2 | 60 | 0 | 0 | 13323 | $0.01229 | 44/48 | 1382 | 2977 | 0 | 0 |
| BASE | 3 | 60 | 0 | 0 | 12998 | $0.01190 | 44/48 | 1363 | 2662 | 0 | 0 |
| **BASE** | **mean ± sd (range)** | 60 in all 3 | 0 in all 3 | 0 in all 3 | 12994 ± 331 (12661-13323) | $0.01190 ± $0.00040 ($0.01150-$0.01229) | 44.3 ± 0.6 (44.0-45.0) of 48 | 1337 ± 62 (1266-1382) | 2868 ± 179 (2662-2977) | 0 in all 3 | 0 in all 3 |
| COLD | earlier single run (v2) | 14 | 51 | 5 | 5956 | $0.00615 | 48/48 | 8594 | 21758 | 0 | 0 |
| COLD | 1 | 12 | 51 | 5 | 5267 | $0.00552 | 47/48 | 7101 | 22395 | 0 | 0 |
| COLD | 2 | 13 | 51 | 5 | 6548 | $0.00687 | 47/48 | 6919 | 21070 | 0 | 0 |
| COLD | 3 | 13 | 51 | 5 | 5301 | $0.00555 | 46/48 | 6010 | 21104 | 0 | 0 |
| **COLD** | **mean ± sd (range)** | 12.7 ± 0.6 (12.0-13.0) | 51 in all 3 | 5 in all 3 | 5705 ± 730 (5267-6548) | $0.00598 ± $0.00077 ($0.00552-$0.00687) | 46.7 ± 0.6 (46.0-47.0) of 48 | 6677 ± 585 (6010-7101) | 21523 ± 755 (21070-22395) | 0 in all 3 | 0 in all 3 |
| WARM | earlier single run (v2) | 0 | 0 | 60 | 0 | $0 | 48/48 | 113 | 122 | 0 | 0 |
| WARM | 1 | 0 | 1 | 59 | 0 | $0.00000 | 47/48 | 117 | 126 | 0 | 0 |
| WARM | 2 | 0 | 1 | 59 | 0 | $0.00000 | 47/48 | 110 | 128 | 0 | 0 |
| WARM | 3 | 0 | 2 | 58 | 0 | $0.00000 | 46/48 | 109 | 129 | 0 | 0 |
| **WARM** | **mean ± sd (range)** | 0 in all 3 | 1.3 ± 0.6 (1.0-2.0) | 58.7 ± 0.6 (58.0-59.0) | 0 in all 3 | $0.00000 in all 3 | 46.7 ± 0.6 (46.0-47.0) of 48 | 112 ± 4 (109-117) | 128 ± 2 (126-129) | 0 in all 3 | 0 in all 3 |

COLD against BASE in the same repeat: 763B tokens cut 56.2 ± 4.6 (50.9-59.2)%, 763B $ cut 49.8 ± 5.0 (44.1-53.4)% (earlier single run: -53.0% tokens, -46.5% $).

## Rerun

```
# .env: CHIMERA_DB_URL, CRUSOE_API_KEY, CHIMERA_GPU_URL (an SSH tunnel to your GPU box)
.venv/bin/python bench/company_cost/run_repeats.py cache 3
.venv/bin/python bench/company_cost/run_repeats.py bank 3
.venv/bin/python bench/company_cost/run_repeats.py ladder 3
.venv/bin/python bench/company_cost/report.py
```

Rows: `bench/.scratch/company_cost/` (git-ignored, one row per item, a rerun skips done rows). Price sources: [Modal H200](https://modal.com/blog/introducing-b200-h200), [Supabase pricing](https://supabase.com/pricing), Crusoe and GMI list prices as in `results_cost_case.md`.
