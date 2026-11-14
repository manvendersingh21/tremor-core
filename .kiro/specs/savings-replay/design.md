# Design: savings replay (planned)

## Flow
```
telemetry.jsonl / suite.jsonl -> scrub -> arm A: ladder    -> grade
                                       -> arm B: 763B only -> grade
                              -> bench/results_replay.md (per-arm totals, loss list)
```

## Reuse
| Need | Existing |
|---|---|
| Prompts and grading | `bench/datasets/`, `bench/run_suite.py`, `bench/datasets/grade.py` |
| Cost tables | `bench/cost_case/report.py` |
| Telemetry rows | `packages/chimera-core/inference/telemetry.py` |
| Eval log | `bench/evallog.py`, `deploy/sql/004_eval_runs.sql` |

## Decisions
- New code stays under `bench/` as one runner, `bench/run_replay.py`. Product code is not touched.
- Dry mode replays recorded answers so tests need no models.

## Correctness properties
Router properties are owned by `.kiro/specs/chimera-speculative-os/`.

| ID | Property | Requirement |
|---|---|---|
| P1 | Totals equal the sum of the per-call rows, for any input. | R2.2 |
| P2 | A prompt where the ladder failed and the top passed always appears in the loss list. | R3.1 |
| P3 | No output file contains an email, key or DSN pattern. | R1.2 |
| P4 | Dry replay makes zero network calls. | R1.1 |
