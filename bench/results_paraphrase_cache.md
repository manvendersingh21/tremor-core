# Paraphrase cache: normalize, a cosine band, the guard and a 30B yes/no check

Date: 2026-11-16. Single run, no repeats. Code: `packages/chimera-core/cache/band.py`, `pgvector_cache.py` (`_choose`). Runner: `bench/run_paraphrase_cache.py`.

Setup: each pair stores `old` with its answer in a fresh cache, then looks up `new` through the real `PgVectorCache` code. An in-memory store stands in for Supabase, so the DB round trip (about 121 ms, `docs/vector-store.md`) is the same for every setting and is left out of the times. Embedder: all-MiniLM-L6-v2. Checker: the self-hosted 30B (`gpu-small`, qwen3:30b-instruct on the tuned V100, over an SSH tunnel to your GPU box), at most one check per lookup, max 3 output tokens, temperature 0. No Modal, no paid API.

Data: `bench/paraphrase_pairs.jsonl` (46 hand-made pairs: 20 paraphrases, 24 tricky non-matches, 2 with a wrong stored answer) and 500 Quora pairs from `bench/datasets/cache_eval.jsonl` (180 duplicates). A hit on a non-matching pair is a wrong hit: the cache would serve the wrong answer. QQP labels are noisy, so some QQP 'wrong hits' may be fine and some 'duplicates' would not share an answer.

## Verdict

- The France pair ('What is the capital of France?' then 'Tell me the capital of France'): hits in settings C, D, E, F; raw cosine is 0.955, under 0.97. Normalized, both prompts are 'capital of france'.
- Tricky non-matches served (of 24): A 2, B 0, C 0, D 0, E 0, F 0. The guard (cache/guard.py) changed during this run. Two rules are stricter: entities in another order ('Celsius to Fahrenheit' vs 'Fahrenheit to Celsius', t10) and 'non-' as negation ('romantic' vs 'non-romantic', a QQP pair); before them, setting B served t10 and that QQP pair (first run of this file). Two fixes only stop false rejects: a possessive 's ('Japan's', h20) and the pronoun 'I' (h19) are no longer read as entities the other prompt lacks.
- QQP: the band without the 30B (D) served 17 pairs against their label; the 30B check (E) cut that to 5:
  - q67 (0.945): 'How do you get to know if a guy is really interested in you during gym?' -> 'How can I know if a guy at the gym is interested in me?': same question (label noise)
  - q104 (0.959): 'How do I pull out a pencil under a wardrobe cabinet / cupboard (almirah)?' -> 'How do I pull out pencil under the almirah/ wardrobe / cabinet?': same question (label noise)
  - q145 (0.904): 'What is the significance of technology in event management and decoration?' -> 'What is the significance of technology in event management?': B is narrower than A; A's answer covers B (borderline)
  - q276 (0.899): 'How can this matrix be written in [math]\LaTeX[/math]?' -> 'How do you write a matrix in LaTeX?': same question (label noise)
  - q360 (0.955): 'What are the best places to meet single men in San Francisco?' -> 'Which are some good ways to meet single men in San Francisco?': places vs ways: really different
- Failures, said plainly: the band with the 30B check is NOT at 0 wrong hits on QQP (above). A wrong stored answer is served when the prompts are equal after normalizing (w02, score 1.0): only band candidates are checked, as with an exact-hash hit. The 30B check costs about half a second per band candidate and needs the GPU tunnel; on an error or a timeout the lookup is a miss. Recall stays low on paraphrases with other words (h13 'largest' vs 'biggest one', h18 'speed of light' vs 'how fast').
- Defaults: `normalize = true` (it added no wrong hit in any set). The band stays off (`band_low = 0.0`) because it is not shown safe on QQP; turn it on with `band_low = 0.88` and `band_check = "gpu-small"`. The checker uses the stricter of two prompt wordings: the first one said YES to 'raw chicken' vs 'cooked chicken' (t24) when asked without the cosine and guard (side run, `bench/.scratch/paraphrase/prompt_ab.py`).

## Hand-made pairs (paraphrases + tricky non-matches)

