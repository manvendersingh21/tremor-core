# Backend v3: the whole product path on the tuned self-hosted 30B, with repeats and failure modes

Date 2026-11-16 (PST), 07:20 to 09:00. All runs from the Mac. The 30B is Ollama `qwen3:30b-instruct` on our V100, our own
tuned server ([`results_akash_tuning.md`](results_akash_tuning.md): flash attention, q8 KV, 4 slots), reached over an SSH
tunnel to your GPU box. Top tier: Crusoe `deepseek-ai/DeepSeek-V4.1-Flash` (763B, thinking off). No Modal, no GPU spend:
`modal app list` showed no app on the current profile before the runs. Rows: `bench/.scratch/backend_v3/` (git-ignored,
one row per item, resumable). Tables: `bench/backend_v3_report.py`.

"Before tuning" rows are the earlier runs on the same box with default Ollama threads: the 3-repeat ladder and bank runs
in [`results_company_cost.md`](results_company_cost.md), the 300-question suite in [`results_suite.md`](results_suite.md),
the terminal coder in [`results_terminal_agent.md`](results_terminal_agent.md).

## Verdict

- **The 30B is no longer the slow part.** Ladder COLD median 6.7 s -> **2.8 s**, p90 21.5 s -> **6.6 s** (3 repeats each).
  Suite POOL median 86.1 s -> **4.2 s**. Terminal coder median 91.7 s -> **6.0 s** per task. The longest single 30B call
  in the ladder and suite runs was 14.0 s. **No call reached the 90 s timeout.**
- **Savings and quality did not change, as expected.** Tuning changed speed, not routing. COLD cut 763B tokens by
  56.4 ± 1.6% (before: 56.2 ± 4.6%). Graded correct 46.7 of 48 in both. 0 wrong cache answers in 6 repeats. The suite cut
  763B tokens 37.4% (before 38.4%) and passed 165/180 test-graded items (before 162/180, 763B alone 170/180).
- **The ladder is still slower than the 763B alone.** COLD median 2.8 s vs 1.5 s for BASE; suite median 4.2 s vs 1.1 s.
  Calls that climb pay for the 30B try and then the 763B (Dolly and Quora items: median 9.0 and 14.1 s).
- **Failure modes: every call that could be answered was answered, none empty, none wrong.** Six product bugs (three
  seen live, three found while reading the code for these checks) and one bench-harness bug were fixed, each with an
  offline test (table below).
- **Against the 763B, the owned V100 still does not pay for itself on this mix.** COLD saved $0.096 of 763B tokens per
  1,000 calls ($0.193 -> $0.097). The tuned V100 costs $0.18 to $0.52 per 1,000 calls when kept busy. The saving is real
  only against a pricier model (GPT-5.5 at $4.02 per 1,000), as `results_company_cost.md` already says.

Bugs found and fixed:

| Bug | How it showed | Fix | Test |
|---|---|---|---|
| Benches built their own 30B tier without `num_thread = 4` or `keep_alive`, timeout 90 or 180 s | Bench calls would run at default threads (20 tok/s), and mixed runner options reload the model on the box (one 13 s reload seen at the start) | `config.product_tier("gpu-small")`: `run_backend`, `run_suite`, the bank's `call30` and `apps/replay` use the product's entry. The product timeout is 90 s, was 180 | `test_product_tier_reads_the_tuned_30b_entry` |
| The H200 tier woke itself: a cold warm-check sent a request that starts the Modal app | Code read: `enabled = true` plus a `MODAL_QWEN_URL` would start a billed H200 on the first cold check | New `wake` flag, default false. Cold = skipped, never started. `bench/run_h200_tier.py` turns it on for its own test | `test_cold_warm_only_tier_is_never_started_without_wake`, `test_example_config_never_auto_starts_the_h200` |
| No retry on a 763B 429 in pool mode, and an empty answer could be served | Code read; only the non-pool gateway retried | The 763B tier retries twice on 429 or 5xx (Retry-After, max 10 s). An empty answer climbs, never served | `test_openai_tier_retries_429_then_answers`, `test_empty_answer_climbs_and_is_never_served` |
| After a 429 storm the only 763B tier was marked down for 15 s | Live: the next call failed in 246 ms without sending a request | An HTTP error (the server answered) counts for the breaker only, not as "down" | `test_http_error_does_not_mark_a_lone_top_tier_down` |
| An Aura that never answers added 10 s to every call | Live: memory retrieve 10,005 ms on each of 3 calls | Memory skips the graph for 60 s after an error. Live after the fix: 10,007 ms on the first call, then 0.02 ms | `test_graph_error_skips_the_graph_for_a_cooldown` |
| The first cache lookup of every process ran past its 300 ms budget and skipped the cache | Live: the first COLD lookup was "unavailable" (312 ms) in all 3 repeats, and in every fault run | `build_router` opens the DB link in the background. Live after the fix: 3 of 3 first lookups "ok" | `test_shared_cache_link_is_opened_at_build` |
| Bench harness: `chimera code` refused every task file | Live: 6 of 15 tasks failed, "refused rangeutil.py: ignored by .gitignore". Task folders had moved into the git-ignored `bench/.scratch` (an uncommitted edit by another chat) | Each task folder is its own git repo | rerun below |

