# Property-based tests (Kiro correctness style)

Flow: EARS requirements (`.kiro/specs/chimera-speculative-os/requirements.md`, R1.5, R1.6, R6 to R9) -> correctness properties (`design.md`, section 5, P1 to P19) -> Hypothesis tests that try to break them and shrink the failure. Tasks 25 to 30 in `tasks.md`.

## Run
```
.venv/bin/python -m pytest -q tests/test_props_*.py          # about 4 s
.venv/bin/python -m pytest -q tests/test_props_*.py --hypothesis-show-statistics
```
`hypothesis>=6` is in the `dev` extra. Settings: `tests/_props.py` (`PBT`: 200 examples, 1 s deadline; `PBT_SLOW`: 50 examples, 5 s deadline for the chi-square test). Offline: fake embedders, fake Supabase (`FakeStore`), fake tiers, in-memory graph store.

## Properties and files
| Properties | File | Examples each |
|---|---|---|
| P1-P6 exact/semantic cache, tenants, guard (R1.1, 1.2, 1.5, 1.6) | `tests/test_props_cache.py` | up to 200 |
| P7-P9 telemetry, escalation, failed check (R6) | `tests/test_props_router.py` | up to 200 |
| P10-P11 accept rule, residual, chi-square (R3.2, 3.3) | `tests/test_props_spec.py` | 200, 200, 50 (1,500 draws each) |
| P12-P17 scrub, risk, memory, stats, held action (R7, R8, R9.1, R9.2) | `tests/test_props_safety.py` | up to 200 |
| P18 chat stream shape (R9.3) | `tests/test_props_api.py` | up to 200 |
| P19 bank serve needs passing tests | not written: no bank code exists | |

"Up to": Hypothesis stops early on duplicate or filtered inputs. Whole property suite: about 4 s. Chi-square uses a seeded rng and a critical value of 28 (df 3, p about 4e-6), so it does not flake.
The accept ratio `min(1, p/q)` and the residual are inline in `verify_tree`; P10 and P11 check them through their output (support and distribution). P10's residual test restates the arithmetic, so it guards the formula, not the code.

## Failures found (4), all kept as `xfail(strict=True)`
Strict: when the owner fixes one, the test XPASSes, fails the run, and the marker must be removed.

| # | File and property | Shrunk counterexample | Fixed |
|---|---|---|---|
| 1 | `cache/exact_cache.py` `prompt_hash`: different (namespace, prompt) pairs get different keys (R1.5) | namespace `a`, prompt `b\x00c` vs namespace `a\x00b`, prompt `c`: same key. Low risk: namespaces are tenant ids. Fix: length-prefix the namespace. | no |
| 2 | `ladder.py` `generate`: an answer whose check failed is not cached (R6.4) | `conf=0.0`, mid `ok`, `check=lambda t: False`, prompt `a#`: the top answer is never checked and is cached. The pool path (`router.py`) is correct. | no |
| 3 | `cache/guard.py` `consistent(a, a)` is true (R1.6) | `What is Python's GIL`: the entity `python's` keeps the apostrophe, the word set strips it, so the prompt rejects itself. A semantic hit on a repeated possessive prompt is dropped by the guard. | no |
| 4 | `memory/safety.py` `scrub`: no Luhn-valid card remains (R7.1) | `00000000000000` + `_` (15 zero digits, then an underscore): `\b` does not match next to `_` or a letter, so `card_4111...` stays. | no |

Not found by 200 examples each: email, API key, JWT, DB URL and spaced or dashed cards next to punctuation; idempotence of scrub; risk score range, token rule, monotonic verbs; memory refusing unverified answers; tenant-scoped purge; pool and ladder tier order; telemetry sign; stats and chat shapes.

Not covered: one-time use of the approval token (`verify_approval` is stateless, so the same token verifies again); the guard's recall; Neo4j and Postgres stores (fakes only); the bank (P19).
