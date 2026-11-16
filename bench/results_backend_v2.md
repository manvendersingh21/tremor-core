# Backend v2: GPU link self-heal, H200 30B tier, bank in `chimera code`, xfail fixes, live checks

> **Correction, 2026-11-16 ([`results_akash_tuning.md`](results_akash_tuning.md)).** Earlier reports, this one included, said the Akash V100 was shared and busy, and blamed it for the slow 30B calls. That was wrong. The GPU was ours, and no one else used it. The 30B was slow because the box gives our container 4 CPUs, while Ollama ran the model with 149 threads, so it decoded 20 tokens/s instead of 98. In some runs our own jobs on the same box (other chats, the speculative-decoding verifier) may also have queued calls or held GPU memory; that part is not proven. Tuned (`num_thread = 4`, then our own Ollama with flash attention, q8 KV cache, 4 slots, `keep_alive = -1`), the 30B passes 270/301 cost-case tasks (was 269/301) at a median 2.7 s per call (was 78.0 s) and $0.18 to $0.52 per 1,000 calls (was $11.02). The numbers below are kept as measured, before tuning.

Date 2026-11-15 (PST). A senior chat on the Mac led two junior `kiro-cli` 3.3.0 agents, k1 (4 CPU, 7 GB) and k2 (2 CPU, 3 GB). Neither box has a GPU or any key. The juniors wrote code and offline tests with fakes. Each change went in as a pull request. The senior read every diff, ran the full suite on the Mac against dev, and squash-merged. Live checks ran only from the Mac. Each run happened once, with no repeats.

## Result per item

