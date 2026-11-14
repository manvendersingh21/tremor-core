# Terminal coding agent (`chimera code`): ladder vs 763B only

Setup: 15 scripted tasks (`bench/terminal_tasks.py`), one `chimera code -m ... --yes` subprocess per task in a
fresh scratch repo. The agent's check is the task's test file; grading reruns a hidden copy of it plus a
static check (docstrings, type hints, helper count) where the task asks for one. Ladder: Supabase cache
(exact, then cosine 0.97 + guard, namespace keyed by a hash of the context files), then the self-hosted
30B (Ollama `qwen3:30b-instruct` on a V100 over an SSH tunnel), then Crusoe `DeepSeek-V4.1-Flash` (763B).
A failed check climbs one tier; at most 3 repair rounds. Single run each, no repeats.

## Summary

- **13 of 15 tasks were done fully local** (30B only, tests pass, the 763B never called). 13 of 15 passed without the 763B; 2 climbed to it.
- Passed: ladder 15/15, 763B only 15/15.
- Tokens kept off the big model: 5397 of 7363 ladder tokens. The 763B-only run sent 6641 tokens to it.
- Dollars at list price: ladder $0.00102 vs 763B only $0.00415 (76% less). The 30B's GPU time is not priced (owned hardware).
- Time: the ladder is much slower. Model seconds 1430 s vs 121 s; median per task 92 s vs 5.5 s. The 30B call itself took 30 to 150 s on the shared V100 box.
- Cache: 0 hits. Every task is a new prompt and each run used a fresh namespace, as planned.

## Totals

| run | passed | calls | repair rounds | tokens | $ | agent seconds |
|---|---|---|---|---|---|---|
| ladder (auto) | 15/15 | 19 | 4 | 7363 | 0.00102 | 1430 |
| 763B only (/tier cloud) | 15/15 | 17 | 2 | 6641 | 0.00415 | 121 |

## Per task

| # | task | ladder pass | tiers (in order) | repairs | tokens | $ | s | 763B-only pass | 763B-only tokens | 763B-only $ | 763B-only s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | fizzbuzz + tests | yes | gpu-small | 0 | 397 | 0.00000 | 114.6 | yes | 939 | 0.00081 | 29.9 |
| 2 | off-by-one | yes | gpu-small | 0 | 496 | 0.00000 | 81.4 | yes | 494 | 0.00018 | 5.8 |
| 3 | add CLI flag | yes | gpu-small | 0 | 256 | 0.00000 | 70.4 | yes | 307 | 0.00021 | 5.5 |
| 4 | regex validator | yes | gpu-small>cloud-deepseek | 1 | 777 | 0.00023 | 84.0 | yes | 212 | 0.00012 | 5.5 |
| 5 | SQL helper | yes | gpu-small | 0 | 238 | 0.00000 | 123.4 | yes | 247 | 0.00015 | 5.3 |
| 6 | refactor | yes | gpu-small | 0 | 414 | 0.00000 | 91.7 | yes | 438 | 0.00031 | 5.5 |
| 7 | type hints | yes | gpu-small | 0 | 270 | 0.00000 | 45.1 | yes | 294 | 0.00020 | 5.3 |
| 8 | docstrings | yes | gpu-small>cloud-deepseek>cloud-deepseek>cloud-deepseek | 3 | 1705 | 0.00078 | 91.0 | yes | 852 | 0.00035 | 22.2 |
| 9 | fix failing test | yes | gpu-small | 0 | 543 | 0.00000 | 148.3 | yes | 555 | 0.00020 | 5.4 |
| 10 | word counts | yes | gpu-small | 0 | 276 | 0.00000 | 128.2 | yes | 228 | 0.00013 | 4.8 |
| 11 | rename across 2 files | yes | gpu-small | 0 | 235 | 0.00000 | 59.1 | yes | 248 | 0.00015 | 4.8 |
| 12 | config loader | yes | gpu-small | 0 | 202 | 0.00000 | 71.6 | yes | 232 | 0.00015 | 4.7 |
| 13 | HARD: todo done command (2 files) | yes | gpu-small | 0 | 825 | 0.00000 | 116.0 | yes | 632 | 0.00041 | 5.5 |
| 14 | HARD: LRU cache class | yes | gpu-small | 0 | 302 | 0.00000 | 94.4 | yes | 378 | 0.00031 | 5.0 |
| 15 | HARD: report --format (2 files) | yes | gpu-small | 0 | 427 | 0.00000 | 110.7 | yes | 585 | 0.00045 | 5.6 |

## Where local failed and climbed

- #4 regex validator: tiers gpu-small>cloud-deepseek, 1 repair round(s), final PASS
- #8 docstrings: tiers gpu-small>cloud-deepseek>cloud-deepseek>cloud-deepseek, 3 repair round(s), final PASS

## Earlier runs (same tasks, before parser fixes)

- Run 1 (Mac 3B first): stopped after 8 tasks. The 3B wrapped edits in the wrong format; 30B replies with a
  `hello.py: main` path line or an unpathed SEARCH block were not parsed. Fixed in `apps/terminal/edits.py`.
- Run 2 (30B first): 13/15 passed. #8 docstrings: the 30B replaced the bodies, the 763B then stacked
  docstrings and failed. #9: the 30B echoed the file in the context format (`--- stack.py ---`), which was
  not parsed. Both fixed (whole-file blocks in context format; a reply with no edits counts as a failed round
  and climbs). Run 3 above is the result after the fixes.

## Verdict

The ladder keeps most coding work off the 763B and cuts list-price dollars, at the cost of about 17x more
wall time per task, because the shared V100 30B answers in 45 to 150 s. Both runs passed every task.

## Reproduce

```
# open an SSH tunnel to your GPU box (Ollama), then point the 30B tier at its local end:
export CHIMERA_GPU_URL=http://127.0.0.1:<local port>
.venv/bin/python bench/run_terminal_agent.py --mode auto --label auto
.venv/bin/python bench/run_terminal_agent.py --mode cloud --label cloud
.venv/bin/python bench/run_terminal_agent.py --report
```
