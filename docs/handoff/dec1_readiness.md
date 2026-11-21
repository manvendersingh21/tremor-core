# Dec-1 readiness

**Written:** 2026-11-20. **Updated by:** this worker session (no GPU; Crusoe + offline only).  
**GPU budget resets:** Dec 1 with ~$90 of credits.  
**Submission deadline:** Dec 4, 2026, 2:00 PM PT.

---

## 1. One-command Dec-1 runner

### Files

| File | Purpose |
|---|---|
| `deploy/dec1/run_all.sh` | Shell runner: detects GPU, skips missing tiers cleanly |
| `deploy/dec1/run_all.py` | Python driver: `dry_run`, `smoke`, `status`, full run |

### Usage on Dec 1

```bash
# 1. Set up the GPU box and wire CHIMERA_120B_URL + CHIMERA_120B_KEY into .env
# 2. Set A6000_ROOT to the run folder on the box
# 3. One command:
.venv/bin/python deploy/dec1/run_all.py

# Or the shell script directly:
bash deploy/dec1/run_all.sh
```

Environment variables read from `.env` (never printed or committed):
- `CRUSOE_API_KEY` — required; Crusoe DeepSeek-V4.1-Flash 763B
- `CHIMERA_DB_URL` — required; Supabase cache + bank
- `CHIMERA_120B_URL` — optional; vLLM gpt-oss-120b endpoint; skipped if absent
- `CHIMERA_120B_KEY` — optional; bearer token for the 120B
- `A6000_ROOT` — optional; path on the GPU box for the watchdog

No GPU or missing 120B: the script detects the absence and no-ops those steps cleanly.  
Resumable: each step appends one row per item to `bench/.scratch/dec1/`; a rerun skips done rows.

### Steps the runner runs (in order)

1. Start the A6000 watchdog (if A6000_ROOT set): yields both GPUs within ~10 s if anyone else touches either.
2. Start gpt-oss-120b vLLM (if CHIMERA_120B_URL set): via `deploy/gpu120b/serve_vllm.sh`.
3. **Cost-case 301 tasks on 763B** (`bench/cost_case/run_tiers.py top`).
4. **Cost-case 301 tasks on 120B** (`bench/cost_case/run_120b.py`) — skipped if no 120B.
5. **40 moderately-hard questions on 763B** (`bench/run_hard_live.py run TOP`).
6. **Same-box speculative on 120B** (`bench/a6000/spec_job.sh`) — skipped if no 120B or A6000_ROOT.
7. Cost-case report (`bench/cost_case/report.py`).
8. Shut down 120B, send watchdog stop.

### Dry-run result (2026-11-20, no GPU, Crusoe only)

Ran `DRY_RUN=1 bash deploy/dec1/run_all.sh` (or `.venv/bin/python deploy/dec1/run_all.py dry_run`).

```
=== Dec-1 runner started 2026-11-20T23:21:14-08:00 ===
GPU: none detected, running Crusoe + cache only
CRUSOE_API_KEY: set (82 chars)
CHIMERA_DB_URL: set
120B tier: CHIMERA_120B_URL not set, skipping
watchdog: skipped (no GPU or A6000_ROOT not set)
120B vLLM: skipped
[DRY_RUN] .venv/bin/python bench/cost_case/run_tiers.py top
[DRY_RUN] (120B cost-case skipped)
[DRY_RUN] .venv/bin/python bench/run_hard_live.py run TOP
[DRY_RUN] (same-box speculative skipped)
[DRY_RUN] .venv/bin/python bench/cost_case/report.py
=== Dec-1 runner finished 2026-11-20T23:21:14-08:00 ===
```

Exit code: 0. No crash, no credential printed.

### Smoke test (2026-11-20, live Crusoe + live Supabase)

Ran `.venv/bin/python deploy/dec1/run_all.py smoke`.

```
Crusoe smoke:   468 ms  reply='dec1-smoke-ok'    ← Crusoe 763B is live
Supabase smoke: 514 ms  hit=False                ← Supabase pgvector is live
```

Result in `bench/.scratch/dec1/smoke.json`. Both services confirmed reachable.

---

## 2. $90 budget plan

GPU budget resets Dec 1. List price: Crusoe 763B $0.29/M in, $1.20/M out.  
A6000 box: owned hardware at $0 per call; Daytona is gone; Modal is gone.

Order: **cheapest tests with the highest submission value first.**  
Run order and rough cost based on earlier measured token counts.

