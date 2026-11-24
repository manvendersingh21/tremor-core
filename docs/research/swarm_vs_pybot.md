# Swarm (PR #11) vs PyBot, the old skeleton and the 763B alone

Independent test. The tester did not build the swarm and did not fix it. Single run per system, 2026-11-24, no GPU.

**Verdict: FAIL. On asks the swarm's author never saw, it costs the same as the old skeleton's Crusoe ladder, answers 6 fewer rewordings, and served one wrong answer ("How do I reset my router?" got the password-reset steps).**

## Setup

- Swarm: PR #11 head `c385281` (`skeleton/core/swarm.py` over `Assistant`: rules, KB lookup at $0, Supabase cache, then crusoe-small, cloud-top, cloud-deepseek). Old skeleton: dev at `8c76603`. Each version was taken with `git archive` into its own folder.
- Systems, same asks:
  1. PyBot as in `pybot_compare.md` (child process, empty environment, $0).
  2. Old skeleton with rules first: (a) the 763B only; (b) the same Crusoe ladder as the swarm.
  3. The 763B alone: every ask straight to `DeepSeek-V4.1-Flash` with the KB, no cache, no rules, no check.
  4. The swarm.
- Asks (180 per system):
  - Help desk 60: `helpdesk_set()` from `skeleton/bench/vs_pybot.py`, seed 7.
  - Blind help desk 60, written from `skeleton/apps/helpdesk/kb.json` only, before the tester read any swarm code: 30 rewordings of KB facts, 10 questions the KB does not cover, 10 small-talk lines with extra words, 10 near-misses that share words with an FAQ entry. sha256 of the set: `49016f2e216c6d8e40763081c61cc81f7570050f2560b4604a48cc71cd7fb88c` (the file is not committed; the blind questions stay out of the swarm author's reach).
  - Blind store 20, written from `skeleton/apps/store/foods.json`.
  - Coder 40: `coder_set()`, judged by unit tests.
- Judge for help desk and store: `google/gemma-4-31b-it`, not part of the swarm, with the rubric of `pybot_compare.md` (CORRECT, MISS, WRONG; an honest "I don't know" on a question the KB does not cover is CORRECT; small talk or trivia answered "I don't know" is a MISS in code). The judge is noisy, so the tester read every WRONG and every swarm MISS (below).
- Live setup: Supabase app role, a fresh cache namespace for every system, set and run; N+1 memory off; scratch config copied from `chimera.example.toml`. Crusoe spend for the task about $0.20 for the systems plus about $0.12 for the judge, under the $2 cap. No HTTP 429 reached a climb in any run.
- Harness: `bench/run_swarm_vs_pybot.py` (imports the helpers of `vs_pybot.py`, which is unchanged).

## Results

Help desk 60 (the author's set):

| System | Right | Wrong | Miss | $0 answers | Cache hits | 763B calls | $ per 1,000 | Median ms | Climb reasons |
|---|---|---|---|---|---|---|---|---|---|
| PyBot | 7 | 36 | 17 | 60 | 0 | 0 | $0.00 | 934 | - |
| Old (a) 763B only | 55 | 0 | 5 | 25 | 12 | 35 | $0.20 | 638 | none |
| Old (b) Crusoe ladder | 55 | 0 | 5 | 25 | 12 | 10 | $0.12 | 512 | low confidence 21, failed check 10 |
| 763B alone | 54 | 0 | 6 | 0 | 0 | 60 | $0.35 | 665 | - |
| Swarm | 53 | 0 | 7 | 39 | 1 | 11 | $0.10 | 0 | low confidence 15, failed check 11 |

Blind help desk 60:

| System | Right | Wrong | Miss | $0 answers | Cache hits | 763B calls | $ per 1,000 | Median ms | Climb reasons |
|---|---|---|---|---|---|---|---|---|---|
| PyBot | 14 | 37 | 9 | 60 | 0 | 0 | $0.00 | 963 | - |
| Old (a) | 54 | 0 | 6 | 1 | 0 | 59 | $0.34 | 753 | none |
| Old (b) | 55 | 1 | 4 | 1 | 0 | 26 | $0.26 | 1297 | low confidence 45, failed check 26 |
| 763B alone | 55 | 0 | 5 | 0 | 0 | 60 | $0.35 | 621 | - |
| Swarm | 49 | 1 | 10 | 7 | 0 | 28 | $0.26 | 1253 | low confidence 37, failed check 28 |

Blind store 20:

| System | Right | Wrong | Miss | $0 answers | 763B calls | $ per 1,000 | Median ms |
|---|---|---|---|---|---|---|---|
| PyBot | 2 | 7 | 11 | 20 | 0 | $0.00 | 1000 |
| Old (a) | 17 | 1 | 2 | 0 | 20 | $0.32 | 769 |
| Old (b) | 16 | 3 | 1 | 0 | 3 | $0.16 | 972 |
| 763B alone | 17 | 0 | 3 | 0 | 20 | $0.32 | 610 |
| Swarm | 16 | 1 | 3 | 3 | 6 | $0.20 | 993 |

Coder 40 (unit tests):

| System | Pass | Cache hits | 763B calls | $ per 1,000 | Median ms |
|---|---|---|---|---|---|
| PyBot | 0 | 0 | 0 | $0.00 | 1118 |
| Old (a) | 39 | 9 | 31 | $0.07 | 792 |
| Old (b) | 40 | 9 | 0 | $0.01 | 653 |
| 763B alone | 39 | 0 | 40 | $0.09 | 725 |
| Swarm | 40 | 9 | 0 | $0.01 | 687 |

All four sets together (180 asks), 763B calls and $ per 1,000: old (a) 145 and $0.233; old (b) 39 and $0.148; 763B alone 180 and $0.290; swarm 45 and $0.146.

Right answers by kind of ask (right / asked; "at $0" = right and cost nothing):

| Kind | PyBot | Old (a) | Old (b) | 763B alone | Swarm | Swarm at $0 |
|---|---|---|---|---|---|---|
| 60-set seed (14) | 0 | 14 | 14 | 14 | 14 | 13 |
| 60-set repeat (14) | 0 | 14 | 14 | 14 | 14 | 14 |
| 60-set reworded (15) | 0 | 15 | 15 | 15 | 14 | 9 |
| 60-set new (10) | 1 | 9 | 9 | 9 | 8 | 0 |
| 60-set general (7) | 6 | 3 | 3 | 2 | 3 | 3 |
| Blind reworded (30) | 0 | 30 | 30 | 29 | 24 | 0 |
| Blind not in KB (10) | 4 | 9 | 9 | 9 | 9 | 0 |
| Blind small talk (10) | 9 | 5 | 7 | 7 | 7 | 7 |
| Blind near-miss (10) | 1 | 10 | 9 | 10 | 9 | 0 |

## Bar for the swarm

| Line | Result | Evidence |
|---|---|---|
| 0 wrong answers served, every set | **FAIL** | Blind help desk `n01` "How do I reset my router?" was answered by crusoe-small with the password-reset steps and served (the old ladder (b) did the same). The judge also marked store `t20` "Is the store open at 10 pm?" WRONG ("No, the store closes at 22:00"); the tester reads that as defensible, so it is not counted. Help desk 60: 0. Coder: 0. |
| Help desk right >= 56/60 | **FAIL** | 53/60. Old (b) 55, 763B alone 54. |
| Fewer 763B calls and fewer $ per 1,000 than old (b) | **FAIL** | Help desk 60: 11 calls vs 10 (more), $0.10 vs $0.12 (less). Blind help desk: 28 vs 26 calls, $0.263 vs $0.264. All sets: 45 vs 39 calls, $0.146 vs $0.148. Both parts must hold. |
| Rewordings in the 60-set answered right at $0 > 2/15 | **PASS** | 9 of 15. On the 30 blind rewordings: 0 at $0. |

## Every WRONG and every swarm MISS, read by hand

Wrong, swarm:

- Blind `n01`, near-miss, crusoe-small: "How do I reset my router?" -> "Go to the sign-in page and click Forgot password. Enter your account email..." The KB line is the password-reset FAQ. A real wrong answer. It passes the number and word-overlap check because the question shares "reset" with the FAQ entry.
- Store `t20` "Is the store open at 10 pm?" -> "No, the store closes at 22:00." The KB says close 22:00. Judge WRONG, tester says defensible.

Swarm MISS, 60-set (the swarm served "I don't know. A support agent will reply by email."):

| Ask | KB | Reading |
|---|---|---|
| h23, h25, h27, h28 (egg, France, Romeo and Juliet, sky) | none | Right refusals (a help desk is told to use only the KB). The judge scores trivia refusals as MISS by rule. |
| h14 "Can I pay with Bitcoin?" | "Visa, Mastercard, American Express, PayPal and gift cards." | Defensible refusal; a "no, we take X" is better. Every system scored MISS. |
| h00 "Can I return an item I already used?" | "Unused items can be returned within 30 days of delivery." | Arguable. The old systems answered it; the swarm refused. |
| h49 "How long do refunds take?" | "...within 5 to 7 business days after the item reaches our warehouse." | Real miss. |

Swarm MISS, blind help desk:

| Ask | KB | Reading |
|---|---|---|
| u02 "Can I pay with Bitcoin?" | payment list | Defensible refusal (as h14). |
| b07 "My package hasn't shown up, how can I follow it?" | "Open Orders and click Track..." | Real miss. |
| b09 "I ordered by mistake, can I call it off?" | cancel-order FAQ | Real miss. |
| b11 "I want to stop my monthly plan, how?" | cancel-subscription FAQ | Real miss. |
| b14 "Can I pay with PayPal?" | payment list | Real miss. |
| b15 "What cards do you take at checkout?" | payment list | Real miss. |
| b19 "Is delivery free?" | "Standard shipping is free on orders over $50..." | Real miss. |
| s04 "thank you so much, you've been great", s05 "hey, how are you?", s10 "hi, is anyone there?" | none needed | Real misses: a polite reply was expected and the rule did not match. |

Swarm MISS, store: `t01` dairy-free milks (real miss), `t11` salmon price (real miss; Tuesday's special differs from the regular price, but a refusal is still a miss), `t13` "Can I return opened items?" (KB: unopened items within 14 days; defensible refusal, every store system scored MISS).

Count: of 7 + 10 + 3 = 20 swarm MISS, 6 are right or defensible refusals (h23, h25, h27, h28, h14, u02) plus 2 arguable (h00, t13); 12 are real misses (h49, b07, b09, b11, b14, b15, b19, s04, s05, s10, t01, t11).

The old systems and the 763B alone also have MISS rows: mostly the same trivia and Bitcoin refusals and small talk answered "I don't know". Their WRONG rows (read by hand): old (b) `n01` (same router answer from crusoe-small); old (a) store `t11` and old (b) store `t11` "Salmon fillet is aisle 4, $7.49" (regular price, Tuesday special is $5.99: ambiguous, not a clear error); old (b) store `t15` "Which items are vegan?" lists quinoa, gluten-free pasta and dark chocolate, which the guide does not tag vegan (a real wrong); old (b) store `t20` (same as the swarm's, defensible).

## Where each system loses

- **PyBot:** wrong or off-topic on company questions (0 of 14 seed asks right, 36 of 60 wrong), 0 of 40 coder asks. It beats the swarm on trivia (6/7 vs 3/7) and on blind small talk (9/10 vs 7/10), at $0.
- **Old (a), 763B only:** the most expensive of the skeleton variants: 35 calls to the 763B on the 60-set, $0.20 per 1,000.
- **Old (b), Crusoe ladder:** the small tier answers fluently when it should not: `n01` (router) and store `t15`. Its check is numbers only. On blind rewordings it is right 30/30 where the swarm is 24/30.
- **763B alone:** costs $0.35 per 1,000 on the help desk, no cache, no free answers, and answers "I don't know" to greetings. It was right on 29 of 30 blind rewordings.
- **Swarm:** serves 39 of 60 help-desk asks at $0 and cuts the 60-set to $0.10 per 1,000, the lowest of all. But its stronger check refuses answers that are right (12 real misses, 6 of them blind rewordings of FAQ facts), the KB lookup answered none of the 30 blind rewordings, the small-talk rule missed 3 of 10 blind lines, and one wrong answer still got through. Its 60-set gain rests on asks the author had seen (rules and lookup answered 38 of 60 for free; on the 60 blind asks, 7).

## Limits

- One run per system. The judge is noisy: old (b) store scored 18/20 in a first run and 16/20 in the rerun on the same asks (the first rows were replaced because they did not capture climb reasons).
- Climb reasons: `low_confidence` and HTTP codes come from the pool's `climb_reason`; "failed check" counts asks that took a second step in the Assistant loop. A cache or free answer has no reason.
- The store set has 20 asks and the specials depend on the weekday of the run (Tuesday). The blind asks were written once; their expected facts were not tuned to any system.
- Supabase rows under the test namespaces were left in place (they belong to this project's cache table and are isolated by namespace).
