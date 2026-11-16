# Handoff: correcting the "shared, slow Akash V100" story

Date: 2026-11-16. Source of truth: [`bench/results_akash_tuning.md`](../../bench/results_akash_tuning.md).

## What was wrong

Earlier reports said the Akash V100 was shared and busy, and blamed it for slow 30B calls (78 s per call, $11.02 per
1,000 calls). That was wrong. The GPU was ours, and no one else used it; the tuning check found 0 MiB in use and the
30B fully on the GPU. The box gives our container 4 CPUs, while Ollama ran the 30B with 149 threads, so it decoded
20 tokens/s instead of 98. In some runs our own jobs on the same box (other chats, the speculative-decoding verifier)
may also have queued calls or held GPU memory; the tuning report says that part is not proven.

No GPU, Modal or ssh was used for this item. No new measurement was made: every new number is copied from
`bench/results_akash_tuning.md` or derived by `bench/company_cost/report.py`.

## Numbers, before and after

| What | Before tuning | After tuning | Source |
|---|---|---|---|
| Pass, 301 cost-case tasks | 269/301 = 89% | 270/301 = 90% | `bench/results_akash_tuning.md` |
| Median s per call | 78.0 (one at a time) | 2.7 (4 at once) | same |
| p90 s per call | 127.2 | 11.2 | same |
| $ per 1,000 calls | $11.02 (at $0.50/hr) | $0.18 at $0.52/hr, $0.52 at $1.53/hr (box kept busy) | same |
| Decode tokens/s per call | 20 (default threads) | 98 (`num_thread = 4`) | same |
| Company cost: V100 $ per 1k, full | $11.02 row | $0.178 ($0.52/hr), $0.522 ($1.53/hr); 50% busy $0.355 / $1.045; 10% busy $1.775 / $5.223 | `bench/results_company_cost.md` |
| V100 calls a day at 100% busy | not stated | 70,307 (301 calls in 369.9 s) | same |
| V100 break-even vs GPT-5.5 | not stated | 4.4% busy, about 3,104 calls a day ($0.52/hr); 13%, about 9,134 ($1.53/hr) | same |
| V100 break-even vs 763B | not stated | never (would need 113% or 331% busy) | same |
| H200 busy share to beat a full tuned V100 | not stated | 39% ($0.52/hr), 13% ($1.53/hr) at 64 at once | same |
| V100s vs H200s (h = 0, failures to GPT-5.5) | not stated | V100s cheaper up to about 280,000 calls a day ($0.52/hr) or 70,000 ($1.53/hr) | same |
| Monthly, 100k / 1M / 10M calls a day, h = 0, 30B on V100s + GPT-5.5, $0.52/hr | not stated | $3,083 (74% saved) / $30,227 (75%) / $300,174 (75%); 3 / 29 / 285 V100s | same |
| Same at $1.53/hr | not stated | $5,264 (56%) / $51,316 (57%) / $507,426 (58%) | same |
| Same, failures to the 763B, $0.52/hr | not stated | $1,218 (-$746) / $11,585 (-$6,857) / $113,757 (-$66,477) | same |
| h = 30%, V100s + GPT-5.5, $0.52/hr | not stated | $2,128 (82%) / $21,054 (83%) / $210,317 (83%) | same |
| H200 rows (break-even 44% / 1.7%, monthly $5,159 / $25,216 / $229,058) | unchanged | unchanged | same |

The V100's failure mix (2 trivial, 12 everyday, 17 hard) prices escalation at $6.26 (GPT-5.5) and $0.227 (763B) per
1,000 failed calls, against $6.04 and $0.221 for the H200's mix.

## Files changed

Step 1, commit 18474fd: dated correction note under the title, old tables kept.

- `bench/akash_correction_note.md` (new: the note text, read by the generators below)
- `bench/results_cost_case.md`, `bench/results_cost_case_h200.md`, `bench/results_suite.md`,
  `bench/results_terminal_agent.md`, `bench/results_ladder.md`, `bench/results_backend.md`,
  `bench/results_backend_verdict.md`, `bench/results_replay.md`, `bench/results_memory.md`, `bench/results_backend_v2.md`
- Generators keep the note on a rerun: `bench/cost_case/report.py`, `bench/run_suite.py`, `bench/memory/report.py`

Step 2, commit 62d7426: company cost recomputed by the script.