| # | Item | Before | After | Commit |
|---|---|---|---|---|
| 1 | GPU 30B link self-heal | `/api/health` showed `gpu_tunnel.up = false`. A tier that hung after a good probe waited a full timeout 3 times in a row before the breaker opened. | `scripts/gpu_tunnel_keep.sh` (`make gpu-keep`) brought a killed tunnel back in **5 s** and a hung (SIGSTOP) one in **17 s**. `gpu_tunnel.up = true`. A failed call marks the tier down until its next probe, so a hang now costs **1** timeout. | e160201 |
| 2 | Modal H200 30B as a live tier | Not in the pool. | The `gpu-h200` tier (vLLM Qwen3-30B-A3B) goes first, but only while warm. On a cold call it was skipped at once, the next tier answered, and a wake started. **4 of 6** warm calls were answered on the H200 in **0.7-1.9 s**. The container scaled to zero, then the app was stopped. | e160201, 5176082 |
| 3 | Bank in `chimera code` | `chimera code` never looked at the bank. | It checks the bank before any model call and serves a match only after the match passes its tests in a temporary copy of the project. Passing answers are written back. Live: run 1 was answered by the GPU 30B (227 tokens) and saved. Run 2 was **served from the bank: 0 tokens, $0**. | d361064 (PR #1) |
| 4 | Property bugs marked xfail | 4 xfailed | **0 xfailed**. Each fix had one junior task and one PR. | 00d667f, 8e2bc63, c7d51cd, 48bd0b0 |
| 5 | Live checks from the Mac | See [the v1 run](results_backend.md) | `check_ui_backend.py` passed 41 of 41 checks. The 60-prompt run and the terminal run are below. | this file |

Test counts (`pytest -q tests` on the Mac, Python 3.14 venv, offline): **239 passed, 4 xfailed** at the start, **257 passed, 0 xfailed** at the end.

## Item 1: the GPU link

Before, the tunnel to the GPU box was a plain `ssh -L` with nothing to restart it. `scripts/gpu_tunnel_keep.sh` reads `CHIMERA_GPU_SSH` (an ssh alias) and `CHIMERA_GPU_URL` from `.env`. It opens only a local port forward. It probes `/api/tags` every 5 s and kills its own ssh after 2 misses in a row. The loop reconnects 2 s later. Nothing on the GPU box is started, stopped or changed: Ollama was not touched.

Self-heal test (`bench/.scratch/backend_v2/heal_test.sh`):

| Fault | Time until the 30B URL answered again |
|---|---|
| ssh killed (tunnel dead, port closed) | 5 s |
| ssh frozen with SIGSTOP (port open, nothing answers) | 17 s (first try with a 10 s probe: 45 s) |

Router side. The setup is the real `TierPool` and `http_probe` against fake local servers, 8 calls per case, with a 10 s timeout standing in for the tier's real one:

| Case | Before: total s, calls that waited a full timeout | After |
|---|---|---|
| A: port closed | 0.0 s, 0 | 0.0 s, 0 |
| B: port accepts, never answers | 3.0 s (one 3 s probe), 0 | 3.0 s, 0 |
| C: probe answers, call hangs | 30.0 s, **3** | 10.0 s, **1** |

Test: `tests/test_tiers.py::test_failed_call_marks_tier_down_until_next_probe`.

## Item 2: the H200 30B tier

Setup: app `chimera-qwen30b` (`deploy/modal/vllm_qwen30b.py`), one H200, vLLM, `Qwen/Qwen3-30B-A3B-Instruct-2507`. Settings: `min_containers=0`, `scaledown_window=120`. Modal profile `manvenderraparia`. A new `chimera-vllm-token` secret was made from `.env`. Tier entry in `chimera.example.toml`:

- `warm_only = true` is the flag. `enabled = false` turns the tier off.
- `modal_app = "chimera-qwen30b"`, `logprobs = true` (the same 0.95 gate as the Ollama 30B), `max_complexity = 0.6`, `timeout_s = 90`.
- Default order: cache -> `gpu-h200` (only while warm) -> `gpu-small` (GPU 30B) -> `cloud-deepseek` (763B). Test: `test_default_order_is_h200_if_warm_then_gpu_30b_then_763b`.
- The warm check runs in the background: a running container in `modal container list` plus a `/v1/models` probe. A call never waits on it. A cold result sends one wake request.
- A low-confidence H200 answer skips the GPU 30B, because it is the same model. It goes straight to the 763B.
- In `chimera code`, the H200 is part of the 30B step, so a failed test round climbs past both.

Live run (`bench/run_h200_tier.py`, rows in `bench/.scratch/backend_v2/h200_live.jsonl`):

| Step | Tier | Time | Note |
|---|---|---|---|
| call 0, H200 cold | gpu-small, then cloud-deepseek | 46.4 s | H200 skipped at once ("skipped unhealthy: gpu-h200"). The 30B took 39.5 s, and its confidence of 0.943 was under the 0.95 gate, so the call climbed. |
| wake to ready | - | **845 s** | Cold start in the new workspace, including the weight download into an empty volume. The v1 cold start was 470 s. A second start was not measured. |
| call 1 | gpu-small | 38.5 s | The warm state was stale. This call read the old "cold" answer and refreshed in the background. |
| calls 2-7 | gpu-h200 x4, cloud-deepseek x2 | H200: 1.85, 0.77, 1.07, 0.71 s | The 2 climbs were H200 answers at confidence 0.932 and 0.934, under the gate. The GPU 30B was skipped for those. |
| idle | - | gone 170-185 s after the last call | `scaledown_window` is 120 s, and Modal took about 1 minute longer. |

Stop proof (`modal app stop -y chimera-qwen30b`, then `modal app list`):

```
chimera-qwen30b stopped 0 2026-11-15 23:33:12-08:00
```

The other `chimera-spec-*` apps in that list belong to another chat and were not touched.

**H200 spend:** the most the container could have run is 23:14:04 (wake) to 23:33:06 (gone), 1,142 s. At $0.001261/s ([Modal H200 price](https://modal.com/blog/introducing-b200-h200)) that is at most **$1.44** of GPU time, and $1.07 of it is the 845 s cold start. CPU and memory meters are not included.

## Item 3: the bank in `chimera code`

PR #1 changes `apps/terminal/agent.py` and `cli.py`. For each task:

1. Look the request and the context files up in the bank (Supabase `solved_bank`, tenant `<tenant>:terminal`).
2. A match runs through `Session.verify`. It copies the project to a temp dir without `.git`, `.venv` or any credential file, restores the task's start files, applies the stored edits, and runs this session's own test command. A test command stored with the row is never run.
3. If that passes, the edits are shown for approval, written, and tested again in the project. A failure there is undone and the model answers.
4. A model answer that passes is written back as full-file blocks. `Bank.add` runs the tests once more before it stores anything.

`--no-bank` turns the bank off. With no `CHIMERA_DB_URL` there is no bank, because nothing is stored on the Mac.

Live (`bench/.scratch/backend_v2/term_run.sh`): the same bug fix in two fresh copies of a 2-file project.

| Run | Answered by | Tokens | $ | Time | Tests |
|---|---|---|---|---|---|
| 1 | gpu-small (GPU 30B) | 227 | $0 | 6.9 s | pass, written to the bank |
| 2 | bank (exact), no model call | 0 | $0 | 4.9 s | pass in the copy, then again in the project |

The 4.9 s is mostly the embedder load and the two test runs. An all-763B run would have cost $0.000094 for run 1.

## Item 4: property bugs (xfail -> pass)

| Property | Root cause | Fix |
|---|---|---|
| card numbers glued to `_` or a letter were not scrubbed | `\b` in `_CARD` | `(?<!\d)` and `(?!\d)` lookarounds (`memory/safety.py`) |
| `consistent(a, a)` was False for "What is Python's GIL" | entities kept the apostrophe, the word set dropped it | the same apostrophe rule for both (`cache/guard.py`) |
| exact-cache keys collided when a namespace held NUL | NUL separator | refuse NUL in a namespace. Every other hash stays byte-for-byte the same, and a test pins one value (`cache/exact_cache.py`). |
| LadderRouter cached a top answer that failed `check` | the top path never ran `check` | run it, and cache only on a pass. A crashing check counts as a fail (`ladder.py`). |

## Who did what

| PR | Junior | Task | Review rounds | Merge |
|---|---|---|---|---|
| #1 | k1 | bank in `chimera code` | 2. Round 1 notes: never copy credential files into the temp dir, run only the session's own test command, imports at the top, a shortcut comment. | d361064 |
| #2 | k2 | card scrub xfail | 1 (plus one restart: the box had no git identity, so the first commit failed) | 00d667f |
| #3 | k2 | guard apostrophe xfail | 1 | 8e2bc63 |
| #4 | k1 | exact-cache NUL xfail | 1 | c7d51cd |
| #5 | k2 | ladder top-check xfail | 1 | 48bd0b0 |

The senior wrote items 1, 2 and 5: e160201 and 5176082, the live runs and this file. Box setup: a fresh clone, `python3.14-venv` from apt, a venv with `.[dev]` and numpy, and a repo-local git identity on the GitHub no-reply address. No key or `.env` was copied to either box.

## Item 5: live checks

### `scripts/check_ui_backend.py` (the web server on 127.0.0.1:8765, restarted on the new code)

```
PASS  health gpu_tunnel.up  (True)
PASS  health modal.state  (not_deployed)
      steps: embed -> cache_shared -> memory -> decide -> call -> draft -> memory -> final -> answer -> done  (6.8 s)
PASS  session tokens_today up (or a cache hit)  (+56, cache hit=False)
PASS  stats storage.neo4j.nodes  (2156)
RESULT: all checks passed
```

These are 5 of the 41 lines. All 41 passed, and the full output is in `bench/.scratch/backend_v2/check_ui_backend.txt`. The `modal.state` field reports the old `chimera-gpu-large` app only. It does not show the H200 30B.

### 60-prompt BASE / COLD / WARM

Setup is the same as [v1](results_backend.md): the same 60 prompts, the same `bench/run_backend.py`, a fresh Supabase namespace, gate 0.95, guard on. The ladder in that runner is the GPU 30B and the 763B, without the H200. Rows are in `bench/.scratch/backend_v2/run/`.

| pass | 763B calls | GPU 30B calls | cache hits | 763B tokens | 763B $ | graded correct | p50 ms | p90 ms | calls >= 90 s | errors |
|---|---|---|---|---|---|---|---|---|---|---|
| v1 BASE | 60 | 0 | 0 | 13741 | $0.01280 | 45/48 | 896 | 2981 | 0 | 0 |
| v1 COLD | 43 | 26 | 5 | 12063 | $0.01113 | 45/48 | 2340 | 91577 | 8 | 0 |
| v1 WARM | 2 | 3 | 57 | 349 | $0.00023 | 46/48 | 138 | 164 | 2 | 0 |
| **v2 BASE** | 60 | 0 | 0 | 12664 | $0.01150 | 45/48 | 1210 | 2670 | 0 | 0 |
| **v2 COLD** | 14 | 51 | 5 | 5956 | $0.00615 | 48/48 | 8594 | 21758 | **0** | 0 |
| **v2 WARM** | 0 | 0 | 60 | 0 | $0 | 48/48 | 113 | 122 | 0 | 0 |

- v2 COLD against v2 BASE: 763B tokens -53.0%, 763B $ -46.5%. In v1 the cut was -12.2% tokens and -13.0% $.
- v2 WARM: 60 of 60 answers came from the shared cache, and 0 of 48 graded cache answers were wrong. Lookup median: 110 ms.
- The slowest v2 COLD calls were `h2` at 45 s, `h6` at 43 s and `gsm8k-325` at 36 s. No call reached the 90 s GPU timeout. v1 had 8.

## Verdict

What worked:
- The GPU link heals itself: 5 s after a dead tunnel, 17 s after a hung one.
- No v2 COLD call waited a 90 s timeout. The H200 30B answered warm calls in under 2 s.
- The bank served a repeat coding task with no model call, and only after its tests passed.
- All 4 property bugs are fixed, and every junior PR was right within 2 rounds.

What failed or is weak:
- **The COLD speedup cannot be credited to the code alone.** The V100 had 0 MiB in use at the start of this run. In v1 the box was shared, and that is where the 90 s timeouts came from. The tunnel fix and the router change remove repeated waits, but an idle GPU box explains much of the p90 drop from 91.6 s to 21.8 s. The two runs cannot be separated.
- **The H200 cold start was 845 s, and it cost about $1.07 before the first answer.** Every burst of traffic after 2 idle minutes pays this again, so the H200 tier saves money only under steady traffic. See the break-even analysis in [the H200 cost case](results_cost_case_h200.md).
- **2 of 6 warm H200 answers were under the 0.95 gate** and went to the 763B. That is a small sample.
- **One call after the warm-up still went to the slow GPU 30B (38.5 s),** because the warm state refreshes in the background. This is by design: a call never waits on the check.
- **Scale-to-zero took about 3 minutes, not 2.**
- **A hung tier still costs its first timeout.** The router cannot know it is hung before it calls. The tunnel probe checks `/api/tags` only, so a hung Ollama whose tags still answer is caught by the router (it marks the tier down), not healed by the script.
- The card-scrub regex now also drops one trailing space or `-` after an unspaced card (cosmetic).
- On the junior boxes the full suite has one known failure, because a git-ignored dataset is missing there. It passes on the Mac.

## Rerun

```
make gpu-keep &                                   # SSH tunnel to your GPU box, self-healing
.venv/bin/python -m pytest -q tests
make modal-qwen-up && .venv/bin/python bench/run_h200_tier.py 6; make modal-qwen-down
BENCH_STORE=bench/.scratch/backend_v2/run BENCH_NS=bench-v2-$(date +%s) .venv/bin/python bench/run_backend.py run BASE COLD WARM
.venv/bin/python scripts/check_ui_backend.py
```
