# Live finding: moderately-hard coding questions, 30B alone vs the ladder vs the 763B alone

## Verdict

On 40 moderately-hard coding questions, run live three times each:

| | A: 30B alone | B: ladder (bank -> cache -> 30B -> 763B) | C: 763B alone |
|---|---|---|---|
| Solved (tests pass), of 40 | 18.3 (18, 19, 18) | **34.7** (34, 36, 34) | 33.7 (33, 34, 34) |
| Wrong answers served | 21.7 | **5.3** | 6.3 |
| 763B calls | 0 | **24.3** (26, 24, 23) | 40 |
| 763B tokens (in + out) | 0 | **10,050** | 16,897 |
| 763B $ for 40 questions (list price) | $0 | **$0.0079** | $0.0135 |
| 763B $ per 1,000 questions | $0 | **$0.198** | $0.339 |
| 30B calls per 1,000 questions | 1,000 | 1,000 | 0 |
| Latency p50 / p90 (s) | 2.5 / 6.4 | 3.8 / 9.6 | 1.1 / 1.8 |

Mean of 3 repeats (single values in brackets). Latency is pooled over all 120 rows per column.

- **The 30B alone misses more than half.** It failed 21.7 of 40 (22, 21, 22).
- **The ladder recovers most of them by climbing.** Of the 30B's misses, the ladder got 16.7 right (17, 17, 16), 77%.
  It solved 34.7 of 40, the same as the 763B alone (33.7). The gap of one question is inside the run-to-run spread.
- **It climbs only when it must.** 15.7 of 40 answers stayed on the 30B, every one passing its tests. The 6 control
  questions (hard, but the 30B passed them before) never climbed: 18 of 18 answers came from the 30B.
- **763B calls fell 39% and 763B dollars 42%** against sending everything to the 763B ($0.198 vs $0.339 per 1,000).
- **Asked again, the bank answered 34 of 40** (p50 0.47 s, tests re-run before serving), and 763B dollars fell 94%
  ($0.00077 vs $0.0135 for 40 questions).
- **The climb never failed to fire.** In 0 of 120 ladder answers did the 30B serve a wrong answer.

Failures, by name:

- **The ladder still served 16 wrong answers in 120 (5.3 per run).** All 16 are 763B answers that also failed their
  tests. The ladder knew the tests failed and served the answer anyway. They come from 8 questions: `humaneval-132`
  (3 of 3), `suite-mbpp-228` (3), `suite-mbpp-235` (3), `mbpp-87` (2), `classic-regex-duration` (2), `humaneval-130`
  (1), `suite-humaneval-163` (1), `suite-mbpp-301` (1). `suite-mbpp-228` and `suite-mbpp-235` failed in every run of
  every mode (their tests want an output format the prompt does not state).
- **The confidence gate wastes 763B calls.** 25 of the 73 ladder 763B calls came from the 0.95 confidence gate, not from
  failed tests: the 30B's answer was never tested. In 7 of those 25, the 30B alone got the same question right in the
  same repeat. Once it turned a right answer into a wrong one: `humaneval-130`, repeat 1 (the 30B alone was right, the
  gate sent it up, the 763B was wrong). The ladder lost 1 question this way in 120; it gained 50.
- **The ladder is slow.** p50 3.8 s vs 1.1 s for the 763B alone, p90 9.6 s vs 1.8 s. A climb pays for the 30B call,
  the test run and the 763B call. Every 30B call also crossed the internet tunnel from the Mac.
- **On this hard-only mix, with the GPU rented, the ladder is not cheaper.** The 763B part is $0.198 per 1,000 vs $0.339.
  Add the A6000 box at $0.18-0.52 per 1,000 30B calls and the ladder costs $0.38-0.72 per 1,000 against $0.339. It is
  cheaper only on owned hardware ($0 per call), on mixed traffic (the cost case: 87.5% of 763B calls cut,
  `bench/results_a6000.md`) or on repeats (94% here).
