# Requirements: terminal agent (`chimera code`)

Scope: `apps/terminal/`, an Aider-style coding agent in the terminal. Doc: `apps/terminal/README.md`. Tests: `tests/test_terminal.py`. Bench: `bench/run_terminal_agent.py`, `bench/terminal_tasks.py`.

## Requirements

### R1 Every model call goes through the router
1. THE agent SHALL call models only through `SpeculativeCascadeRouter.generate()`.
2. EVERY call SHALL write the normal telemetry row, so sessions appear in the Observatory.

### R2 Edits are shown and confirmed
1. THE agent SHALL parse SEARCH/REPLACE and `FILE: ... END FILE` blocks and show a diff.
2. WHEN `--yes` is not set, THE agent SHALL apply an edit only after the user answers yes or always.
3. `/undo` SHALL restore the previous file text and remove files the agent created.

### R3 Test, repair, climb
1. AFTER an edit THE agent SHALL run the test command (default `pytest -q` when tests exist).
2. IF the tests fail, THEN THE agent SHALL send the output back, at most `--max-repairs` (3) times.
3. IN tier `auto`, EACH failed round SHALL start the next call one tier up (30B, then 763B).
4. `-m` mode SHALL exit 1 when tests still fail.

### R4 Safety
1. EVERY shell command and file write SHALL be risk-scored. A score >= 70 SHALL need the one-time token, even with `--yes`.
2. A write outside the working directory SHALL score at least 70.
3. THE agent SHALL NOT read or write `.env`, `id_rsa*`, `*.pem`, `*.key`, `credentials*` or anything under `.ssh`, `.aws`, `.gnupg`. `.env.example` is allowed.
4. TEXT sent to a model SHALL be redacted (keys, tokens, DSN passwords, secret env values).
5. CHILD processes SHALL run without `*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*` variables.
6. `/commit` SHALL never push.

### R5 Cache correctness
1. THE cache namespace SHALL include a hash of each context file's path and content, so changed file text never gets a stale cached answer.

### R6 No Mac answer cache
1. THE agent SHALL replace the router's SQLite caches with a no-op.

### R7 Honest results
1. `/cost` SHALL show per-tier totals and dollars saved against an all-763B baseline. Live results go to `bench/results_terminal_agent.md` with failures named (file does not exist yet).