## 1. Product path checks

| Check | Result |
|---|---|
| 30B tier used by the router | `gpu-small` from `chimera.toml`: `options = {num_thread = 4}`, `keep_alive = -1`, timeout 90 s. Server: our Ollama 0.40.16, model fully on the GPU, `keep_alive` forever. A warm direct call: 400 tokens in 4.6 s (87 tok/s); the call before it waited 13 s for a model reload |
| 90 s timeout | Never reached. Longest 30B call: 11.1 s (ladder), 14.0 s (suite). 0 timeouts in 157 ladder and 298 suite 30B calls |
| Tunnel self-heal | Killed: back in 4.3, 7.8 and 7.9 s. Frozen: back in 21.7 and 22.2 s (watcher probe every 5 s, kills after 2 misses). Every next call went to the 30B again |
| H200 30B tier | `warm_only = true`, `wake = false`. With no app deployed, `modal_running` = False and the tier is skipped. Default order stays `gpu-h200` (only while warm), `gpu-small`, `cloud-deepseek`. No H200 call in any run |

## 2. 60-prompt ladder: BASE, COLD, WARM, 3 repeats

Same 60 prompts and `bench/run_backend.py` as v2. BASE = 763B only. COLD = fresh namespace: Supabase cache -> GPU 30B
(gate 0.95) -> 763B. WARM = the same prompts again. Each repeat: own namespace, deleted after.
`REPEATS_OUT=bench/.scratch/backend_v3/repeats REPEATS_TAG=v3 bench/company_cost/run_repeats.py ladder 3`.
Cells are mean ± sd (min-max) over 3 repeats.

| Pass | Run | 763B calls | GPU 30B calls | Cache hits | 763B tokens | 763B $ | Graded correct | Wrong cache answers | p50 ms | p90 ms | Calls >= 90 s | Errors |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BASE | before tuning | 60 | 0 | 0 | 12994 ± 331 | $0.01190 ± $0.00040 | 44.3 ± 0.6 of 48 | 0 | 1337 ± 62 | 2868 ± 179 | 0 | 0 |
| BASE | **tuned** | 60 | 0 | 0 | 12714 ± 129 | $0.01156 ± $0.00015 | 45.3 ± 0.6 of 48 | 0 | 1513 ± 170 | 3000 ± 780 | 0 | 0 |
| COLD | before tuning | 12.7 ± 0.6 | 51 | 5 | 5705 ± 730 | $0.00598 ± $0.00077 | 46.7 ± 0.6 of 48 | 0 | 6677 ± 585 | 21523 ± 755 | 0 | 0 |
| COLD | **tuned** | 11.3 ± 0.6 | 51 | 5 | 5544 ± 153 | $0.00583 ± $0.00014 | 46.7 ± 0.6 of 48 | 0 | **2799 ± 44** | **6562 ± 813** | 0 | 0 |
| WARM | before tuning | 0 | 1.3 ± 0.6 | 58.7 ± 0.6 | 0 | $0 | 46.7 ± 0.6 of 48 | 0 | 112 ± 4 | 128 ± 2 | 0 | 0 |
| WARM | **tuned** | 0.3 ± 0.6 | 1.3 ± 0.6 | 58.7 ± 0.6 | 54 ± 94 | $0.00003 ± $0.00006 | 46.7 ± 0.6 of 48 | 0 | 106 ± 2 | 116 ± 2 | 0 | 0 |