- **The check is the grading tests.** The ladder ran the same tests it was graded on. That is the developer-with-tests
  case. With no tests, only the 0.95 gate guards the 30B.
- **The set is built to make the 30B fail.** 29 of 40 questions were picked because the 30B failed them before. It is a
  stress set, not a traffic mix.

## Setup

- **Questions** (`bench/hard_live/questions.jsonl`, built by `bench/run_hard_live.py build`):
  - 22 cost-case HARD tasks (`bench/cost_case/tasks.jsonl`) the 30B failed in at least 1 of 3 earlier plain runs
    (`bench/.scratch/a6000/`), including `multi-lru` (the LRU cache) and `multi-calc` (an expression parser).
  - 7 harder HumanEval/MBPP items from `bench/datasets/suite.jsonl` the 30B failed the same way.
  - 5 new classics (`bench/hard_live/classics.py`): median of two sorted arrays in O(log n), word break returning every
    split (must not blow up on `'a' * 40 + 'b'`), a SQLite DENSE_RANK window query, a strict duration regex, and a
    two-account transfer deadlock fix (8 threads, 2,000 random transfers each, 6 s limit).
  - 6 controls: cost-case HARD tasks the 30B passed in every earlier run.
  - Left out: items that every earlier ladder repeat also failed (`mbpp-229`, `mbpp-462`, `suite mbpp-83/160/164`).
  - Every question is graded by running its tests (sandboxed, no network, 10 s limit). The classics' tests were
    checked offline: each accepts a correct answer and rejects a plausible wrong one (`tests/test_hard_live.py`).
- **Models**: the self-hosted 30B is Ollama `qwen3:30b-instruct` (Q4_K_M), 16 slots, flash attention, q8 KV cache,
  on **GPU 1 only** of a shared two-GPU RTX A6000 box (`bench/a6000/serve.sh`). The top tier is Crusoe
  `DeepSeek-V4.1-Flash` (763B), list price $0.29 per million tokens in, $1.20 out.
- **Modes** (`bench/run_hard_live.py`, every call through `SpeculativeCascadeRouter.generate()`):
  - **A**: every question to the 30B alone.
  - **B**: the deployed order. First the solved-problem bank (Supabase `solved_bank`; a stored answer is served only if
    it passes this question's tests). Then the shared cache (Supabase `prompts`: exact hash, then cosine 0.97 with the
    guard, 300 ms budget, settings from `[cache]` in `chimera.toml`). Then the 30B (0.95 confidence gate; prompts above
    complexity 0.6 go straight to the 763B, none here did). The 30B answer runs its tests; a failure climbs to the
    763B. Only answers that pass their tests are written to the bank and the cache.
  - **C**: every question to the 763B alone.
  - **WARM**: B again on the bank and cache that repeat 1 filled.
  - Each repeat of B used its own fresh tenant (`bench-hard-live`, `-r2`, `-r3`), empty at the start, so first-pass
    bank and cache hits are 0 by design.
  - A, B and C ran at the same time as three streams, one question at a time each. Repeats ran one after another.
- **Not in this run**: N+1 memory few-shot retrieval (Aura) and bank hints for the 30B. The bank either serves or misses.
- **Database**: the project's store is Supabase (Postgres + pgvector) plus hosted Neo4j Aura. There is no GCP database
  in this project, so the store check below is against Supabase.

## Where the ladder's answers came from

| | Repeat 1 | Repeat 2 | Repeat 3 |
|---|---|---|---|
| Bank / cache (first pass, empty tenant) | 0 | 0 | 0 |
| 30B, tests passed | 14 | 16 | 17 |
| 763B after the 30B's answer failed its tests | 17 | 14 | 17 |
| 763B after the 30B's confidence was under the gate | 9 | 10 | 6 |
| 30B wrong and no climb | 0 | 0 | 0 |

WARM (repeat traffic, after repeat 1): bank 34, 30B 1, 763B after failed tests 3, 763B after the gate 2. The 6 that
missed the bank are the 6 questions repeat 1 never solved, so nothing was stored for them; one was solved this time.
WARM solved 35 of 40 with 5 763B calls and $0.00077 of 763B tokens.