| Setting | Hits | Correct hits | Wrong hits | Recall | Lookup p50 / p90 (ms) | 30B checks |
|---|---|---|---|---|---|---|
| A. cosine >= 0.97 only (no guard) | 7 | 5 | 2 | 25.0% | 0.1 / 0.2 | 0 |
| B. cosine >= 0.97 + guard (the product until now, guard with the 2 new rules) | 5 | 5 | 0 | 25.0% | 0.1 / 0.2 | 0 |
| C. normalize + 0.97 + guard | 10 | 10 | 0 | 50.0% | 0.4 / 11.3 | 0 |
| D. normalize + band 0.88-0.97 + guard | 17 | 17 | 0 | 85.0% | 0.2 / 8.8 | 0 |
| E. normalize + band 0.88-0.97 + guard + 30B yes/no | 17 | 17 | 0 | 85.0% | 0.2 / 508.9 | 7 |
| F. normalize + band 0.85-0.97 + guard + 30B yes/no (wider band) | 17 | 17 | 0 | 85.0% | 0.2 / 508.9 | 8 |

## Quora (QQP) pairs

| Setting | Hits | Correct hits | Wrong hits | Recall | Lookup p50 / p90 (ms) | 30B checks |
|---|---|---|---|---|---|---|
| A. cosine >= 0.97 only (no guard) | 28 | 26 | 2 | 14.4% | 0.1 / 0.1 | 0 |
| B. cosine >= 0.97 + guard (the product until now, guard with the 2 new rules) | 23 | 23 | 0 | 12.8% | 0.1 / 0.2 | 0 |
| C. normalize + 0.97 + guard | 24 | 24 | 0 | 13.3% | 0.1 / 8.8 | 0 |
| D. normalize + band 0.88-0.97 + guard | 87 | 70 | 17 | 38.9% | 0.1 / 8.4 | 0 |
| E. normalize + band 0.88-0.97 + guard + 30B yes/no | 59 | 54 | 5 | 30.0% | 0.1 / 421.3 | 63 |
| F. normalize + band 0.85-0.97 + guard + 30B yes/no (wider band) | 70 | 63 | 7 | 35.0% | 0.2 / 506.4 | 85 |

## The France pair and every hand-made pair under E

