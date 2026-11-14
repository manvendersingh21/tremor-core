# Real-dataset suite

`suite.jsonl` (300 rows, about 216 KiB) is built from public Hugging Face datasets. It is **not committed**:
the Quora pairs come through GLUE QQP, whose license is "other" (Quora terms, research use), so redistribution
is not clear. Rebuild it; the build is seeded and gives the same file each time.

| Source | Dataset | License | Rows | Type | Grader |
|---|---|---|---|---|---|
| mmlu | `cais/mmlu` (6 subjects, test) | MIT | 60 | easy | choice (letter) |
| dolly | `databricks/databricks-dolly-15k` (open_qa, general_qa, no context) | CC-BY-SA-3.0 | 60 | easy | llm (1-5 vs reference) |
| qqp | `nyu-mll/glue` qqp validation: 24 duplicate + 6 non-duplicate pairs | Quora terms ("other") | 60 | repeat | pair (cache behaviour) |
| humaneval | `openai/openai_humaneval` | MIT | 40 code + 15 hard (longest prompts) | code, hard | unit_test |
| mbpp | `google-research-datasets/mbpp` sanitized test | CC-BY-4.0 | 35 | code | unit_test |
| gsm8k | `openai/gsm8k` main test (5+ calculation steps) | MIT | 30 | hard | exact (final number) |

Skipped: `lmsys/lmsys-chat-1m` (gated), `tatsu-lab/alpaca` (CC-BY-NC), Kaggle (no credentials file; the browser route was blocked, see docs/handoff/real-datasets-suite.md).

Rebuild:

    .venv/bin/python bench/datasets/fetch.py        # caches 100-row pages under $KIROCREW_SCRATCH/hf (about 2 MB)
    .venv/bin/python bench/datasets/build_suite.py  # writes bench/datasets/suite.jsonl

`fetch.py` reads the datasets-server rows API page by page, prints the dataset size first and refuses anything over 150 MiB
as a whole download. `grade.py` runs generated code in a subprocess with a 10 s timeout, an empty environment and a
socket block (macOS `sandbox-exec` is used when it works; it did not on the build machine, so the socket block is the only network guard there).
Run the suite with `bench/run_suite.py` (see its docstring); results go to `bench/results_suite.md` and `.csv`.

## Cache eval (Quora pairs)

`build_cache_eval.py kaggle|hf` writes `cache_eval.jsonl` (1,000 queries from 500 real Quora pairs, arrival order, duplicate labels).
`kaggle` reads `bench/.scratch/kaggle/train.csv` (Kaggle 'Quora Question Pairs', competition rules, non-commercial use); `hf` uses the same
Quora data through GLUE QQP train (license "other", Quora terms). Both outputs are git-ignored, not redistributed.
Run: `.venv/bin/python bench/run_cache_eval.py sqlite pg` (pg uses `CHIMERA_DB_URL`, tenant `eval-kaggle`, purged after each config).