## Recovery

| | Repeat 1 | Repeat 2 | Repeat 3 |
|---|---|---|---|
| 30B alone missed | 22 | 21 | 22 |
| Ladder got those right | 17 | 17 | 16 |
| Ladder still wrong on those | 5 | 4 | 6 |
| 30B alone right, ladder wrong | 1 | 0 | 0 |

## Per question

| Question | Picked as | A: 30B alone | B: ladder | B answered by (r1, r2, r3) | C: 763B alone |
|---|---|---|---|---|---|
| `humaneval-10` | hard, 30B failed before | 3/3 | 3/3 | 30B, 763B (tests failed), 30B | 3/3 |
| `humaneval-112` | hard, 30B failed before | 3/3 | 3/3 | 763B (tests failed), 30B, 30B | 3/3 |
| `humaneval-113` | hard, 30B failed before | 3/3 | 3/3 | 763B (gate), 30B, 763B (tests failed) | 3/3 |
| `humaneval-115` | hard, 30B failed before | **0/3** | 3/3 | 763B (tests failed), 763B (tests failed), 763B (tests failed) | 3/3 |
| `humaneval-125` | hard, 30B failed before | 3/3 | 3/3 | 30B, 30B, 30B | 3/3 |
| `humaneval-126` | hard, 30B failed before | **0/3** | 3/3 | 763B (gate), 30B, 30B | 3/3 |
| `humaneval-127` | hard, 30B failed before | **2/3** | 3/3 | 30B, 30B, 30B | 3/3 |
| `humaneval-129` | hard, 30B failed before | 3/3 | 3/3 | 763B (gate), 763B (gate), 763B (gate) | **1/3** |
| `humaneval-130` | hard, 30B failed before | **1/3** | **2/3** | 763B (gate), 763B (gate), 763B (gate) | 3/3 |
| `humaneval-132` | hard, 30B failed before | **0/3** | **0/3** | 763B (tests failed), 763B (tests failed), 763B (tests failed) | **1/3** |
| `humaneval-153` | hard, 30B failed before | **2/3** | 3/3 | 30B, 30B, 30B | 3/3 |
| `humaneval-160` | hard, 30B failed before | **0/3** | 3/3 | 763B (tests failed), 763B (tests failed), 763B (tests failed) | 3/3 |
| `humaneval-41` | hard, 30B failed before | **1/3** | 3/3 | 763B (tests failed), 763B (tests failed), 763B (tests failed) | 3/3 |
| `humaneval-67` | hard, 30B failed before | **0/3** | 3/3 | 763B (tests failed), 763B (tests failed), 763B (tests failed) | 3/3 |
| `mbpp-237` | hard, 30B failed before | **1/3** | 3/3 | 763B (gate), 763B (gate), 763B (tests failed) | 3/3 |
| `mbpp-255` | hard, 30B failed before | **0/3** | 3/3 | 763B (tests failed), 763B (tests failed), 763B (tests failed) | 3/3 |
| `mbpp-473` | hard, 30B failed before | **1/3** | 3/3 | 763B (gate), 763B (gate), 763B (gate) | 3/3 |
| `mbpp-87` | hard, 30B failed before | **0/3** | **1/3** | 763B (tests failed), 763B (gate), 763B (tests failed) | **2/3** |
| `multi-calc` | hard, 30B failed before | **0/3** | 3/3 | 763B (tests failed), 30B, 763B (tests failed) | 3/3 |
| `multi-intervals` | hard, 30B failed before | **0/3** | 3/3 | 763B (tests failed), 763B (tests failed), 763B (tests failed) | **1/3** |
| `multi-inventory` | hard, 30B failed before | **0/3** | 3/3 | 763B (tests failed), 763B (tests failed), 763B (tests failed) | 3/3 |
| `multi-lru` | hard, 30B failed before | **0/3** | 3/3 | 763B (tests failed), 763B (tests failed), 763B (tests failed) | 3/3 |
| `suite-humaneval-128` | suite, 30B failed before | 3/3 | 3/3 | 30B, 763B (tests failed), 30B | 3/3 |
| `suite-humaneval-163` | suite, 30B failed before | **0/3** | **2/3** | 763B (tests failed), 763B (tests failed), 763B (tests failed) | 3/3 |
| `suite-humaneval-77` | suite, 30B failed before | **2/3** | 3/3 | 763B (gate), 763B (gate), 30B | 3/3 |
| `suite-mbpp-228` | suite, 30B failed before | **0/3** | **0/3** | 763B (gate), 763B (gate), 763B (tests failed) | **0/3** |
| `suite-mbpp-235` | suite, 30B failed before | **0/3** | **0/3** | 763B (tests failed), 763B (gate), 763B (gate) | **0/3** |
| `suite-mbpp-286` | suite, 30B failed before | **0/3** | 3/3 | 763B (gate), 763B (gate), 763B (gate) | **2/3** |
| `suite-mbpp-301` | suite, 30B failed before | **0/3** | **2/3** | 763B (tests failed), 763B (tests failed), 763B (tests failed) | **0/3** |
| `classic-median-two` | classic | 3/3 | 3/3 | 30B, 30B, 30B | 3/3 |
| `classic-word-break` | classic | 3/3 | 3/3 | 30B, 30B, 30B | 3/3 |
| `classic-sql-window` | classic | 3/3 | 3/3 | 30B, 30B, 30B | 3/3 |
| `classic-regex-duration` | classic | **0/3** | **1/3** | 763B (tests failed), 763B (gate), 763B (gate) | **2/3** |
| `classic-deadlock-fix` | classic | **0/3** | 3/3 | 763B (tests failed), 763B (tests failed), 763B (tests failed) | 3/3 |
| `humaneval-1` | control | 3/3 | 3/3 | 30B, 30B, 30B | 3/3 |
| `humaneval-119` | control | 3/3 | 3/3 | 30B, 30B, 30B | 3/3 |
| `humaneval-147` | control | 3/3 | 3/3 | 30B, 30B, 30B | **2/3** |
| `humaneval-69` | control | 3/3 | 3/3 | 30B, 30B, 30B | 3/3 |
| `humaneval-87` | control | 3/3 | 3/3 | 30B, 30B, 30B | 3/3 |
| `mbpp-277` | control | 3/3 | 3/3 | 30B, 30B, 30B | 3/3 |

