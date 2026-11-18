# Skeleton Crew: one small skeleton, two apps

The skeleton is one class: `Assistant(config).ask(prompt, context)`. Each question goes first to the shared answer cache. On a miss it goes to a self-hosted 30B. Only what the 30B cannot do goes to the 763B. An app adds two hooks, and that is all it adds:

- `knowledge(prompt) -> str`: the facts the models need (a store catalog, the files to edit).
- `verify(answer) -> bool`: the app's answer check (tests pass, prices are real). A failing answer is never cached, and the question climbs one tier.

Two apps are built on it, in separate folders:

| App | Folder | knowledge | verify |
|---|---|---|---|
| Terminal coding agent | `skeleton/apps/coder/` | the files you name | the tests pass on a temp copy |
| Food-store helper (web) | `skeleton/apps/store/` | `foods.json` as a store guide | prices and aisles exist; no "I don't know" |

## Why it pays: many people ask the same thing

Students show this best. A class gets the same assignment ("Assignment 3: write is_palindrome(s) in palindrome.py") and the same reading ("Summarize this paper"). The first student pays for a model call. Every student after gets the checked, cached answer in about 0.16 s, for $0. Live, 150 student questions needed 14 model calls: 92.7% came from the cache, with 0 wrong cache answers (`skeleton/RESULTS.md`). Shoppers in a store are the same: 86.0% of 200 came from the cache.

Only checked answers are served from the cache. A patch is cached after its tests pass. A summary is cached only when it is short and uses only numbers from the text. Reworded questions reach a cached answer only through the cache's own rules: the same words once "please", case and punctuation are dropped, or cosine >= 0.97 that the guard passes. A question with "without", or with a new number, is a new question.

## What is in the skeleton

| Part | Job |
|---|---|
| `core/assistant.py` | `Config` (the TOML), `Assistant.ask`, the climb on a failed check, `stats()` |
| `core/demo.py` | demo mode: the cache table in memory, a word-bag embedder, stub models |
| `packages/chimera-core/` (not changed) | `SpeculativeCascadeRouter.generate()`: Supabase cache (exact hash, then cosine 0.97 with the guard), then `TierPool` with the confidence gate, standard telemetry |

`ask()` returns a dict: `answer`, `tier`, `model`, `tokens`, `tokens_saved`, `dollars`, `dollars_saved`, `cache_hit`, `latency_ms`, `verified`, `tried` (tiers called, so a climb shows), `steps`.

How a question flows:

```
ask(q) -> cache (exact, then cosine 0.97) -> hit: done, 0 tokens
                                          -> miss: 30B -> verify? -> pass: cache it, done
                                                                  -> fail: 763B -> verify -> done
```

The cache key is the question alone. The facts and the context only pick the cache section (`namespace:hash`), so new facts never get old answers, and a long catalog does not blur the match.

## Build a new app in about 20 lines

```python
# my_app.py  (my_app.toml: namespace = "faq", ladder = ["gpu-small", "cloud-deepseek"],
#             instructions = "Answer from the FAQ below. If it does not say, reply: I don't know.")
import hashlib

from skeleton.core import Assistant

FAQ = open("faq.txt").read()


def facts(question: str) -> str:   # the knowledge hook: what the models may use
    return FAQ
facts.version = hashlib.sha256(FAQ.encode()).hexdigest()  # new FAQ text -> a fresh cache section


def check(answer: str) -> bool:    # the verify hook: a "no" climbs one tier and is never cached
    return bool(answer.strip()) and "i don't know" not in answer.lower()


bot = Assistant("my_app.toml", knowledge=facts, verify=check)
a = bot.ask("How do I reset my password?")
print(a["answer"], a["tier"], a["tokens"], a["dollars_saved"], a["cache_hit"], a["latency_ms"])
print(bot.stats())                 # questions, hit_rate, model_calls, climbs, tokens, dollars ...
```

`mode = "demo"` in the TOML (the default) needs no keys: pass `demo_models={"gpu-small": fn, "cloud-deepseek": fn}` to say what each stub tier answers. `mode = "live"` uses the `[[tiers]]` in `chimera.toml` and the keys in `.env`.

## Run the apps

```bash
make setup                                          # once
.venv/bin/python -m skeleton.apps.coder demo        # coder, offline: a climb, then cache hits
.venv/bin/python -m skeleton.apps.coder class       # a class, offline: student 1 pays, students 2..5 hit the cache
.venv/bin/python -m skeleton.apps.coder ask "Fix add() so add(2, 3) == 5" \
    --repo path/to/repo --file calc.py --test "python -m pytest -q" --live
.venv/bin/python -m skeleton.apps.store             # store web app, demo: http://127.0.0.1:8766
.venv/bin/python -m skeleton.apps.store --live      # A6000 30B, Crusoe 763B, Supabase cache
.venv/bin/python skeleton/bench/run.py              # both apps on the same skeleton
.venv/bin/python -m pytest -q tests/test_skeleton_*.py
```

Live mode reads `CHIMERA_GPU_URL`, `CHIMERA_GPU_KEY`, `CRUSOE_API_KEY` and `CHIMERA_DB_URL` from `.env`. No key goes in a TOML.

More: `skeleton/apps/coder/README.md`, `skeleton/apps/store/README.md`.

## Results (one live run, see `skeleton/RESULTS.md`)

Live: the 30B on our A6000 GPU, the Crusoe 763B, the Supabase cache.

| | Class, 150 student questions | Store, 200 shopper questions | Coder, 3 tasks x 2 |
|---|---|---|---|
| From the cache | **139 (92.7%)** | **172 (86.0%)** | 3 of 6 (every second ask) |
| Wrong cache answers | 0 | 0 | 0 (tests re-run on each cached patch) |
| Model calls (climbs to the 763B) | 14 (3) | 38 (10) | 3 (0) |
| Cache hit, median | 162 ms | 122 ms | 165-283 ms |
| $ spent vs all-763B estimate | $0.0007 vs $0.0263 | $0.0031 vs $0.0488 | $0 (the 30B fixed all 3) |

What failed: paraphrases rarely reached a cached answer at cosine 0.97 (4 of 39 store rewordings). Questions the store guide cannot answer pay the 30B and the 763B every time. One summary check wrongly rejected a numbered list; that is fixed after the run. It was a single run with no repeats. The demo numbers (stub models, CI) are in `skeleton/RESULTS.md` too.

Limits: the store puts its whole guide in every model prompt (fine to about 200 items). A cached answer that later fails its check is skipped, but it stays in the cache. The store app runs on port 8766 because it is its own app; the Chimera site stays alone on 8765.