| Priority | Test | GPU needed | Approx cost | Hours | Value |
|---|---|---|---|---|---|
| 1 | Cost-case 301 tasks × 1 rep on 763B alone (`run_tiers.py top`) | None (Crusoe only) | ~$0.05 | 0.5 h | Baseline for all saving claims |
| 2 | 40 hard questions × 3 reps on 763B alone (`run_hard_live.py run TOP`) | None | ~$0.04 | 0.5 h | Ladder vs 763B baseline |
| 3 | Cache cold/warm full run on 301 tasks + 40 hard (ladder, A6000 30B) | A6000 (owned) | $0 GPU + ~$0.10 Crusoe | 2 h | Shows 70%+ 763B-call cut |
| 4 | 120B tier: gpt-oss-120b on 1 × H100 or H200, 60 cost-case tasks | H100 $2.47/h on Daytona, or bring own box | ~$0.08 + ~$3 GPU | 1.5 h | 4-tier ladder proof |
| 5 | 120B cost-case full 301 tasks (`run_120b.py gen 4`) | 1 × H100 / H200 | ~$0.26 + ~$10 GPU | 4 h | Full 4-tier comparison |
| 6 | Same-box speculative on 120B with EAGLE-3 (`bench/a6000/spec_job.sh`) | H100 or H200 (H100 compute cap 9+ required) | ~$10–20 GPU | 4–8 h | Spec speedup claim |
| 7 | Repeat all A6000 runs with fresh credentials after yield proof | A6000 (owned) | $0 | 4 h | Repeats for submission table |

**At $90 total:**  
- Items 1–3: ~$0.20 total. Do these first; they prove the main claim with owned hardware.
- Item 4 (120B sample): ~$3–4. Good second. Proves the 4-tier ladder exists.
- Item 5 (120B full): ~$10–11. Run if time allows; skip if the sample is clean.
- Item 6 (same-box spec): ~$10–20. Nice to have; spec result already measured in `results_spec_modal.md`.
- **Budget leftover for reruns and mistakes:** ~$55–70.

**Cut if running short:**
- Skip item 6 (spec). The existing Modal measurement is sufficient for the submission.
- Shrink item 5 to 60 items if needed.
- Items 1–3 are the minimum needed to publish a final `bench/results_a6000.md` row for Dec 4.

---

## 3. Live re-test results (2026-11-20)

No GPU available today. Tested what runs on Crusoe + Supabase + offline.

### 3a. Offline pytest

```
make test  →  365 passed, 1 deselected in 35.19 s
```

All offline tests pass on the current working tree (Python 3.14, venv).

### 3b. Skeleton apps (offline / demo mode)

```
pytest tests/test_skeleton_core.py tests/test_skeleton_coder.py \
       tests/test_skeleton_helpdesk.py tests/test_skeleton_store.py \
       tests/test_skeleton_bench.py

→  35 passed in 2.34 s
```

All three skeleton apps pass their offline tests.  
Demo mode (`Config(demo=True)`) returns `{'answer': ..., 'tier': ..., 'tokens': ..., ...}` — API shape confirmed.

### 3c. Cache cold/warm (live Supabase)

```
COLD: 187 ms  hit=False   ← miss on a fresh tenant, as expected
WARM: 169 ms  hit=True    response='Paris'  ← exact hit, correct
```

0 wrong answers. Supabase pgvector round-trip ~185 ms median.

### 3d. Crusoe 763B (live)

```
reply='OK'   tokens in/out: 9 / 2   latency: ~470 ms
```

Crusoe is live. TopBackend resolves the key from env, never prints it.

### 3e. Router + cache + memory offline tests

```
pytest tests/test_memory.py tests/test_pgvector_cache.py tests/test_router.py
→  28 passed, 1 deselected in 0.47 s
```

### 3f. GPU-only checks (deferred to Dec 1)

The following need the A6000 30B and are deferred:
- Full POOL run (cache → 30B → 763B) on 301 cost-case tasks
- Full POOL run on the 300-question suite
- Bank fill + run2 + run3
- `run_hard_live.py run PLAIN POOL WARM` (the PLAIN and POOL steps need the 30B)
- Terminal coder with live 30B
- `chimera code` live smoke

Last known results for these: `bench/results_a6000.md` (2026-11-17, A6000 GPU 1, 8 runs, CI green).

---

## 4. Kiroween submission final-check

**Checked 2026-11-20.**