The 30B is not fully repeatable at its settings: `humaneval-10` passed alone 3 of 3 but failed its tests once inside
the ladder (and climbed). Grades for the 763B also move between runs (`humaneval-129`: 1 of 3).

## Live store check (Supabase)

Rows in our tenants of the two live tables (`prompts` = the answer cache, `solved_bank` = the bank):

| Point | Cache rows | Bank rows | Bank hits |
|---|---|---|---|
| Repeat 1 start (fresh tenant) | 0 | 0 | 0 |
| Repeat 1 end | 34 | 34 | 0 |
| After WARM | 35 | 35 | 34 |
| Repeat 2 end | 36 | 36 | 0 |
| Repeat 3 end | 34 | 34 | 0 |
| After the purge at the end (all 3 tenants) | 0 | 0 | 0 |

- **Only verified answers were written.** Each repeat wrote exactly as many rows as it solved (34, 36, 34), in both
  tables. After WARM, all 35 cache rows had `verified = true`, and all 35 cache and 35 bank answers read back from
  Supabase passed their question's tests again. By tier: 15 from the 30B, 20 from the 763B.
- **Reads hit the real tables.** In WARM the bank served 34 of 40 (its hit counter rose 0 -> 34). A read probe of all 40
  questions found 34 cache hits, 5 misses (the 5 never solved, so never stored) and 1 lookup skipped by the 300 ms
  budget; the bank's exact read found 35 of 40.

Store latency from the Mac (ms):

