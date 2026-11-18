# Skeleton Crew results: one skeleton, two apps

One run of `skeleton/bench/run.py`, live and demo, on 2026-11-17 (a Tuesday, so the Tuesday specials). No repeats.

- **Live:** the self-hosted 30B (`qwen3:30b-instruct`, Ollama on GPU 1 of our A6000 box, reached over a tunnel), the Crusoe 763B (`deepseek-ai/DeepSeek-V4.1-Flash`), the shared Supabase cache (all-MiniLM-L6-v2, cosine 0.97, guard on, normalized prompts). GPU 1 was idle when the run started, and our server was stopped right after (VRAM back to 12 MiB).
- **Demo:** stub models (`DEMO_MODELS` in each app), the same `PgVectorCache` code over an in-memory table, a word-bag embedder (`skeleton/core/demo.py`). It needs no key, and CI runs it.

The $ columns are 763B list price. The A6000 is priced $0. "If every question went to the 763B" is an estimate: what was spent, plus what each cache hit and each 30B answer would have cost on the 763B.

Rerun:

```bash
.venv/bin/python skeleton/bench/run.py           # demo
.venv/bin/python skeleton/bench/run.py --live    # 30B (CHIMERA_GPU_URL), 763B (CRUSOE_API_KEY), Supabase (CHIMERA_DB_URL)
```

Rows: `bench/.scratch/skeleton/{store,coder,students}_{live,demo}.jsonl` (git-ignored).

A cache answer counts as wrong when it differs from the first answer to the same question. If the question is new wording, it is compared with its seed question's answer instead.

## Students: the first one pays, the rest get the cache

A class asks the same things. Three assignments ("Assignment 3: write is_palindrome(s) in palindrome.py"), one paper and one chapter ("Summarize this paper"). 150 student questions: 70% pasted as given, 20% reworded, 10% really different ("... without slicing", "in 3 bullet points"). No warm-up, so the first student of each question pays the model. Demo set: `skeleton/apps/coder/classroom.py`, `classroom/paper.md`, `classroom/chapter.md`.

| | Live | Demo |
|---|---|---|
| Distinct questions | 22 | 22 |
| Cache hit rate | **92.7%** (139 of 150) | 93.3% (140 of 150) |
| Hits: pasted as given / reworded / really different | 111/116, 22/25, 6/9 | 111/116, 24/25, 5/9 |
| Wrong cache answers | **0** | 0 |
| Model calls (climbs to the 763B) | 14 (3) | 12 (2) |
| Answers that failed their check | 1 | 0 |
| Tokens used / kept off the 763B | 6,198 / 42,147 | 3,101 / 35,881 |
| $ spent / if every question went to the 763B | $0.000702 / $0.026345 | $0.000263 / $0.018890 |
| Median latency: cache hit / model | **162 ms** / 1,412 ms | (not timed) |

| Item (live) | Asked | From the cache | Model answers |
|---|---|---|---|
| Assignment 3, palindrome | 45 | 43 | 2 |
| Assignment 4, fizzbuzz | 23 | 22 | 1 |
| Assignment 5, word count | 28 | 27 | 1 |
| Paper summary | 38 | 33 | 5 |
| Chapter summary | 16 | 14 | 2 |

What this shows:
- Student 1 pays. A patch is cached only after the assignment tests pass, and the tests run again on each cached patch before a student sees it. A summary is cached only when it is short and every number in it is in the text.
- Really different questions are not served the cached answer. "... without slicing" (the guard sees "without") and "in 3 bullet points" (a new number) went to the model. They hit only when a later student asked the same different question again ("really different" hits: 6 of 9).
- Reworded questions hit only through the cache's rules: the same words once "please", "can you", case and punctuation are dropped, or cosine >= 0.97 that the guard passes. "Give me a summary of this paper" missed (the word changed), so it paid once.
- Failed, live: the paper and chapter summaries from the 30B failed the check on first ask and climbed to the 763B. "Summarize this paper in 3 bullet points" failed the check on the 763B too. The 763B numbered its bullets 1-3, and the number rule rejected them, which was a false reject. That answer was served marked unchecked and was not cached. List markers are now ignored (`summary_ok`, with a test), after this run.

