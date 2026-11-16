# CI green on dev

Date 2026-11-15 (PST). Workflow: `.github/workflows/ci.yml` (pytest on Python 3.11 and 3.12, plus the image job).

## Cause

1. `tests/test_cut_count.py` and `tests/test_cut_door.py` failed at collection on GitHub, because `scripts/cut_*.py` import numpy and Pillow and the `[dev]` extra had neither.
2. After that, one test still failed: `tests/test_spec_modal.py::test_prompt_set_is_mixed_and_warmups_are_not_measured`. It reads `bench/datasets/suite.jsonl`, which is git-ignored, so the CI runner never has it.

Every dev run from 4431484 to e4e3267 failed for these reasons.

## Fix

| Commit | Change |
|---|---|
| b8e28a6 | `pyproject.toml`: `numpy` and `pillow` in the `dev` extra |
| 322f594 | `tests/test_spec_modal.py`: that one test is skipped when `bench/datasets/suite.jsonl` is missing. The offline rule applies: no live data on CI. Where the file exists (the Mac), the test still runs. `bench/datasets/README.md` builds it. |

## Runs

| Run id | Commit | Result |
|---|---|---|
| 43826653237 | e4e3267 | failure (numpy) |
| 43826912877 | b8e28a6 | failure (suite.jsonl) |
| **43827253093** | **322f594** | **success**: job 133163911144 `test (3.11)` 252 passed, 4 skipped; job 133163910749 `test (3.12)` 252 passed, 4 skipped; job 133163910968 `image` success |
| **43827495749** | **2a05f8b** (this note) | **success**: `test (3.11)`, `test (3.12)` and `image` |

Open pull requests: none. `jr/bank-terminal`, `jr/xfail-safety`, `jr/xfail-guard`, `jr/xfail-nul` and `jr/xfail-ladder` were squash-merged as PRs #1 to #5 before the fix, so no branch needed a rebase.

## Not done

- No Modal job was started. The speculative decoding comparison owns Modal until its Phase B is done.
- The spec chat's uncommitted edits to `tests/test_spec_modal.py` on the Mac were kept. The fix was made in a clean worktree, and the edits came back cleanly on pull.
