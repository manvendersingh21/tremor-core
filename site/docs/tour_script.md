# The guided tour: demo video script

Written by `python3 site/build.py` from `site/demo.json` (the same stops the page plays: press T or the Tour button).
Every number is read from the file named in `site/demo.json`.

| Time | Where | The Count says |
|---|---|---|
| 0:00 | landing | Good evening. I am Count Cuspid. This castle sends every AI question to the cheapest helper that can answer it. Come, I will walk you in. |
| 0:07 | walk | The iron gates open as we arrive, and the great door too. Four seconds from the road to the hall. |
| 0:12 | hall | The Great Hall. The board shows the saved run of the real stack: 120 calls, 52% answered from the cache, 13,763 tokens kept off the big model. |
| 0:22 | observatory | The Observatory counts every call. The second time the same 60 questions came in, 57 were served from the cache with no model, and the ladder spent $0.00023. |
| 0:36 | crypt | The Crypt is the cache in Supabase. Asked again, the hit rate was 0.95. A lookup takes 122 ms. 0 of 50 graded cache answers were wrong. |
| 0:49 | ladder | The Ladder climbs one rung at a time: cache, then our own 30B, then the 763B. Per 1,000 coding calls the 763B costs $0.1576, GPT-5.5 costs $4.02. The bank of solved problems served 75 of 80 repeats, 0 wrong. |
| 1:03 | familiar | The Familiar is a small model for your phone. It is written, but no phone has run it yet. I will not pretend otherwise. |
| 1:12 | workshop | The Workshop shows how Kiro built this castle: 7 steering files, 7 specs, 6 hooks, 4 custom agents, 3 MCP tools and a Power. Hypothesis tried 43 property tests and found 4 real bugs. 4 are fixed. |
| 1:30 | tower | The Tower holds the biggest models. We tried speculative decoding on Modal: EAGLE-3 in the same box ran 1.80x as fast, but a drafter on another box ran at only 0.23x. We show both. |
| 1:42 | gpus | The Manor is our own GPU. A 30B on an H200 kept busy costs $0.070 per 1,000 calls. On our own V100, tuned and kept busy, it costs $0.178; before tuning it cost $11.02. |
| 1:54 | guild | The Guild is for companies: an OpenAI-style gateway, keys per tenant, metrics for Prometheus. Change one address and one key. |
| 2:03 | gate | The Gate: four commands and it runs on your machine. The tests need no models and no keys. |
| 2:12 | ledger | And the bill. At 1 million coding calls a day, GPT-5.5 alone costs $120,600 a month. With the cache, the bank and our 30B first: $25,216, 79% less. Against the cheap 763B we do not save at that volume: the ladder costs $2,518 a month more. Every number here comes from a file. Good night. |

Total: 2 min 32 s of narration, plus the room-door clips (played fast during the tour).