## Store: 200 shopper questions after a 30-question warm-up

Mix (seed 7): 70% the 30 common questions (rank r asked with weight 1/r), 18% other wording of one of them, 12% new questions. 50 distinct questions.

| | Live | Demo |
|---|---|---|
| Warm-up (30 questions) | 31 model calls, 34,593 tokens, 30 s | 30 model calls, 22,033 tokens |
| Cache hit rate | **86.0%** (172 of 200: exact 168, cosine 4) | 90.5% (181: exact 160, cosine 21) |
| Wrong cache answers | **0** | 0 |
| Model calls (climbs to the 763B) | 38 (10) | 26 (7) |
| Answers that failed the catalog check | 7 | 7 |
| Tokens used / kept off the 763B | 42,706 / 147,293 | 19,120 / 142,177 |
| $ spent / if every question went to the 763B | $0.003075 / $0.048769 | $0.001645 / $0.046293 |
| Median latency: cache hit / model | **122 ms** / 866 ms | (not timed) |

What this shows:
- After warm-up, 172 of 200 questions needed no model, and a hit answered in 122 ms (p50, p90 149 ms).
- Failed: live, other wording reached its seed question's answer far less often than in demo (4 cosine hits against 21). Of the 39 reworded asks, 24 came from the cache, but 20 of those were repeats of a rewording that had already paid once. MiniLM put "where is the oat milk" and "Where do I find oat milk?" below 0.97, and the band that would catch them is off (`bench/results_paraphrase_cache.md`). The demo word bag treats them as the same, so the demo hit rate is the optimistic one.
- Failed: the 3 questions the guide cannot answer ("Can I order a birthday cake?") paid a 30B call and a 763B call every time they were asked (7 asks). Their answer fails the check, so it is never cached.

## Coder: 3 bug-fix tasks, each asked twice

| Task | Pass | Live: answered by | Live tokens | Live ms | Demo: tiers called |
|---|---|---|---|---|---|
| fix-add | 1 | 30B, tests pass | 136 | 1,896 | 30B (tests FAIL) -> 763B |
| greet | 1 | 30B, tests pass | 132 | 664 | 30B |
| clamp | 1 | 30B, tests pass | 147 | 829 | 30B |
| fix-add | 2 | cache, tests pass | 0 | 188 | cache |
| greet | 2 | cache, tests pass | 0 | 165 | cache |
| clamp | 2 | cache, tests pass | 0 | 283 | cache |

Live, the real 30B fixed all three tasks, so nothing climbed. The demo 30B breaks `fix-add` on purpose to show the climb: the failing patch is not cached, the 763B's patch passes and is. The class run above shows real climbs.

## Same core, earlier and larger (from `bench/results_a6000.md`)

| Measured on the A6000 30B + 763B | Result |
|---|---|
| 763B calls cut, first pass (2,404 items, 8 runs) | 70.7% |
| Wrong answers from the cache, first passes | 0 |
| Same items again: served from the cache | 586 of 601 |

## Verdict

- Held: one `Assistant` serves both apps. Each app is a TOML file, one knowledge hook and one verify hook.
- Held, live: a class asking the same assignments and readings got 92.7% of its 150 questions from the cache, in 162 ms (p50), with 0 wrong cache answers. Spend was $0.0007 against about $0.026 if every question had gone to the 763B. The store got 86.0%, with 0 wrong.
- Failed: live paraphrase hits were few at cosine 0.97 (4 of the store's 39 reworded asks reached their seed question's answer). Unanswerable questions pay every time. One check false-rejected a numbered list (fixed after the run). Single run, no repeats.
