# Solved-problem bank: does looking a problem up first save model calls?

Single run. The bank holds verified problem/solution pairs in Supabase `solved_bank` (pgvector), and every banked pair is also written to the Aura graph. `bank.lookup` tries an exact hash, then cosine >= 0.9. A match is served only if its answer passes the asked problem's unit tests in the sandbox; a weaker match (>= 0.7) or one whose tests fail becomes a hint for the 30B; a miss goes to the ladder (30B, then the 763B), and a passing answer is written back.

## Plain words

- Run 1 (empty bank, 80 problems) made 80 30B calls and 12 big-model calls ($0.0043).
- Run 2 (same problems, bank filled) served 75 of 80 from the bank (93.8%) and made 5 30B calls and 5 big-model calls ($0.0026).
- Run 3 (80 reworded copies) served 24 (30.0%): 24 by cosine after passing tests, 40 only as a hint, 16 misses. Calls: 56 30B, 7 big ($0.0065). Tests caught 0 wrong matches.
- Bank size: 374 pairs {'mbpp': 127, 'humaneval': 95, 'custom': 152}; lookups so far counted 99 served hits.

## Table

| Run | Problems | Served (exact/cosine) | Hint only | Miss | Wrong hits caught | 30B calls | Big calls | Big $ | Big tokens | Solved | Median lookup ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 cold | 80 | 0 (0/0) | 11 | 69 | 0 | 80 | 12 | $0.0043 | 5310 | 75 | 298 |
| 2 same problems | 80 | 75 (75/0) | 2 | 3 | 0 | 5 | 5 | $0.0026 | 2581 | 75 | 472 |
| 3 reworded copies | 80 | 24 (0/24) | 40 | 16 | 0 | 56 | 7 | $0.0065 | 5770 | 75 | 336 |

Avoided by the bank, run 2 vs run 1: 75 30B calls, 7 big calls, $0.0018, 2729 big tokens.
Run 3 vs run 1 (same problems, reworded): 24 fewer 30B calls, 5 fewer big calls, big $ changed by -0.0021 (negative means run 3 cost more than run 1).

## Verdict

- Same problem again: works. 75 of 80 came from the bank after their tests passed, at about 472 ms per lookup (the sandbox test run is most of that). This is the easy case: the exact text was banked.
- Reworded problem: partial. 30.0% served; the rest went down the ladder. Run 3 cost more big-model $ than run 1 (0.0065 vs 0.0043) although it made fewer big calls; the cause was not measured (run 1 replays saved answers, run 3 made fresh calls with their own token counts). Rewording was done by the 30B itself, so some copies may have changed the task.
- Tests are what make serving safe. Without them, cosine alone would have shipped wrong answers: see the probe table (at 0.70, most matches fail the asked problem's tests). In run 3 the 0.90 cut-off meant 0 wrong matches reached the test step, so the test gate was never the thing that saved us here; it is untested on a wrong close match.
- Run 1 is not a clean cold run for the bank: write-back during the run gave 11 hints from near-duplicate problems in the same set. Run 1 replays saved model answers, so its 30B and big-call counts are the earlier measured ones.
- One run, 80 problems, temperature 0. Dollar amounts are fractions of a cent, so call counts are the better signal.

## Wrong hits: would a different problem's answer have been wrong?

No model calls. For each test problem, the nearest other bank entry (its own entry left out) is run against this problem's tests. A pass means reuse was right; a fail is a wrong hit that serving without tests would have shipped.

| Cosine at or above | Matches | Pass its tests | Fail its tests (wrong hit) |
|---|---|---|---|
| 0.7 | 36 | 2 | 34 |
| 0.8 | 11 | 2 | 9 |
| 0.85 | 5 | 2 | 3 |
| 0.9 | 2 | 2 | 0 |
| 0.95 | 2 | 2 | 0 |

Probe covered 80 of 80 test problems.

## Where it did not help

- 56 reworded copies were not served; 40 of them still got a hint for the 30B.
- 5 problems were unsolved in run 1 and so never banked: humaneval-163, mbpp-164, mbpp-438, mbpp-430, mbpp-143.
- Run 1 replays saved 30B and 763B answers (same prompts, temperature 0); only reworded copies made new model calls. Hints for the 30B were used on those new calls only.
- The graph write used the keyword extractor (no model call), so graph concepts here are coarser than in `results_memory.md`.
- Embedding ran with MiniLM on the Mac (about 600 short texts, cached on disk), not on the GPU box: it was not heavy enough to move.
- Not built: a LeetCode-style open set. HumanEval, MBPP, the suite code rows and every 763B answer that passed are banked.

## Rerun

```
# open an SSH tunnel to your GPU box first; CRUSOE_API_KEY, CHIMERA_DB_URL, CHIMERA_GRAPH_* in .env
.venv/bin/python bench/bank/run_bank.py all
.venv/bin/python bench/bank/run_bank.py report
```

Rows are cached in `bench/.scratch/bank/`. Remove the bank rows with `Bank.purge()` (tenant `bench-bank`). Design: `docs/memory.md`.
