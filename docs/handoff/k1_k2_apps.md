# k1 / k2 test and polish pass: coder and help desk

No GPU used. Crusoe 763B and offline tests only. The Crusoe key stayed on the Mac; the boxes got no model keys, so their runs are offline.

## What each box did

| Box | Branch | Job | Result |
|---|---|---|---|
| k1 (4 CPU) | `k1-coder` | fresh clone of dev, venv, `make test`, coder demo and class, probe of nearby inputs, path traps | 1 fix, PR #6 |
| k2 (2 CPU) | `k2-helpdesk` | same for help desk and core, 11 nearby question pairs, 8 bad inputs | nothing broken, no PR |

PR: https://github.com/manvendersingh21/tremor-core/pull/6 (`coder: clear message when every tier fails`).

## Fixed

Coder CLI: when every tier fails, `ask` printed a traceback. Now one line on stderr, exit code 2. One test in `tests/test_skeleton_coder_cli.py`. (A new file, because the secret scan flags the old `tests/test_skeleton_coder.py` line 35, a fake key-path string in a refusal test.)

## `make test` on a fresh clone

- First clone of dev 8de4f2c: 1 failure, `tests/test_site_demo.py::test_demo_json_is_up_to_date` (stale `site/demo.json`). Not in the apps. Dev 332c185 regenerated it.
- After rebase on dev with the fix: 360 passed, 5 skipped.
- Python on both boxes is 3.14.4.

## Nearby inputs tested (offline, stub models)

Help desk (k2):
- Same intent: trailing "?" removed, mixed case and extra "???". Served from cache. OK.
- Different intent: "not reset", "reset my email", "refund in 5 days", "cancel my subscription", "undo cancelling", "order 12345", "weekend hours", "hours in 2030". No wrong hit. Two seeded questions got exact hits of their own seed answers, which is right.
- Bad input: empty, spaces, `None`, number (400), 501 characters (413), script tag, bidi character, NUL byte (200, no crash).

Coder (k1):
- Same task twice: second answer from cache, tests re-run, passed.
- Same task on changed files (other bug, already fixed, trailing space): never a cached failing patch. Failing patches were not served.
- Test that no patch can pass: repeat is not a verified cache hit.
- Refused paths: `../evil.py`, `/etc/passwd`, `.env`, `.ENV`, `sub/.env`, other key files, `.git/config`, `a/../../x.py`. All refused. `~/x` is a plain file name inside the repo (no tilde expansion), so it is allowed, correctly.
- Reworded tasks with no stub answer raise `AllTiersFailed` in demo mode. That is the bug fixed above.

## Crusoe-only smoke (run on the Mac, `--no-gpu`, Supabase cache)

| App | Asks | Hits | Wrong cache answers | Tokens | $ |
|---|---|---|---|---|---|
| Help desk, 10 questions asked twice | 20 | first pass 8 (earlier runs warmed them), repeat 8 of 10 | 0 | 4,503 | 0.001426 |
| Coder class, 6 students | 15 | 15 of 15 | 0 | 0 (all cached) | 0 |

Help desk repeat median hit: 102 ms. Two repeats were not cache hits: an answer that fails the grounding check (or quotes the support phone number) is never cached, by design. "Wrong" means a cached answer that differs from the first answer or fails the grounding check.

## Left

- k2 found nothing to change, so there is no `k2-helpdesk` PR.
- Coder class run was all warm cache from earlier runs, so it shows the hit path, not a first-model-call path.
- The live Crusoe path of `coder ask --live` was not run (needs a real repo task; only the class run was).
- Python 3.11 and 3.12 (CI) were not run on the boxes.

## Round 2 (extra jobs)

| Job | Box | Result |
|---|---|---|
| Fresh-clone full suite on Python 3.11 and 3.12 | k1 | 365 tests each, 0 failed, 5 skipped. Installed with `uv` (not on the boxes; put in a venv). |
| Hypothesis tests for skeleton core and coder | k1 | PR #8. Found a real gap: the coder path guard allowed a file inside a directory named `.env` (`.env/a`). Fixed, and kept as a property test. |
| Secret scan (tree and all history), link check, README figure match | k2 | PR #7, `docs/audits/k2_audit.md`. No real credential. The old private box address and a key file path sit in 4 early commits; removing them needs a history rewrite, which is the owner's call. 0 broken links. |
| Store `--no-gpu` flag | k2 | PR #9. The store was the one app without it. |
| Crusoe-only smoke, store, 10 questions twice | Mac | 9 of 10 repeats from the cache, 0 wrong cache answers, 2 answers failed the grounding check (served marked unverified, never cached), 11,365 tokens, $0.003457, median hit 112 ms. |
| Crusoe-only smoke, help desk | Mac | see above (20 asks, 0 wrong). |

The Crusoe key stayed on the Mac, so smoke runs ran there, not on the boxes. `site/demo.json` counts the files in `docs/handoff/`; adding a handoff note needs `python3 site/build.py` or CI goes red.
