# We stopped paying a frontier model for FizzBuzz. Here is what it saved, and where it lost.

*Written for Kiroween 2026, the Kiro hackathon. Code: [github.com/manvendersingh21/tremor-core](https://github.com/manvendersingh21/tremor-core) (MIT).*

Companies send every coding call to the biggest model they can buy, FizzBuzz included. A model you run yourself writes FizzBuzz just fine. So why pay a top price for it?

For Kiroween 2026 I built CHIMERA to find out. It is a router. Each call climbs a short ladder and stops at the first step that gets it right. First a shared cache. Then a bank of problems we already solved. Then a 30B model we host ourselves. Only then the big cloud model. Every call logs its tier, its tokens, its time and its cost.

It is a monster stitched from parts: a Supabase cache, a Neo4j graph, a Qwen 30B on a GPU and a 763B model on Crusoe. Its face is a painted Halloween castle. You walk in with W, and the rooms show live numbers.

## What worked

**Repeats are free.** When the same question came back, the cache answered it in about a tenth of a second for zero tokens. In three repeats of a 60-question test, 58 or 59 came from the cache, and none were wrong. A second client got 49 of 60 hits in every repeat, again with none wrong. (All from `bench/results_company_cost.md`.)

**Solved problems stay solved.** The bank serves an old solution only if it passes the new problem's tests right now. On the same 80 problems it served 75 every time, with zero wrong. My terminal coding agent, `chimera code`, uses it too. The first time, the 30B fixed a bug for 227 tokens. The second time, the bank served the fix for 0 tokens and $0 (`bench/results_backend_v2.md`).

**Against a frontier price, the savings are real.** I priced a company that sends coding calls to GPT-5.5. A 30B on rented H200s, with GPT-5.5 re-asked for each call the 30B fails, costs 57% to 81% less a month at 100,000 to 10 million calls a day. If 3 in 10 calls are repeats, it is 62% to 87% less.

**My own old GPU was fine all along.** For days I wrote that the 30B was slow because my V100 was shared and busy. That was wrong. The GPU was mine and idle. The box gives my container 4 CPUs, and Ollama ran the model with 149 threads, so it crawled at 20 tokens a second instead of 98. With 4 threads and my own Ollama (flash attention, 4 slots, model kept loaded), the 30B answers a coding task in a median 2.7 seconds, passes 90% of 301 tasks, and costs 18 to 52 cents per 1,000 calls when the box is busy (`bench/results_akash_tuning.md`). Before, it was 78 seconds and $11.02. At 100,000 coding calls a day, three such boxes at $0.52 an hour plus GPT-5.5 for the failures cost 74% less than GPT-5.5 alone (`bench/results_company_cost.md`).

## What did not work

I promised myself I would write the losses next to the wins.

**A cheap big model is hard to beat.** The 763B on Crusoe costs about 16 cents per 1,000 coding calls. Against that, my ladder costs 7 times as much at 100,000 calls a day. It only saves money at a million calls a day with many repeats. If you already use a cheap model, this router is not your win.

**The 30B is wrong about 1 time in 10.** It failed 31 of 301 coding tasks. The 763B failed 15. The savings above assume tests catch every failure and send it up. Most real requests have no tests. Without them, the cheap bill comes with about one wrong answer in ten.

**New prompts are slower.** With an empty cache, the ladder cut big-model tokens by 56%. But the median call took 6.7 seconds on the 30B before I tuned it, against 1.3 seconds for the big model alone. I have not rerun this test on the tuned box.

**Some ideas just failed.** Solved examples as hints moved the 30B from 68 to 70 of 80, but three random examples also gave 70 (`bench/results_memory.md`). Fine-tuning the 30B on the big model's answers made it worse, from 92.2% to 88.3% (`bench/results_distill.md`).

## The speculative decoding detour

I also tried a small model that drafts tokens for a big model to check, on Modal, with Qwen3-235B checking. With the drafter on its own box, it was 4 to 12 times slower than the big model alone. Inside the big model's own box, EAGLE-3 made it 1.8 times faster: 162.2 tokens a second against 89.8 (`bench/results_spec_modal.md`). The test cost $64.57 across three Modal accounts.

## How Kiro shaped it

I used Kiro for the whole build, and the parts mattered in different ways.

**Specs** gave the cache and the safety code real rules. Requirements in the EARS style became 19 correctness properties. Hypothesis then tried to break them. Out of 39 property tests, 4 broke on the first run. One was a cache key collision between tenants. One was a credit card number that slipped past the scrubber when glued to an underscore. All four are now fixed.

**Steering** kept every agent honest. One file pins the cache cut-off at 0.97, because 0.94 served wrong answers. Another keeps the losses table in view, so no agent writes only wins.

**Hooks** run the matching test on save and block any commit that holds a key or a private host. The secret scan caught a GPU host name in an uncommitted file before it reached git.

**Kiro Crew** ran the work. A conductor split goals into items, one worker chat each. Two `kiro-cli` juniors on small boxes with no keys opened five pull requests, and a senior chat reviewed and merged them all.

The castle was the opposite: pure vibe coding. I rejected two versions by looking at screenshots until it felt right. Specs for money and safety, vibes for the look. That split worked for me.

## What I would tell a team

If you pay a frontier price for many small coding calls, a cache, a bank and a self-hosted model can cut that bill a lot. Put tests in front of the cheap model. If your big model is already cheap, keep it.

Most of my tests ran once. Every number has its file in the repo, so you can check me.