COLD against BASE in the same repeat: 763B tokens cut 56.4 ± 1.6% (55.0-58.1), 763B $ cut 49.5 ± 1.9% (48.2-51.6).
Before tuning: 56.2 ± 4.6% and 49.8 ± 5.0%.

Who answered (tuned):

| Pass | Repeat 1 | Repeat 2 | Repeat 3 |
|---|---|---|---|
| COLD | 30B 44, 763B 11, cache 5 | 30B 44, 763B 11, cache 5 | 30B 43, 763B 12, cache 5 |
| WARM | cache 59, 30B 1 | cache 58, 763B 1, 30B 1 | cache 59, 30B 1 |

Every GPU 30B call inside the ladder (from telemetry):

| Run | 30B calls per repeat | p50 ms | p90 ms | max ms | >= 90 s | Errors |
|---|---|---|---|---|---|---|
| before tuning | 52, 52, 53 | 6897-8426 | 19733-21431 | 47248-51023 | 0 | 0 |
| **tuned** | 52, 53, 52 | **2198-2277** | **4847-6276** | **9840-11145** | 0 | 0 |

Per 1,000 calls of this mix: BASE $0.193 of 763B tokens, COLD $0.097, WARM $0.0005. The owned 30B is not priced in these
cells.

## 3. 300-question suite (POOL)

`BENCH_STORE=bench/.scratch/backend_v3/suite bench/run_suite.py POOL`: Supabase cache (own tenant, purged before and after)
-> GPU 30B -> 763B. The TOP row (763B only) is the earlier run; the 763B did not change. Dolly rows were not judged in
this rerun (no judge call was made), so pass counts cover the 180 items graded by tests, exact match or choice letter.

| Run | 763B calls | 763B tokens | 763B $ | Pass (180 graded) | p50 ms | p90 ms | Sum of latencies | Errors | Empty | Answered by |
|---|---|---|---|---|---|---|---|---|---|---|
| TOP (763B only) | 300 | 103,067 | $0.1020 | 170/180 | 1,121 | 4,451 | 570 s | 0 | 0 | 763B 300 |
| POOL before tuning | 123 | 63,514 | $0.0733 | 162/180 | 86,074 | 136,073 | 26,206 s | 0 | 0 | 30B 175, 763B 123, cache 2 |
| **POOL tuned** | 125 | 64,536 | $0.0745 | 165/180 | **4,169** | **15,018** | **1,854 s** | 0 | 0 | 30B 173, 763B 125, cache 2 |

| Source/type | n | Pass TOP | Pass POOL before | Pass POOL tuned | Median ms TOP / before / tuned | 763B calls before / tuned |
|---|---|---|---|---|---|---|
| dolly/easy | 60 | not judged | not judged | not judged | 2812 / 101876 / 9020 | 54 / 54 |
| gsm8k/hard | 30 | 29/30 | 30/30 | 30/30 | 1200 / 86634 / 4485 | 4 / 4 |
| humaneval/code | 40 | 38/40 | 36/40 | 36/40 | 961 / 87280 / 3814 | 1 / 0 |
| humaneval/hard | 15 | 15/15 | 11/15 | 11/15 | 1521 / 104659 / 6382 | 1 / 1 |
| mbpp/code | 35 | 29/35 | 27/35 | 30/35 | 709 / 74951 / 1860 | 2 / 4 |
| mmlu/easy | 60 | 59/60 | 58/60 | 58/60 | 533 / 67740 / 938 | 3 / 4 |
| qqp/repeat | 60 | n/a | n/a | n/a | 3978 / 97949 / 14123 | 58 / 58 |

763B tokens cut 37.4%, 763B $ cut 27.0% (before tuning: 38.4% and 28.1%). Cache: 2 of 24 real duplicate questions served,
0 wrong-source hits. 298 30B attempts: p50 3.7 s, p90 10.1 s, max 14.0 s, 0 errors.

## 4. Terminal coder (`chimera code`, 15 tasks)

`bench/run_terminal_agent.py --mode auto --no-bank`: one `chimera code` process per task, the product's tier pool
(H200 skipped, cold), a failed test climbs, at most 3 repair rounds. The bank was off so the 30B is measured; the run
with the bank on is shown too. Earlier rows are from before the bank existed in `chimera code`.

