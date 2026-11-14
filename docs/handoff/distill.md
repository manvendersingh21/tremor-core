# Handoff: N+1 training (LoRA distillation)

Report: `bench/results_distill.md`. Code: `bench/distill/build_data.py`, `bench/distill/grade_gen.py`, `deploy/modal/distill.py`, test `tests/test_distill_data.py`.

**Result:** LoRA on 2,516 verified 763B pairs lowered held-out pass@1 from 92.2% to 88.3% on 566 problems. Do not ship the adapter.

**Router needs:** none. Nothing in the router core, `site/` or the HUD was changed.

**Shared file touched:** `bench/evallog.py` gained one path in `SUITE_LOGS` (`bench/.scratch/distill/eval_log.jsonl`) so the Evals tab shows the distill rows.

**Left in place (not secrets):** Modal volume `chimera-distill` holds the base checkpoint (about 61 GB), the adapter and the merged weights. Delete it with `modal volume delete chimera-distill` if the space matters.

**Open:** the retrieval-memory result was not available to compare. The solve step skipped about 1,488 problems on API errors; `build_data.py solve` resumes them.
