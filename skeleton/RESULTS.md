# Skeleton Crew results: one skeleton, two apps

One run of `skeleton/bench/run.py`, live and demo, on 2026-11-17. No repeats. The help desk and the class/coder sections were run live about 10 minutes apart (`--only helpdesk` for the help desk).

- **Live:** the self-hosted 30B (`qwen3:30b-instruct`, Ollama on GPU 1 of our A6000 box, reached over a tunnel), the Crusoe 763B (`deepseek-ai/DeepSeek-V4.1-Flash`), the shared Supabase cache (all-MiniLM-L6-v2, cosine 0.97, guard on, normalized prompts). Both GPUs were idle when each run started, and our server was stopped right after each (GPU 1 back to 12 MiB).
- **Demo:** stub models (`DEMO_MODELS` in each app), the same `PgVectorCache` code over an in-memory table, a word-bag embedder (`skeleton/core/demo.py`). It needs no key, and CI runs it.

The $ columns are 763B list price. The A6000 is priced $0. "If every question went to the 763B" is an estimate: what was spent, plus what each cache hit and each 30B answer would have cost on the 763B.

Rerun:

```bash
.venv/bin/python skeleton/bench/run.py           # demo
.venv/bin/python skeleton/bench/run.py --live    # 30B (CHIMERA_GPU_URL), 763B (CRUSOE_API_KEY), Supabase (CHIMERA_DB_URL)
```

Rows: `bench/.scratch/skeleton/{helpdesk,coder,students}_{live,demo}.jsonl` (git-ignored).

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

## Help desk: 200 support tickets after a 30-ticket warm-up

Knowledge base: `skeleton/apps/helpdesk/kb.json` (20 FAQ entries with steps, policies, hours, contact; invented). Mix (seed 7): 70% the 30 common questions (rank r asked with weight 1/r), 18% other wording of one of them, 12% new tickets. 50 distinct tickets.

| | Live | Demo |
|---|---|---|
| Warm-up (30 tickets) | 31 model calls, 36,252 tokens, 33 s | 36 model calls, 41,735 tokens |
| Cache hit rate | **86.0%** (172 of 200: exact 164, cosine 8) | 83.5% (167: exact 157, cosine 10) |
| Wrong cache answers | **0** | 0 |
| Model calls (climbs to the 763B) | 32 (4) | 58 (25) |
| Answers that failed the knowledge-base check | 1 | 17 |
| Tokens used / kept off the 763B | 38,393 / 230,615 | 66,409 / 205,261 |
| $ spent / if every ticket went to the 763B | $0.001371 / $0.075617 | $0.008714 / $0.075076 |
| Median latency: cache hit / model | **113 ms** / 996 ms | (not timed) |

Cost per ticket as volume rises, live (the 30 warm-up tickets included):

| Tickets | Model tokens per ticket | $ per ticket | $ per ticket if all went to the 763B |
|---|---|---|---|
| 1 | 1,172 | $0 | $0.000380 |
| 30 | 1,208 | $0.000011 | $0.000370 |
| 50 | 794 | $0.000014 | $0.000374 |
| 100 | 508 | $0.000010 | $0.000376 |
| 200 | 373 | $0.000009 | $0.000377 |

What this shows:
- A few questions make most tickets. After warm-up, 172 of 200 tickets needed no model, and a hit answered in 113 ms (p50, p90 156 ms).
- Model work per ticket fell from 1,208 tokens at 30 tickets to 373 at 200, as more tickets repeated an answered one. $ per ticket stayed near $0.00001 because the 30B is owned ($0); the $ comes from the 4 climbs to the 763B.
- Failed, a finding: 7 repeat tickets missed the cache because their answer quotes the support phone number ("What is your phone number?", "How do I contact a person?", "Why was my card charged twice?"). The core's privacy scrub (`memory/safety.py`) reads it as personal data, and the router never caches an answer the scrub would change. So those answers paid the 30B every time. Allowing a company's own public contact details would fix it; that is a core change, not made here.
- Failed: 2 other repeats ("How long do refunds take?", "I forgot my password, how do I reset it?") missed once each. The cause was not traced.
- Failed: reworded tickets reached their seed's answer by cosine only 8 times. "where is my order??" and "how do i reset my password" hit; "I forgot my password, how do I reset it?" did not.
- Demo climbed more (25 against 4) because the stub 30B only matches words. The live 30B answered most new tickets itself.

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
- Held, live: a class asking the same assignments and readings got 92.7% of its 150 questions from the cache, in 162 ms (p50), with 0 wrong cache answers. Spend was $0.0007 against about $0.026 if every question had gone to the 763B. The help desk got 86.0% of 200 tickets, with 0 wrong; model tokens per ticket fell from 1,208 to 373.
- Failed: few reworded tickets reached their seed's answer at cosine 0.97 (8). Answers that quote the support phone number are never cached (privacy scrub). One check false-rejected a numbered list (fixed after the run). Single run, no repeats.