- `bench/company_cost/report.py`: tuned V100 inputs (`V100_HOURS`, `V100_CAP`, `V100_FULL`, `FAILS_V100`),
  `box_month()` shared by H200 and V100, `v100_monthly()`, V100 rows in the per-1k table, a wider break-even table,
  V100 projection tables for h = 0 and h = 30%, the crossover line. The old $11.02 row is labelled before tuning.
- `bench/company_cost/verdict.md`: new bullet on the tuned V100, a correction bullet, "shared V100" wording fixed.
- `bench/results_company_cost.md`: regenerated.
- `tests/test_company_cost.py`: `test_tuned_v100_price_and_cascade`.

Step 3, commit 93d4310: docs, steering, PRD package.

- `README.md`: new section "Self-hosted 30B after tuning"; ladder loss line labelled before tuning.
- `docs/PRD_chimera.md`: problem statement, tier 3b, results rows (v1/v2 ladder labelled, cost case before tuning,
  new tuned V100 row), single-run caveat, cost model (V100 paragraph and monthly table), plain-words bullet, risks 2 and 9,
  roadmap 1 and 8.
- `docs/PRD_chimera.pdf`, `docs/prd/cost_per_1k.png`, `docs/prd/monthly_cost.png`: rebuilt
  (`scripts/prd_charts.py`, `scripts/prd_pdf.py`).
- `docs/chimera_tracker.xlsx` from `scripts/prd_xlsx.py`: Costs sheet has a tuned V100 row and a before-tuning row
  (break-even formulas now point at B9 and B11). New sheet "Tuned V100" with live formulas.
  `tests/test_prd_docs.py` checks for the new sheet.
- `docs/hackathon/blog_post.md` (new paragraph "My own old GPU was fine all along", ladder time line),
  `docs/hackathon/submission.md` (pitch sentence, results row), `docs/hackathon/demo_script.md` (shot 6 line and its check row).
- `docs/status_2026-11-15.md` (note at top, two rows), `docs/spec_architecture.md` (one row),
  `docs/handoff/replay.md`, `docs/handoff/real-datasets-suite.md` (one line each).
- `.kiro/steering/tech.md` (tier 1 row), `.kiro/steering/product.md` (new results row, "What failed" line),
  `.kiro/specs/chimera-speculative-os/tasks.md` (task 9a text).

Step 4, commit f973ff0, and step 5 (this note): site.

- `site/rooms.js`: "The Manor's box" says the box is ours and the 30B was thread-bound; "Ladder is slower" labelled before tuning.
- `site/results.py`: new `akash_tuning` report (pass, p50 tuned and before, $ per 1k), headlines `v100_tuned_per_1k`
  and `v100_tuned_p50_s`; the cost-case V100 labels say before tuning. `tests/test_site_results.py` expects 13 reports.
- `site/demo.py`: the Manor tour stop quotes the tuned V100 price next to the before-tuning one.
- `site/dashboard/halloween.html`: the 30B line shows the tuned price and the before-tuning price.
- `site/index.html` (Tier I rung text, plus the generated part), `site/results.json`, `site/demo.json`,
  `site/docs/tour_script.md`: rebuilt by `python3 site/build.py`; `--check` passes.
- `site/docs/ui_results_rooms.md`: one row.
- `docs/handoff/akash-correction.md`: this file.

## Checks run

- `pytest tests/test_company_cost.py tests/test_prd_docs.py tests/test_site_demo.py tests/test_site_results.py
  tests/test_castle.py tests/test_world.py tests/test_hud.py tests/test_memory_report.py tests/test_suite_cache_stats.py`: pass.
- `python3 site/build.py --check`: pass.
- `.kiro/hooks/scripts/secret_scan.py --staged` before every commit: clean.

## Not done, and risks

- Not rerun: the 60-question ladder, suite, replay, terminal agent and memory runs. Their latency stays as measured
  before tuning, labelled so.
- `bench/run_ladder.py` and `bench/run_terminal_agent.py` still write the "shared" text on a rerun. Both had
  uncommitted edits from another chat, so they were left alone; the note is in their result files only.
- `bench/memory/run_memory.py` and `bench/cost_case/run_router.py` still say "shared" in code comments.
- The castle's per-1k table (`site/game/panels.js`, from `demo.json`) now lists 6 tuned V100 rows; the UI owner may want fewer.
- Demo shot 6 gained one sentence (about 5 s) inside a 25 s slot.
- Pre-existing, not touched: some committed files still name local tunnel ports (`bench/results_gpu.md`,
  `bench/results_ladder.md`, `bench/run_bench_gpu.py`, `bench/run_spec.py`, `chimera.example.toml`). The secret scan has
  no port rule, so it does not catch them.
