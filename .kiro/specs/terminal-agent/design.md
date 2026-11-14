# Design: terminal agent

## Turn
```
request -> prompt (edit rules + repo map <= 500 chars + redacted context files + last test failure)
        -> router.generate(): Supabase cache -> 30B -> 763B
        -> parse edit blocks -> diff -> confirm -> write
        -> run tests -> fail: send output back (<= 3), next tier up
```

## Components
| Part | File |
|---|---|
| REPL, flags, slash commands | `apps/terminal/cli.py`, `__main__.py` |
| Turn loop, prompt, repair | `apps/terminal/agent.py` |
| Edit parser and writer, undo | `apps/terminal/edits.py` |
| Tier choice and cache namespace | `apps/terminal/routing.py` |
| Redaction, blocked files, risk gate | `apps/terminal/safety.py`, `packages/chimera-core/firewall/risk_scorer.py` |

## Decisions
- Stdlib only, no TUI library, so it runs from the repo venv.
- The repair loop climbs one tier per failed round, so cheap fixes stay on the 30B.
- Safety lives in one module and runs before any shell or write, not inside the model prompt.

## Correctness properties
Router and firewall properties are owned by `.kiro/specs/chimera-speculative-os/`; these are the agent's own.

| ID | Property | Requirement |
|---|---|---|
| P1 | For any edit text, parse, apply, then `/undo` returns the original bytes. | R2.3 |
| P2 | A path under `.ssh`, `.aws`, `.gnupg` or named `.env`, `*.pem`, `*.key` is always refused. | R4.3 |
| P3 | `redact(redact(x)) == redact(x)` and no `sk-`, `ghp_` or DSN password survives. | R4.4 |
| P4 | A write whose resolved path is outside the working directory scores >= 70. | R4.2 |
| P5 | The child environment never contains a name matching KEY, TOKEN, SECRET or PASSWORD. | R4.5 |
| P6 | With a fake router, repair rounds never exceed `max_repairs`. | R3.2 |
| P7 | Changing a context file's text changes the cache namespace. | R5 |
| P8 | The tier index of round n+1 is >= round n in `auto`. | R3.3 |

Tests: `tests/test_terminal.py` (fake router, no models).
