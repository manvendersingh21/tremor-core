# Demo video script: 2 minutes 45 seconds

For the Kiroween 2026 YouTube upload (must be under 3 minutes, public). Every number on screen comes from the file named in its row. Say the numbers exactly as written.

The recorded cut (`site/docs/demo_cut.mp4`) uses a newer shot list with the same pitch: cache hit, FizzBuzz on the 30B, a climb to the 763B, the bill, the Workshop. Its narration and timings are in `site/docs/demo_video.md`. Read that one over the recorded cut.

## Before you record

1. `make web`, then open `http://127.0.0.1:8765` in Chrome at 1280x720.
2. Have the GPU tunnel up (`make gpu-keep`) so the 30B answers. Do not show the terminal that starts it: it holds a host name.
3. Seed the cache once with the question used in shot 3. Ask it one time before recording, so the shot shows a cache hit.
4. Open these files in tabs, zoomed so one table fills the screen: `bench/results_company_cost.md`, `bench/results_spec_modal.md`, `docs/prd/monthly_cost.png`, `docs/prd/spec_speed.png`.
5. Hide `.env`, the shell history and any window that shows a host, an IP, a port or a key path.
6. A scratch folder with a 2-file project and one failing test for `chimera code` (shot 5). The same project as in `bench/results_backend_v2.md`, item 3, works.

## Shot list

| # | Time | Screen | Do or type | Number on screen | Source |
|---|---|---|---|---|---|
| 1 | 0:00-0:12 | Castle landing (painted moon, gates, Count Cuspid) | nothing; let the bats fly | title "CHIMERA" | `site/` |
| 2 | 0:12-0:30 | Castle walk | hold **W**: gates open, drive, gold door, Great Hall | none | `site/game/` |
| 3 | 0:30-0:50 | Great Hall, chat with the Count | press **T**, type `Write FizzBuzz in Python`, Enter; read the trace | tier `cache`, about 0.1 s, 0 tokens | `bench/results_company_cost.md` (WARM median 112 ms) |
| 4 | 0:50-1:05 | Observatory (Halloween dashboard) | walk to the Observatory door, press **E** | tokens saved, dollars saved, calls by tier | live `/api/stats` |
| 5 | 1:05-1:30 | Terminal | `bin/chimera code -m "fix the failing test" --yes` in the scratch project, run it twice | run 1: 30B, 227 tokens; run 2: bank, 0 tokens, $0 | `bench/results_backend_v2.md` (item 3) |
| 6 | 1:30-1:55 | `docs/prd/monthly_cost.png`, then the h = 30% table in `bench/results_company_cost.md` | point at the GPT-5.5 row, then the 763B row | 62% to 87% saved vs GPT-5.5; at 100k a day the 763B row says -607% | `bench/results_company_cost.md` |
| 7 | 1:55-2:15 | `docs/prd/spec_speed.png`, then the Phase A summary in `bench/results_spec_modal.md` | point at EAGLE-3, then the two-box rows | same box EAGLE-3 162.2 tok/s, 1.80x; two boxes 0.09x to 0.27x | `bench/results_spec_modal.md` |
| 8 | 2:15-2:32 | Kiro: `.kiro/` tree, `.kiro/specs/chimera-speculative-os/design.md` section 5, `docs/handoff/property-tests.md` | scroll the 4 bug rows | 39 property tests, 4 bugs found, all fixed | `docs/handoff/property-tests.md`, `bench/results_backend_v2.md` |
| 9 | 2:32-2:45 | Castle landing again | nothing | repo URL and the pitch as a caption | `docs/hackathon/submission.md` |

## Narration (about 380 words, read at a calm pace)

**Shot 1 (0:00).** "Companies pay a frontier model for every coding call. Even FizzBuzz. This is CHIMERA. It answers each call at the cheapest place that gets it right."

**Shot 2 (0:12).** "The whole app is one page. You walk in like a movie. Hold W. The gates open. Every room behind these doors shows live numbers from the router."

**Shot 3 (0:30).** "I ask the Count for FizzBuzz. Someone asked this before. So the answer comes from our shared cache, in about a tenth of a second. Zero tokens. No model was called. In three repeats, 58 or 59 of 60 repeat questions came from the cache, with zero wrong answers."

**Shot 4 (0:50).** "The Observatory is the dashboard. It counts tokens and dollars kept off the big model, per tier, per call."

**Shot 5 (1:05).** "This is chimera code, our terminal coding agent. First run: a self-hosted 30B fixes the bug, and the tests pass. Same task again: the fix comes from our bank of solved problems. It is served only after it passes the tests again. Zero tokens. Zero dollars."

**Shot 6 (1:30).** "Here is the money. Against GPT-5.5, a 30B on rented H200s saves 62 to 87 percent a month, if 3 in 10 calls are repeats. Now the loss. Against a cheap big model, the 763B on Crusoe, at 100 thousand calls a day we cost more, not less. And our 30B gets about 1 in 10 coding tasks wrong. Tests have to catch those. And on our own old V100, tuned, the 30B answers a coding task in under 3 seconds, 9 times in 10."

**Shot 7 (1:55).** "We also tested speculative decoding on Modal. A small model drafts, a big model checks. With the drafter on its own box, it was 4 to 12 times slower. Inside the big model's own box, EAGLE-3 made the 235B 1.8 times faster. So we keep it in one box."

**Shot 8 (2:15).** "We built this with Kiro. Seven specs, six hooks, four custom agents, an MCP server and a Power. Property tests from the specs found four real bugs. All four are fixed."

**Shot 9 (2:32).** "Stop paying a frontier model for FizzBuzz. We prove it with tests. CHIMERA, for Kiroween 2026."

## Numbers to check before upload

| Said on screen | File | Line to look for |
|---|---|---|
| about 0.1 s from cache | `bench/results_company_cost.md` | WARM p50 112 ± 4 ms |
| 58 or 59 of 60, zero wrong | `bench/results_company_cost.md` | WARM cache hits 58.7 ± 0.6 |
| 227 tokens, then 0 tokens and $0 | `bench/results_backend_v2.md` | Item 3 table |
| 62% to 87% vs GPT-5.5 | `bench/results_company_cost.md` | h = 30% table |
| 763B costs more at 100k a day | `bench/results_company_cost.md` | -607% (h = 30%), -611% (h = 0) |
| about 1 in 10 wrong | `bench/results_company_cost.md` | 31 of 301 failed |
| own V100, under 3 s, 9 in 10 | `bench/results_akash_tuning.md` | tuned 30B, 270/301, p50 2.7 s |
| 4x to 12x slower, two boxes | `bench/results_spec_modal.md` | Phase A verdict, point 1 |
| EAGLE-3 1.80x | `bench/results_spec_modal.md` | `a235_big_eagle_q3_235b`, 162.2 tok/s |
| 4 bugs found, all fixed | `docs/handoff/property-tests.md`, `bench/results_backend_v2.md` | item 4 |

If the live trace in shot 3 or 5 shows a different number, say the number on screen. Do not read the script number over it.