| # | Check | Status | Notes / Fix |
|---|---|---|---|
| S1 | Repo public + MIT license visible | **PASS** | `LICENSE` at root, MIT; GitHub shows "MIT License" |
| S2 | `/.kiro` at root and NOT gitignored | **PASS** | `git ls-files .kiro` → 45 files; `git check-ignore .kiro` → not ignored |
| S3 | `/.kiro/settings/mcp.json` committed | **PASS** | listed by `git ls-files .kiro/settings/` |
| S4 | Working app URL loads | **PARTIAL** | Pages static view at [manvendersingh21.github.io/tremor-core](https://manvendersingh21.github.io/tremor-core/) returns 200. Live `make web` runs at `127.0.0.1:8765`. Pages is demo mode; full castle needs local server. **User action**: decide whether to host a live demo or accept the Pages static view. |
| S5 | Demo video exists and ≤ 3:00 | **PASS** | `site/docs/demo_v3.mp4` exists (57 MB, **145 s = 2:25**); within the 3-minute limit |
| S6 | Demo video uploaded to YouTube as Public | **NEEDS USER** | File is local. User must upload and confirm Public (not Unlisted). |
| S7 | Devpost text complete and honest | **PASS** | `docs/hackathon/submission.md` — pitch, results table with losses, Kiro section, all numbers source-cited |
| S8 | Kiro write-up present | **PASS** | Same file; covers Kiro Crew, CLI, IDE, 7 steering files, 7 specs, 6 hooks, 4 agents, MCP, Power |
| S9 | Category chosen | **PASS** | Frankenstein (second: Costume Contest) in `docs/hackathon/submission.md` |
| S10 | Skeleton Crew: two named apps + bonus | **PASS** | Coder (`skeleton/apps/coder`) + Helpdesk (`skeleton/apps/helpdesk`) as submitted; Store (`skeleton/apps/store`) as bonus. `skeleton/README.md` names the two. |
| S11 | All results files present | **PASS** | `bench/results_a6000.md`, `_akash_tuning.md`, `_backend_v2.md`, `_backend_v3.md`, `_bank.md`, `_company_cost.md`, `_distill.md`, `_hard_live.md`, `_memory.md`, `_replay.md`, `_spec_modal.md`, `_terminal_agent.md` — all exist |
| S12 | Numbers consistent: README ↔ PRD ↔ site ↔ hackathon docs | **PASS** | Key claims cross-checked: "70.7% cut", "0 wrong cache answers", "2:25 video" consistent across `README.md`, `docs/hackathon/submission.md`, `bench/results_a6000.md` |
| S13 | spec tasks.md boxes ticked for built specs | **FIXED** | `savings-replay/tasks.md` and `lora-distill/tasks.md` had all boxes unchecked; ticked this run to match the built and measured state. |
| S14 | CI green on Python 3.11 and 3.12 | **PASS** | Last commit `732b8d1` passed CI. Local `make test` → 365 passed. |
| S15 | Secret scan clean (tree + staged) | **PASS** | `.kiro/hooks/scripts/secret_scan.py --all` → `clean` |
| S16 | No SSH hostnames / IPs / tunnel ports in committed files | **PASS** | Secret scan clean; docs say "an SSH tunnel to your GPU box", not any host |
| S17 | Devpost form filled | **NEEDS USER** | Paste from `docs/hackathon/submission.md`. Add repo URL, app URL, YouTube URL. Pick Frankenstein. Tick Best Kiro Crew App and Best Demo. |
| S18 | Blog post published | **NEEDS USER** | Draft in `docs/hackathon/blog_post.md`. Must be posted on a third-party site with "Kiroween 2026" in the text. |
| S19 | Social post published | **NEEDS USER** | Draft in `docs/hackathon/social_post.md`. Must start with `#KiroweenHackathon26`. |
| S20 | Kiro handle `@kirodotdev` confirmed | **NEEDS USER** | In `docs/hackathon/social_post.md`. Confirm or update. |
| S21 | `bench/results_suite.md` exists | **NOTE** | File does not exist as a named file; suite results live in `results_a6000.md` and `results_backend_v2.md`. No reference in submission.md points to `results_suite.md`. No fix needed. |

### Summary of FAIL / NEEDS USER items

| Item | Who | Action |
|---|---|---|
| S4 app URL | User | Decide: Pages static (OK for demo mode) or host a live demo |
| S6 video upload | User | Upload `site/docs/demo_v3.mp4` to YouTube as Public; aim for Dec 3 |
| S17 Devpost form | User | Fill and submit before Dec 4 2:00 PM PT |
| S18 blog post | User | Publish draft from `docs/hackathon/blog_post.md` |
| S19 social post | User | Post from `docs/hackathon/social_post.md` |
| S20 Kiro handle | User | Confirm `@kirodotdev` or update social_post.md |

No FAIL items require a code change. All technical checks pass.

---

## Exact Dec-1 commands

```bash
# Check everything is set before you start:
.venv/bin/python deploy/dec1/run_all.py smoke

# Optional: check status of previous rows
.venv/bin/python deploy/dec1/run_all.py status

# When the GPU box + credits are ready:
# 1. Set A6000_ROOT in .env (or export it)
# 2. If running 120B: set CHIMERA_120B_URL and CHIMERA_120B_KEY in .env
# 3. Run:
.venv/bin/python deploy/dec1/run_all.py

# Or the shell script:
bash deploy/dec1/run_all.sh

# Output is in bench/.scratch/dec1/  (git-ignored, resumable)
# Logs:   bench/.scratch/dec1/run_all.log
```

The runner no-ops cleanly if no GPU is detected or if `CHIMERA_120B_URL` is absent.
