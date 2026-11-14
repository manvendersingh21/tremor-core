# Handoff: real-dataset suite and cache eval

## Done
- `bench/datasets/{fetch,build_suite,grade}.py`, `suite.jsonl` (300 rows, git-ignored: Quora terms), README with sources and licenses.
- `bench/run_suite.py` (TOP | POOL | report). TOP run finished: 300/300.
- `bench/datasets/build_cache_eval.py`, `bench/run_cache_eval.py`, `bench/cache_eval_report.py` (section "Token savings: what this means for users", appended by `run_suite.py report`).
- SQLite cache eval ran, 1,000 queries, Quora pairs from GLUE QQP train: 181 possible repeats. Hits/false hits: no guard 0.94 = 58/10, 0.97 = 31/4; guard 0.94 = 44/4, 0.97 = 24/1.
- Commit: see `git log -1 -- bench/run_cache_eval.py`.

## Half done
- POOL run: 116/300 rows in `bench/.scratch/suite_POOL.jsonl` (killed on handoff; git-ignored). Resume skips finished ids.
- Pg cache eval: first config matched SQLite exactly (58/48/10); the other three were stopped. Tenant `eval-kaggle` was purged. `bench/results_cache_eval.json` is not written yet (it needs all configs).
- Kaggle download: not done. The browser tool said Chrome refuses debugging; the user must turn on "Allow remote debugging" at chrome://inspect/#remote-debugging. Then put `train.csv` in `bench/.scratch/kaggle/`, unzip, delete the zip, run `build_cache_eval.py kaggle`. No API token. If a rules page appears, use the browser `ask` op.
- `bench/results_suite.md/.csv` do not exist yet.

## Resume
    export KIROCREW_SCRATCH=$PWD/bench/.scratch
    curl -s -m 3 127.0.0.1:8080/health || bash bench/serve_local.sh
    ssh -N -f -L 127.0.0.1:<port>:127.0.0.1:11434 <gpu-host>   # an SSH tunnel to your GPU box
    .venv/bin/python -u bench/run_suite.py POOL        # about 1-2 h on the shared Mac 3B
    .venv/bin/python bench/run_cache_eval.py sqlite pg  # about 20 min for pg
    .venv/bin/python bench/run_suite.py report          # writes results_suite.md/.csv
The TOP tokenizer file `bench/.scratch/tok_DeepSeek-V4.1-Flash.json` is from huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash (re-download if missing).
Crusoe tokens so far: TOP run only (see `per_tier` sums in `suite_TOP.jsonl`); judge not run.

- 2026-11-13: the Mac 3B was stopped by the user. POOL is now cache -> gpu-small (30B) -> 763B. The 116 POOL rows already in bench/.scratch were made with the 3B tier first, so delete bench/.scratch/suite_POOL.jsonl before a rerun.
