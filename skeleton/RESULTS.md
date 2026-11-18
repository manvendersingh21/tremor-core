# Skeleton Crew results: one skeleton, two apps

**These numbers are DEMO numbers.** The models are stubs (`skeleton/apps/*/` `DEMO_MODELS`), the cache is the product's `PgVectorCache` over an in-memory table, and the embedder is a word bag (`skeleton/core/demo.py`). They show how the skeleton routes, not how good a real model is. Run on 2026-11-17 (a Tuesday, so the Tuesday specials).

A live run was not done. The A6000 30B was serving another session's measured run (`bench/run_hard_live.py`) at the time, and extra calls would have changed its numbers. The live run is one command (below). The same core measured live on the A6000 is in `bench/results_a6000.md`.

Rerun:

```bash
.venv/bin/python skeleton/bench/run.py           # demo (these tables)
.venv/bin/python skeleton/bench/run.py --live    # A6000 30B via CHIMERA_GPU_URL, Crusoe 763B, Supabase cache
```

Rows: `bench/.scratch/skeleton/store_demo.jsonl`, `coder_demo.jsonl` (git-ignored).

## Store: 200 shopper questions after a 30-question warm-up

Mix (seed 7): 70% the 30 common questions (rank r asked with weight 1/r), 18% other wording of one of them, 12% new questions. 50 distinct questions.

| | Value |
|---|---|
| Warm-up | 30 questions, 30 model calls, 22,033 tokens |
| Cache hit rate | **90.5%** (181 of 200: exact 160, cosine 21) |
| Wrong cache answers | 0 |
| Model calls | 26 (7 climbed from the 30B to the 763B) |
| Answered by | cache 181, 30B 12, 763B 7 |
| Answers that failed the catalog check | 7 (served as "ask at the desk", never cached) |
| Tokens used / kept off the 763B | 19,120 / 142,177 |
| $ spent (list price) | $0.001645 |
| $ if every question went to the 763B (estimate) | $0.046293 |

What this shows:
- Repeats are most of a store's questions. After warm-up, 181 of 200 needed no model.
- Other wording hit when it kept the same content words ("where is the oat milk" → "Where do I find oat milk?"). It missed when the words changed ("Which aisle has the eggs?"). The live embedder (all-MiniLM-L6-v2) catches more of these.
- The 7 questions the guide cannot answer ("Can I order a birthday cake?") cost a 763B call every time. They are not cached, because their answer failed the check. This is the main cost left.
- Latency is not reported. In demo every step takes about 4 ms. Live, a Supabase hit took 147-186 ms p50 (`bench/results_a6000.md`).

## Coder: 3 bug-fix tasks, each asked twice

| Task | Pass | Answered by | Tiers called | Tests | Tokens | $ spent |
|---|---|---|---|---|---|---|
| fix-add | 1 | cloud-deepseek | gpu-small -> cloud-deepseek | pass | 232 | $0.000052 |
| greet | 1 | gpu-small | gpu-small | pass | 122 | $0 |
| clamp | 1 | gpu-small | gpu-small | pass | 130 | $0 |
| fix-add | 2 | exact_cache | (cache) | pass | 0 | $0 |
| greet | 2 | exact_cache | (cache) | pass | 0 | $0 |
| clamp | 2 | exact_cache | (cache) | pass | 0 | $0 |

The demo 30B breaks `fix-add` on purpose (`a * b`). Its tests fail, so the patch is not cached and the task climbs to the 763B. Its patch passes and is cached. On pass 2 every patch comes from the cache, and the tests run again on it before it is shown.

## Same core, live (from `bench/results_a6000.md`, not rerun here)

The skeleton calls the same `SpeculativeCascadeRouter` and `TierPool` that run below.

| Measured on the A6000 30B + 763B | Result |
|---|---|
| 763B calls cut, first pass (2,404 items, 8 runs) | 70.7% |
| Wrong answers from the cache, first passes | 0 |
| Same items again: served from the cache | 586 of 601 |
| Cache hit latency, p50 | 147-186 ms |

## Verdict

- Held: one `Assistant` serves both apps. Each app is a TOML file, one knowledge hook and one verify hook. The store answered 90.5% of a repeat-heavy mix from the cache with 0 wrong cache answers (demo).
- Failed or not shown: no live run of these two apps. Paraphrase hits in demo come from a word bag, not a real embedder. Unanswerable store questions climb to the 763B every time they are asked.