| Pair | Old -> new | Should match | Best score | B hit | D hit | E hit | How (E) | 30B said |
|---|---|---|---|---|---|---|---|---|
| h01 | What is the capital of France? -> Tell me the capital of France | yes | 1.000 | - | HIT | HIT | normalized | - |
| h02 | What is the capital of France? -> capital of france | yes | 1.000 | - | HIT | HIT | normalized | - |
| h03 | What is the capital of France? -> Which city is the capital of France? | yes | 0.942 | - | HIT | HIT | band+raw | yes |
| h04 | What is the capital of France? -> Can you tell me what the capital of France is? | yes | 0.970 | - | HIT | HIT | normalized | - |
| h05 | How many days are in a leap year? -> How many days does a leap year have? | yes | 0.989 | HIT | HIT | HIT | normalized | - |
| h06 | Who wrote the novel Pride and Prejudice? -> Who is the author of Pride and Prejudice? | yes | 0.956 | - | HIT | HIT | band+normalized | yes |
| h07 | What is the chemical symbol for gold? -> Please tell me the chemical symbol of gold. | yes | 0.992 | - | HIT | HIT | normalized | - |
| h08 | What does HTTP status code 404 mean? -> What does a 404 status code in HTTP signify? | yes | 0.952 | - | HIT | HIT | band+raw | yes |
| h09 | Convert 100 degrees Celsius to Fahrenheit. -> What is 100 degrees Celsius in Fahrenheit? | yes | 0.912 | - | HIT | HIT | band+normalized | yes |
| h10 | How do I reverse a list in Python? -> How can I reverse a list in python? | yes | 0.998 | HIT | HIT | HIT | normalized | - |
| h11 | What is the boiling point of water at sea level? -> At sea level, what temperature does water boil at? | yes | 0.909 | - | HIT | HIT | band+raw | yes |
| h12 | Write a Python function that returns the sum of a list. -> Write a python function to sum a list of numbers | yes | 0.925 | - | HIT | HIT | band+normalized | yes |
| h13 | What is the largest planet in the solar system? -> Which planet is the biggest one in our solar system? | yes | 0.942 | - | - | - | - | - |
| h14 | How many continents are there? -> How many continents does Earth have? | yes | 0.891 | - | - | - | - | - |
| h15 | What is the square root of 144? -> whats the square root of 144 | yes | 1.000 | HIT | HIT | HIT | normalized | - |
| h16 | Who painted the Mona Lisa? -> Can you tell me who painted the Mona Lisa? | yes | 1.000 | HIT | HIT | HIT | normalized | - |
| h17 | What year did World War II end? -> When did World War II end? | yes | 0.970 | - | HIT | HIT | normalized | - |
| h18 | What is the speed of light? -> How fast does light travel? | yes | 0.832 | - | - | - | - | - |
| h19 | How do I check my Python version? -> how to check python version | yes | 0.981 | HIT | HIT | HIT | normalized | - |
| h20 | What is the capital of Japan? -> Tell me Japan's capital city. | yes | 0.946 | - | HIT | HIT | band+normalized | yes |
| t01 | What is the capital of France? -> What is the capital of Germany? | no | 0.663 | - | - | - | - | - |
| t02 | capital of france -> capital of germany | no | 0.537 | - | - | - | - | - |
| t03 | What is the capital of France? -> Tell me the capital of Spain | no | 0.622 | - | - | - | - | - |
| t04 | I have 2 apples and eat one. How many are left? -> I have 3 apples and eat one. How many are left? | no | 0.981 | - | - | - | - | - |
| t05 | What is 2+3? -> What is 2*3? | no | 0.803 | - | - | - | - | - |
| t06 | Is 7 a prime number? -> Is 9 a prime number? | no | 0.801 | - | - | - | - | - |
| t07 | How do I sort a list in ascending order in Python? -> How do I sort a list in descending order in Python? | no | 0.952 | - | - | - | - | - |
| t08 | Which foods are safe for dogs to eat? -> Which foods are not safe for dogs to eat? | no | 0.968 | - | - | - | - | - |
| t09 | What is the largest planet in the solar system? -> What is the smallest planet in the solar system? | no | 0.821 | - | - | - | - | - |
| t10 | Convert 100 degrees Celsius to Fahrenheit. -> Convert 100 degrees Fahrenheit to Celsius. | no | 0.993 | - | - | - | - | - |
| t11 | Who wrote the novel Pride and Prejudice? -> Who wrote the novel War and Peace? | no | 0.500 | - | - | - | - | - |
| t12 | How do I reverse a list in Python? -> How do I reverse a string in Python? | no | 0.831 | - | - | - | - | - |
| t13 | How do I get the first element of a Python list? -> How do I get the last element of a Python list? | no | 0.796 | - | - | - | - | - |
| t14 | How many days are in a leap year? -> How many days are in a normal year? | no | 0.728 | - | - | - | - | - |
| t15 | What year did World War II end? -> What year did World War I end? | no | 0.882 | - | - | - | - | - |
| t16 | What is the boiling point of water in Celsius? -> What is the freezing point of water in Celsius? | no | 0.832 | - | - | - | - | - |
| t17 | How do I install numpy with pip? -> How do I uninstall numpy with pip? | no | 0.812 | - | - | - | - | - |
| t18 | Write a Python function that returns the sum of a list. -> Write a Python function that returns the product of a list. | no | 0.737 | - | - | - | - | - |
| t19 | What is the capital of Australia? -> What is the largest city in Australia? | no | 0.779 | - | - | - | - | - |
| t20 | Can dogs eat grapes? -> Can dogs eat carrots? | no | 0.709 | - | - | - | - | - |
| t21 | How do I encode a string to base64 in Python? -> How do I decode a base64 string in Python? | no | 0.924 | - | - | - | - | - |
| t22 | What is the time complexity of binary search? -> What is the time complexity of linear search? | no | 0.806 | - | - | - | - | - |
| t23 | Who was the first president of the United States? -> Who was the second president of the United States? | no | 0.781 | - | - | - | - | - |
| t24 | Is it safe to eat raw chicken? -> Is it safe to eat cooked chicken? | no | 0.876 | - | - | - | - | - |
| w01 | What does HTTP status code 404 mean? -> What does a 404 status code in HTTP signify? | no | 0.952 | - | HIT | - | - | no |
| w02 | What is the capital of France? -> Tell me the capital of France | no | 1.000 | - | HIT | HIT | normalized | - |

## The 30B check alone on the hand-made pairs (no cosine, no guard)

| Set | Pairs | 30B said YES |
|---|---|---|
| match | 20 | 20 |
| tricky | 24 | 0 |
| bad_answer | 2 | 0 |

30B check time: p50 488 ms, p90 766 ms over 71 live checks (saved verdicts reused on a rerun keep their first time).