| Run | Passed | Fully on the 30B | Reached the 763B | Calls | Repair rounds | Tokens | 763B $ | Model s (sum) | Median s per task |
|---|---|---|---|---|---|---|---|---|---|
| 763B only (earlier) | 15/15 | 0 | 15 | 17 | 2 | 6,641 | $0.00415 | 121 | 5.5 |
| ladder before tuning | 15/15 | 13 | 2 | 19 | 4 | 7,363 | $0.00102 | 1,430 | 91.7 |
| **ladder tuned, bank off** | 15/15 | 11 | 4 | 19 | 4 | 7,646 | $0.00107 | **95** | **6.0** |
| ladder tuned, bank on | 15/15 | 13 | 2 | 18 | 3 | 4,611 | $0.00092 | 62 | 4.3 |

- Tasks that climbed (bank off): #4 regex validator, #8 docstrings, #11 rename across 2 files, #14 LRU cache. Before
  tuning: #4 and #8. The 30B samples at Ollama's default temperature, so 2 more climbs is within run-to-run noise on
  15 tasks.
- Bank on: 8 of 15 tasks came from the bank with 0 tokens. The bank was filled by this session's earlier runs, so this
  row shows a repeat, not a first run.
- The first attempt (before the harness fix) failed 6 of 15: the harness put task folders inside the git-ignored
  `bench/.scratch`, and `chimera code` correctly refused git-ignored files. Rows kept in
  `bench/.scratch/backend_v3/terminal_v3auto_gitignored.jsonl`.

## 5. Solved-problem bank, runs 2 and 3, 3 repeats

`REPEATS_OUT=bench/.scratch/backend_v3/repeats REPEATS_TAG=v3 bench/company_cost/run_repeats.py bank 3`. Run 2 asks the
same 80 problems, run 3 asks 80 reworded copies. Misses in run 3 make fresh 30B and 763B calls (temperature 0).

| Run | Served (exact/cosine) | Hint only | Miss | 30B calls | 763B calls | 763B $ | Solved | Median lookup ms |
|---|---|---|---|---|---|---|---|---|
| 2 same, before tuning | 75 (75/0) | 2 | 3 | 5 | 5 | $0.0026 | 75 | 448 ± 11 |
| 2 same, **tuned** | 75 (75/0) | 2 | 3 | 5 | 5 | $0.0026 | 75 | 444 ± 4 |
| 3 reworded, before tuning | 24 (0/24) | 40 | 16 | 56 | 7.7 ± 0.6 | $0.0066 ± $0.0002 | 74.3 ± 0.6 | 271 ± 9 |
| 3 reworded, **tuned** | 24 (0/24) | 40 | 16 | 56 | 7.3 ± 0.6 | $0.0061 ± $0.0010 | 74.3 ± 1.2 | 265 ± 3 |

Same counts in all 3 repeats, as expected: lookups use fixed embeddings and cut-offs. 0 wrong answers served (every served
answer passed its tests first). Run 2 replays saved 30B answers for its 5 misses, so it does not time the 30B.

## 6. Failure modes (`bench/run_faults.py`)

Product router (`build_router` with `chimera.toml`), own tenant, purged after.

| Case | What broke | Calls | Answered | Right | Empty | No answer | Answered by | Result |
|---|---|---|---|---|---|---|---|---|
| tunnel | ssh killed 2 s into a long 30B call | 3 | 3 | 3 | 0 | 0 | 763B 3 | 2 calls lost the 30B mid-answer (`RemoteDisconnected` after 0.6 s) and climbed; in the first the tunnel died before the 30B was tried. Healed in 4.3-7.9 s; next call on the 30B |
| hung | ssh frozen (SIGSTOP) 2 s into a 30B call | 2 | 2 | 2 | 0 | 0 | 763B 2 | The 30B call waited 18.3 s until the watcher killed the ssh, then climbed. Healed in 21.7-22.2 s |
| supabase | DSN at a closed port | 3 | 3 | 3 | 0 | 0 | 30B 3 | Cache "unavailable" (310 ms, then skipped after 2 strikes), calls answered in 0.6-0.8 s |
| supabase | DSN at an address that never answers | 3 | 3 | 3 | 0 | 0 | 30B 3 | Same |
| neo4j | Aura URL at a closed port | 3 | 3 | 3 | 0 | 0 | 30B 3 | Memory retrieve 1 ms, no context |
| neo4j | Aura URL that never answers, before the fix | 3 | 3 | 3 | 0 | 0 | 30B 3 | **Every call +10 s** (retrieve 10,005 ms) |
| neo4j | the same after the fix | 3 | 3 | 3 | 0 | 0 | 30B 3 | First call +10 s, then 0.02 ms |
| ratelimit | 763B answers 429 once | 2 | 2 | 2 | 0 | 0 | 763B 2 | Retried after Retry-After, answered |
| ratelimit | 429 then 503 | 2 | 2 | 2 | 0 | 0 | 763B 2 | Retried twice, answered |
| ratelimit | 429 three times (763B-only router) | 2 | 0 | - | 0 | 2 | - | No tier left: `AllTiersFailed`, no empty or wrong text. The second call sent no request: the bug fixed above |
| ratelimit | 429 x3, then Crusoe fine (after the fix) | 2 | 1 | 1 | 0 | 1 | 763B 1 | The next call goes out and is answered |

