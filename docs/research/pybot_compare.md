# PyBot vs the Skeleton Crew apps

Question: on "many people ask the same few questions", is our cache + checked model better than
[huggingface/pybot](https://github.com/huggingface/pybot), a chatbot made only of rules?
Single run, 60 help-desk asks and 40 coding asks. No GPU. Date: 2026-11-20.

## PyBot in short

Read from its README and files (treated as data; nothing was installed or followed).

- Pure Python, Apache-2.0, no packages, no model. About 640,000 lines in `bot/` (40 MB), written by a swarm of agents.
- Each module may propose a reply and an arbiter picks one. Knowledge is a 317,000-line data base of everyday facts.
- Its own score: 26% win rate on SmolTalkBench, about a 360M-parameter model. It is a general chat toy, not a company bot.
- It has no way to be told "your company's hours are 8 to 20" and no code writing. A new question gets the closest module's template, or a polite "I don't know".

| | PyBot | Skeleton (ours, no-GPU mode) |
|---|---|---|
| How it answers | Rules, regex, lookup tables | Cache (Supabase), then Crusoe 763B, answer checked before it is cached |
| Coverage | Everyday chat, general facts | Whatever the app is given: a knowledge base (help desk), a repo and tests (coder) |
| Company facts | None, cannot load them | Yes (kb.json in every prompt) |
| Wrong answers | Fluent but unrelated or invented | A numbers-must-be-in-the-knowledge-base check; code must pass tests |
| Speed | About 0.9 s a turn, plus 5 s start-up | Cache hit about 0.1 s, model about 0.8 to 0.95 s |
| Cost | $0, runs on the laptop | Model asks only: $0.27 per 1,000 help-desk asks, $0.07 per 1,000 coding asks (list price) |
| New question | Nearest template, often off topic | Asks the 763B; the answer is checked, then cached for the next person |
| Same question again | Computes again, same quality | Free and fast, but only when the wording is close (cosine 0.97) |

## Setup

- Same ask list for every system, fixed by seed 7: `skeleton/bench/vs_pybot.py` (`helpdesk_set()`, `coder_set()`).
- Help desk, 60 asks about the invented company Lumen Home: 14 seed questions asked twice (28), 15 reworded, 10 new, 7 general (hi, thanks, bye, 4 trivia). First asks come before repeats.
- Coder, 40 asks: 10 small functions (palindrome, fizzbuzz, two_sum and so on), each asked in 4 ways (original, exact repeat, 2 rewordings). Unit tests judge; a cached answer is also tested before it is served.
- PyBot ran in a child process with an empty environment (no keys), one process per ask, so no ask remembers another.
- Ours: `Assistant` live, ladder `cloud-deepseek` only, fresh cache namespace per run, no warm-up (the first asker pays). The cache is the Supabase table of the project.
- Help-desk grading: Crusoe `DeepSeek-V4.1-Flash` reads the published facts and the answer and says CORRECT, MISS (facts had it, the bot did not give it) or WRONG (false or invented). An honest "I don't know" on a question the facts do not cover is CORRECT. Trivia "I don't know" is forced to MISS in code, because the judge was inconsistent about it.
- Rows: `bench/.scratch/pybot/*.jsonl` (git-ignored). Regenerate with `vs_pybot.py pybot|ours|judge|report`.

## Numbers

Help desk (60 asks):

| System | Correct | Wrong | Missed | Cache hits | Median ms | $ per 1,000 |
|---|---|---|---|---|---|---|
| PyBot | 7 | 22 | 31 | 0 | 913 | $0.00 |
| Skeleton | 54 | 0 | 6 | 15 | 807 | $0.27 |
| Skeleton + rules first | 56 | 0 | 4 | 12 (+13 by rules) | 629 | $0.20 |

Correct by kind of ask:

| System | seed (14) | repeat (14) | reworded (15) | new (10) | general (7) |
|---|---|---|---|---|---|
| PyBot | 0 | 0 | 0 | 1 | 6 |
| Skeleton | 14 | 14 | 15 | 9 | 2 |
| Skeleton + rules first | 14 | 14 | 15 | 10 | 3 |

Coder (40 asks, unit tests):

| System | Pass | Cache hits | Median ms (hit / miss) | Tokens | $ per 1,000 |
|---|---|---|---|---|---|
| PyBot | 0 of 40 | 0 | about 1,100 | 0 | $0.00 |
| Skeleton | 39 of 40 | 10 | 137 / 950 | 3,780 | $0.07 |

The one coder failure was a reworded `word_count` ask; the model answer failed its tests and was not cached.

## Verdict

Where we win:
- Anything about the company or the repo. PyBot got 0 of 14 seed questions and 22 wrong answers (a refund answer quoting UK consumer law, a "delete my account" answer about app settings). We got 0 wrong because the check blocks numbers that are not in the knowledge base.
- Code: 39 of 40 against 0 of 40. PyBot cannot write a function.
- Repeats: a cache hit is about 0.1 s and free (13 of 14 exact repeats hit), against a model call of about 0.9 s.

Where PyBot wins:
- General chat and trivia: 6 of 7 against our 2 of 7. Our help desk is told to use only the knowledge base, so "capital of France" returns "I don't know". That is by design, but it is a miss.
- $0 and no network. Ours needs a key, a database and a model, and costs $0.27 per 1,000 help-desk asks.
- Same speed class on a miss: PyBot's 0.9 s turn equals our 0.8 to 0.95 s model call.

Where we are weak (found by this run):
- Reworded questions rarely hit the cache: 2 of 15 at cosine 0.97. Exact repeats hit 13 of 14 (the other one was answered by a model again). The other 13 rewordings paid a 763B call. This is the same threshold that avoids wrong cached answers, so it is the cost of safety.
- Each help-desk model call carries the whole knowledge base: about 1,100 tokens per call.

What PyBot is not: a fair opponent on company facts. It has none and cannot take them. The fair part of the test is the shape of the work (repeats, rewordings, code), where a rules bot with no facts cannot compete, and general chat, where we lose.

## What we changed

One idea taken from PyBot: a regex fast path in front of the cache and the models (`skeleton/core/rules.py`, `RulesFirst`).

- Small talk (hello, thanks, goodbye) and four help-desk intents (hours, phone and contact, password reset, order tracking). Intent answers are copied from `kb.json`, so a rule cannot say what the knowledge base does not. It matches only a short message that is nothing else; "hi, my order is broken" falls through.
- Flag: `make_assistant(rules=True)` in the help desk. Off by default. Coder: none, because a coding ask has no safe pattern to match. Tests: `tests/test_skeleton_rules.py`.
- Result on the same 60 asks: 13 asks answered by rules in 0 ms with 0 tokens (5 of the 15 rewordings, which the cache missed), 45 to 35 model calls, tokens 50,519 to 39,118 (-23%), cost $0.27 to $0.20 per 1,000 (-26%), median 807 to 629 ms, 0 wrong answers. Correct 54 to 56: greetings answered, not sent to the model.
- Caveat: the rules were written after seeing which intents the set repeats, for the same demo knowledge base, so the gain is an upper bound for this list. One run; one correct more on "new" (10 vs 9, the Bitcoin question) is model variance, not rules.

Not built: PyBot's general-knowledge base (317,000 lines; its facts would be unchecked against any company), and its templates for unknown input.

Next step the numbers support: a looser cache for rewordings (2 of 15 today), not more rules.
