# Audit: secrets, links, README figures (k2, no GPU, no network)

Run on a fresh clone of dev. The scan uses the rules of `.kiro/hooks/scripts/secret_scan.py`. No values are printed anywhere.

## Secret scan, current tree: 6 hits, all false positives

| File | Rule | What it is |
|---|---|---|
| `tests/test_bank.py:69` | api key or token | made-up `sk-abc...` string, test fixture for the scrubber |
| `tests/test_service.py:137` | api key or token | `sk-test-...` fixture |
| `tests/test_service.py:138`, `tests/test_no_local_cache.py:16` | dsn with password | fake DSN set by `monkeypatch.setenv` |
| `tests/test_skeleton_coder.py:35` | key path | fake path string in the "refuse key files" test |
| `skeleton/core/assistant.py:147` | secret assignment | keyword arguments (`tokens_saved=...`), not a secret |

No real credential is in the tree.

## Secret scan, all history, all refs: 14 (file, rule) pairs

All are "key path" or "ssh target host" in early benchmark files and notes, or the test fixtures above:

- `bench/results_gpu.md` (088cd85), `bench/run_bench_gpu.py` (6177579), `bench/run_ladder.py` (65f5a53), `docs/handoff/real-datasets-suite.md` (299e136): an SSH tunnel command with a key file path and a private box address. The current tree no longer has them.
- test fixtures: `tests/test_bank.py`, `tests/test_service.py`, `tests/test_no_local_cache.py`, `tests/test_skeleton_coder.py`.
- `docs/handoff/k1_k2_apps.md` (7d4ebdc): example key file names in prose, already reworded.

Real exposure: only the old private box address and key file path in those four commits. No key contents were found. Removing them from history needs a history rewrite on a private repo. That is a destructive, shared-branch action, so it is left to the owner. If the box address matters, rotate or ignore it instead.

## Links

121 markdown files checked for relative links: 0 broken. External links were not fetched (no network).

## README figures against results files

Every `%` and `$` figure in `README.md` (36), `skeleton/README.md` (9), the coder README (4), the help desk README (4) and the store README (1) appears verbatim in a `bench/results*.md`, `skeleton/RESULTS.md` or `docs/vector-store.md` file. This is a text match only: it proves the figure exists in a results file, not that it sits next to the right label.

## Not checked

External URLs, figures that are not `%` or `$` (counts, milliseconds, token totals), and whether a matched figure belongs to the same claim.
