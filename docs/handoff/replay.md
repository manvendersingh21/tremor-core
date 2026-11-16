# Handoff: `chimera replay` (savings replay on a company's own request log)

## Use
```
bin/chimera replay <log.jsonl|log.csv> [--sample N] [--seed S] [--volume REQS_PER_MONTH] [--out PREFIX]
    --estimate   (default) no model calls: classify and project
    --live       run the real ladder, grade a sample of 30B answers against the 763B with a GMI judge
    --rates F    estimate: rates file written by a --live run (PREFIX.rates.json)
    --no-embed   estimate: exact repeats only, skip the cosine near-repeat check
```
- Log formats: OpenAI-style JSONL (`messages`, `model`, `usage`; also batch lines with `body` / `response.body.usage`) and CSV (`prompt` or `messages`, `model`, `prompt_tokens`, `completion_tokens`).
- `--live` needs, in `.env`: `CHIMERA_DB_URL`, `CRUSOE_API_KEY`, `GMI_API_KEY`, `CHIMERA_GPU_URL` (the local end of an SSH tunnel to your GPU box). The cache tenant is `replay-<name>`, purged before and after.
- Run files: `bench/.scratch/replay_live_<name>.jsonl` (one row per request, resumable), `bench/.scratch/replay_eval_log.jsonl` (every ladder, reference and judge call; `bench/evallog.py` imports it).

## Files
`apps/replay/{logs,prices,estimate,live,report,cli}.py`, `bench/replay_prep_oasst.py` (oasst1 to a request log), `bench/replay_near_dup_judge.py` (wrong-hit rate of near repeats), `tests/test_replay.py`.

## Limits
- Prices in `apps/replay/prices.py` are list prices with sources; re-check before quoting.
- `bench/results_cost_case.md` did not exist when this was built. Estimate rates come from the live run, or are labelled assumptions.
- The system prompt is not sent to the router (it counts only in input tokens).
- Token counts are len/4 when the log has no usage.
- GPU box cost ($0.50/h V100) is an assumption from `bench/cost_case/report.py`.

## Needs from other owners (backend owner, router core)
- **Cache false hits on non-English prompts.** `bench/results_replay.md`: at cosine 0.97 plus `cache/guard.py`, unrelated Thai and Chinese prompts matched (81 of 84 non-ASCII near pairs judged not interchangeable). The English MiniLM embedder puts non-Latin text close together, and the guard reads only English words and digits. Suggest: a multilingual embedder, or make the guard reject a hit when either prompt is mostly non-ASCII and the texts differ. Not changed here.
- The 30B gate (0.95) rejects most open chat, so each such request waits for a failed 30B call before the 763B (median 79 s on the V100 before tuning; the box was not shared, the 30B was thread-bound, see `bench/results_akash_tuning.md`). A cheap pre-check that sends open chat straight to the 763B would remove that wait.