The 429s came from a local proxy in front of the real Crusoe API (it answers 429 or 503 first, then passes the call on).
No real rate limit was triggered. The "never answers" address is 192.0.2.1 (TEST-NET-1, reserved for documentation).

## What this changes in the story

- Drop "the ladder is slow because of the 30B". With the tuned server the 30B answers in about 2.2 s per call (p50) and
  never came near the 90 s timeout. What is left is the climb cost: a question the 30B cannot answer pays for both tiers.
- Keep "the ladder is slower than calling the 763B": 2.8 s vs 1.5 s median on the 60 prompts, 4.2 s vs 1.1 s on the suite.
  The gap is now about 2 to 4 times, not 5 to 77 times.
- The saving numbers stand: about 56% of 763B tokens on the 60 prompts (now with a 1.6-point spread over 3 repeats) and
  37% on the 300-question suite, 0 wrong cache answers.
- The coding demo is now realistic in time: `chimera code` takes about 6 s per task on the ladder vs 5.5 s on the 763B
  alone, and 15/15 pass in both.
- The money case is unchanged: against the 763B, the V100 costs more per call than the 763B tokens it saves. It pays
  against expensive models.
- The product now survives a dead tunnel, a hung tunnel, Supabase down, Aura down and a 763B 429 without a wrong or
  empty answer. Two of those (Aura that never answers, a 429 storm) needed the fixes above.

## Limits and risks

- Each 30B answer is sampled (Ollama's default temperature in the ladder, suite and terminal runs; the bank uses 0),
  so the 15-task and 60-prompt counts move by 1 or 2 between runs. The suite and terminal runs are single runs.
- Other chats may have used the 30B box during the runs (the web page on 127.0.0.1:8765 was up). Latency is as measured.
- Any caller that still builds its own Ollama options (`bench/run_ladder.py`, `bench/cost_case/run_tiers.py`,
  `bench/run_bench_gpu.py`) reloads the model on the box when it alternates with the product. Those files were not
  changed: `run_ladder.py` has uncommitted edits by another chat.
- The terminal runs wrote passing answers for the 15 bench tasks into the product bank tenant `default:terminal` (as the
  v2 run did). They were not purged, because a purge deletes the whole tenant.
- The Supabase-down check covers a closed port and an address that never answers, not a slow database. The tunnel checks
  cover kill and freeze of the Mac side, not a crash of Ollama on the box.
- Neo4j logs a deprecation warning on every vector query (`db.index.vector.queryNodes` is replaced by `SEARCH`). Not fixed.
- Test count: 287 offline tests pass on the Mac (`pytest -q tests`).

## Rerun

```
make gpu-keep &    # SSH tunnel to your GPU box, self-healing
REPEATS_OUT=bench/.scratch/backend_v3/repeats REPEATS_TAG=v3 .venv/bin/python bench/company_cost/run_repeats.py ladder 3
BENCH_STORE=bench/.scratch/backend_v3/suite .venv/bin/python bench/run_suite.py POOL
.venv/bin/python bench/run_terminal_agent.py --mode auto --label v3nobank --no-bank --fresh
REPEATS_OUT=bench/.scratch/backend_v3/repeats REPEATS_TAG=v3 .venv/bin/python bench/company_cost/run_repeats.py bank 3
.venv/bin/python bench/run_faults.py ratelimit supabase neo4j tunnel hung
.venv/bin/python bench/backend_v3_report.py
```
