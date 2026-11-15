# Savings replay on public real traffic (OpenAssistant oasst1)

Tool: `bin/chimera replay` (`apps/replay/`). Handoff: `docs/handoff/replay.md`. Raw rows: `bench/.scratch/replay_live_oasst300.jsonl` (git-ignored). Summaries: `bench/results_replay_live.json`, `bench/results_replay_est.json`.

## Verdict
On this traffic the ladder does **not** cut tokens, and it is **8x slower**. Its dollar saving comes from the 763B's low list price, not from the cheap tiers.

| Question | Answer | Where |
|---|---|---|
| Did the 30B answer? | 18 of 300 (6%). 280 climbed to the 763B. 2 were exact cache hits. | live run |
| Tokens on the 763B vs the company's model | 595,073 vs 541,730 per 1k requests (**9.8% more**). | live run |
| $ per 1k requests, ladder vs GPT-5.5-class list price | $0.69 vs $15.58. Measured ladder cost, projected company cost. | live run |
| Same traffic on the 763B alone | about $0.74 per 1k. The ladder saves about 6% of that. | derived |
| Latency | ladder p50 82.7 s, p90 130.3 s. 763B alone p50 10.6 s (18 reference calls). | live run |
| 30B quality (judge vs 763B answer) | 15 of 18 pass (score >= 4 of 5). Scores below 4: 2, 2, 3. | live run |
| Wrong cache hits (live) | 0 semantic hits in 300, so nothing to judge. | live run |
| Wrong cache hits (5,000 estimate) | 82 of 97 near-repeat pairs judged not interchangeable. 81 of the 84 non-ASCII ones are wrong. | estimate |

Failures and where the ladder costs more:
1. **Time.** A 30B call that fails its check costs a median 79 s of waiting before the 763B starts. 253 of 280 climbed requests had that wait. The Akash box is shared, so this is not a clean 30B speed.
2. **Confidence gate.** Mean 30B token probability on the requests that climbed was 0.83, against the 0.95 gate. Open chat is the case the gate was set to reject.
3. **Cache false hits on non-English prompts.** The cosine 0.97 check plus the guard passed unrelated Thai and Chinese prompts (for example a Thai school-history question against a Thai travel question). The embedder is English MiniLM, and the guard reads English words and digits, so it sees nothing to compare. Of 13 mostly-ASCII near pairs, 1 was wrong. This is a router-core issue; it is written up in `docs/handoff/replay.md` for the backend owner.
4. **Fixed GPU box.** At $0.50 an hour ($365 a month, an assumption from `bench/cost_case/report.py`) the ladder only pays back against a frontier price. At 100,000 requests a month it nets about $1,137 against GPT-5.5-class, $98 against Sonnet-class, and loses $108 against Grok-class. Against the 763B alone it never pays back.
5. **Token counts are len/4** because oasst1 has no usage fields. Non-English text uses more tokens per character, which is why the 763B count is above the estimate.

## Setup
- Data: [OpenAssistant/oasst1](https://huggingface.co/datasets/OpenAssistant/oasst1), `2023-04-12_oasst_ready.trees.jsonl.gz`, Apache-2.0, ungated. First-turn prompter messages, all languages: 10,363. `bench/replay_prep_oasst.py` writes the request log.
- Live: `--sample 300 --seed 0 --live --judge-n 40`. Ladder = Supabase cache (tenant `replay-oasst300`, purged before and after; exact, then cosine 0.97 + guard) -> Akash `qwen3:30b-instruct` -> Crusoe DeepSeek-V4.1-Flash 763B (thinking off), through `SpeculativeCascadeRouter.generate()` with a tier pool. No Mac 3B. Reference answers: the 763B alone, no cache. Judge: GMI `zai-org/GLM-5.3-Flash`, score 1-5 against the 763B answer, pass at 4 or more.
- Judge sample: 40 requested, but only the 18 the 30B answered exist, so all 18 were judged and all 18 got a score.
- Estimate: `--sample 5000 --seed 0`, MiniLM cosine 0.97 + guard for near repeats, class rates from the live run. Near-repeat wrong-hit rate from `bench/replay_near_dup_judge.py` (GMI yes/no on 97 pairs, exact repeats excluded). Prices: `apps/replay/prices.py`.
- Every ladder, reference and judge call is in `bench/.scratch/replay_eval_log.jsonl` (EvalRow format, read by `bench/evallog.py`).
- Cost of the grader runs: judge $0.0037, 763B reference calls $0.0051.

## Live run: 300 requests (measured)
Classes: exact repeat 2, easy code 32, lookup 248, general 18. Failed requests: 0.

| Company model (list $/M in/out) | Their $ per 1k | Ladder $ per 1k | $ saved |
|---|---|---|---|
| GPT-5.5-class (5/30) | $15.58 | $0.69 | 95.6% |
| Claude Opus-class (4/20) | $10.40 | $0.69 | 93.4% |
| Claude Sonnet-class (2/10) | $5.20 | $0.69 | 86.8% |
| Grok-class (2/6) | $3.14 | $0.69 | 78.1% |

Their cost is projected: it prices the logged prompt (len/4) and the ladder's answer length at their list price. Ladder cost is measured 763B spend. The 30B is free per token, so its box cost is in the monthly table below.

| Per month at 100,000 requests | Their $ | Ladder $ + GPU box | Net | Break-even requests a month |
|---|---|---|---|---|
| GPT-5.5-class | $1,558 | $434 | +$1,124 | 24,512 |
| Claude Opus-class | $1,040 | $434 | +$607 | 37,567 |
| Claude Sonnet-class | $520 | $434 | +$86 | 80,852 |
| Grok-class | $314 | $434 | -$119 | 148,648 |

## Estimate: 5,000 requests (projection, not measured on this log)
Classes: repeat 43, near repeat 84, easy code 343, lookup 4,262, general 245, hard 23. Rates carried from the live run: 30B answers 16% of easy code, 5% of lookup, 0% of general; judged agreement 83%; near-repeat wrong rate 85%.

| Company model | Their $ per 1k | Ladder $ per 1k | $ saved | Net a month at 100,000 |
|---|---|---|---|---|
| GPT-5.5-class | $15.60 | $0.58 | 96.3% | +$1,137 |
| Claude Opus-class | $10.42 | $0.58 | 94.5% | +$619 |
| Claude Sonnet-class | $5.21 | $0.58 | 88.9% | +$98 |
| Grok-class | $3.15 | $0.58 | 81.7% | -$108 |

Tokens on the 763B: 501,705 vs 544,853 per 1k (7.9% fewer, almost all from cache hits). Projected: 46 30B answers worse than the 763B, 71 wrong cache hits.

## Prices
Sources are in `apps/replay/prices.py` and in the tool's output. Claude-class prices come from a [third-party page](https://developer.puter.com/tutorials/claude-api-pricing/) and were not checked against the [Anthropic price page](https://platform.claude.com/docs/en/about-claude/pricing). GPT-5.5 and Grok list prices come from `bench/cost_case/report.py`. 763B: $0.29 in, $1.20 out per million (`bench/results_ladder.md`).

## What this does not show
- One run, one seed, one dataset. 18 judged answers is a small sample (83% has a wide interval).
- oasst1 is volunteer chat, mostly open questions. A company log full of FizzBuzz-class calls would give the 30B a higher answer share. That is the case the tool is for, and it is untested here. `bench/results_cost_case.md` did not exist when this ran, so the estimate uses rates from this live run, not that file.
- The 5,000 estimate's class rates come from 300 requests.
