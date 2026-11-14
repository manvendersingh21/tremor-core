# Tasks: terminal agent

Status at writing: `apps/terminal/` and `tests/test_terminal.py` sit in another chat's working tree, uncommitted.

- [x] 1. REPL, flags, slash commands (R2, R3) `apps/terminal/cli.py`
- [x] 2. Edit parser, diff, apply, undo (R2) `apps/terminal/edits.py`
- [x] 3. Router wiring, cache namespace, no Mac cache (R1, R5, R6) `apps/terminal/routing.py`
- [x] 4. Repair loop with tier climb (R3) `apps/terminal/agent.py`
- [x] 5. Safety: redaction, blocked files, risk gate (R4) `apps/terminal/safety.py`
- [x] 6. Offline tests with a fake router `tests/test_terminal.py`
- [ ] 7. Commit and push `apps/terminal/` (owner: terminal chat)
- [ ] 8. Live run on `bench/terminal_tasks.py` and `bench/results_terminal_agent.md` (R7): file does not exist
- [ ] 9. Property tests P1 to P8 as `tests/test_props_terminal.py`