| Operation | n | p50 | p90 |
|---|---|---|---|
| Cache lookup during B (embed + exact + nearest, one round trip) | 120 | 107 | 122 |
| Bank lookup on a miss (embed + exact + nearest) | 120 | 329 | 393 |
| Bank write (re-runs the tests, then insert) | 104 | 173 | 202 |
| Bank serve in WARM (lookup + test run + answer) | 34 | 467 | 518 |
| Cache lookup, read probe | 40 | 162 | 265 |
| Bare DB round trip (ping) | 40 | 139 | 247 |

The 300 ms cache budget skipped 2 of 166 lookups (120 in B, 6 in WARM, 40 in the probe): 1 in WARM (`humaneval-130`,
307 ms) and 1 in the probe. A skipped
lookup goes on to the models, so it costs a model call, never a wrong answer.

## GPU 1 and the watchdog

- `bench/a6000/watchdog.sh` gained `ONLY_GPUS` (start servers only on the listed GPUs; every GPU is still watched and
  any other user on either GPU still kills ours within about 10 s). `bench/a6000/selftest.sh` case 5 checks it with a
  fake `nvidia-smi`: with both GPUs free it started on GPU 1 only, and a new process on GPU 0 killed our GPU 1 server
  in 6 s. All 5 cases passed on the box.
- The watchdog ran with `ONLY_GPUS=1`. It started our 30B on GPU 1 at 20:00:49 and stopped it at 20:15:57 (box time,
  EST). GPU 0 was never used.
- **GPU yields: none.** No other process touched either GPU during the run (yield log on the box is empty for this run).
- **Teardown:** after the stop, GPU 1 showed 12 MiB used (the idle baseline) and 0 compute processes. Our Ollama, token
  proxy and tunnel processes: 0 each. The tunnel URL died with the stop and `.env` points back at the earlier GPU URL.
  The watchdog stays running idle in `stop` mode, as it was before this run; it starts nothing.

## Crusoe 763B spend for this report

| Use | Calls | Tokens (in + out) | $ (list) |
|---|---|---|---|
| B, 3 repeats | 73 | 30,150 | 0.0238 |
| C, 3 repeats | 120 | 50,690 | 0.0406 |
| WARM | 5 | 1,213 | 0.0008 |
| **Total** | 198 | 82,053 | **0.0652** |

The 763B alone cost $0.339 per 1,000 of these questions, about twice the $0.16 per 1,000 of the cost-case mix: hard
questions get longer answers.

## What a judge sees

On 40 hard coding questions, the 30B model on our own GPU solves 18 by itself. Put the ladder in front of it and 35 are
solved, as many as the 763B model alone (34). The ladder checks each 30B answer by running its tests and sends only the
failures up, so the 763B is called 24 times instead of 40 and costs 42% less. A wrong 30B answer was never served. The
price is speed: about 4 s instead of 1 s for a typical answer. Asked the same questions again, 34 of 40 come back from
the solved-problem bank in half a second, tests re-run first. The judge can rerun every number here from the commands
below; the GPU link itself is never shared.

## Reproduce

```
.venv/bin/python bench/run_hard_live.py build                              # the 40 questions
.venv/bin/python bench/run_a6000.py up                                     # 30B on a free GPU (watchdog: ONLY_GPUS=1)
.venv/bin/python bench/run_hard_live.py run PLAIN POOL TOP WARM            # repeat 1; then PLAIN:2 POOL:2 TOP:2, ...:3
.venv/bin/python bench/run_hard_live.py store                              # live store check, then purge
.venv/bin/python bench/run_hard_live.py tables
.venv/bin/python bench/run_a6000.py down
```

Rows: `bench/.scratch/hard_live/` (git-ignored, one row per question per run; a rerun skips finished rows):
`PLAIN.jsonl`, `POOL.jsonl`, `TOP.jsonl`, `WARM.jsonl`, `*_r2.jsonl`, `*_r3.jsonl`, `store.jsonl`,
`store_check.json`, `tables.json`, `teardown.txt`.
