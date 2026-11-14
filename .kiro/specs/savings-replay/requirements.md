# Requirements: savings replay

**Status: planned. No code exists in the tree.** The user paused it for Mac memory. This spec records the intent so the work starts from a written bar. Inputs that exist: telemetry JSONL (`inference/telemetry.py`), the cost case (`bench/cost_case/`), the real-dataset suite (`bench/run_suite.py`).

Intent: replay logged prompts through the ladder and through the top model alone, then report tokens and dollars saved with losses shown.

## Requirements

### R1 Replay input
1. THE replay SHALL read prompts from a telemetry JSONL or a suite file and SHALL NOT need keys for a dry run with recorded answers.
2. THE replay SHALL scrub prompts with `memory/safety.py` before writing any result.

### R2 Two arms
1. THE replay SHALL run each prompt through the ladder and through the 763B alone, with the same grader.
2. THE report SHALL list tokens, dollars, median and p90 latency and pass rate per arm.

### R3 Honest report
1. THE report SHALL name every prompt where the ladder cost more or failed a check the top model passed.
2. THE report SHALL write `bench/results_replay.md` with the setup and a verdict that names failures.

### R4 Cost control
1. LIVE replay SHALL use cheap models first and SHALL cap calls to the 763B by a flag.
2. HEAVY jobs SHALL run on the Akash box, not the Mac.
