# Skeleton Crew: one small skeleton, two apps

The skeleton is one class: `Assistant(config).ask(prompt, context)`. Each question goes first to the shared answer cache. On a miss it goes to a self-hosted 30B. Only what the 30B cannot do goes to the 763B. An app adds two hooks, and that is all it adds:

- `knowledge(prompt) -> str`: the facts the models need (a store catalog, the files to edit).
- `verify(answer) -> bool`: the app's answer check (tests pass, prices are real). A failing answer is never cached, and the question climbs one tier.

Two apps are built on it, in separate folders:

| App | Folder | knowledge | verify |
|---|---|---|---|
| Terminal coding agent | `skeleton/apps/coder/` | the files you name | the tests pass on a temp copy |
| Food-store helper (web) | `skeleton/apps/store/` | `foods.json` as a store guide | prices and aisles exist; no "I don't know" |

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
.venv/bin/python -m skeleton.apps.coder ask "Fix add() so add(2, 3) == 5" \
    --repo path/to/repo --file calc.py --test "python -m pytest -q" --live
.venv/bin/python -m skeleton.apps.store             # store web app, demo: http://127.0.0.1:8766
.venv/bin/python -m skeleton.apps.store --live      # A6000 30B, Crusoe 763B, Supabase cache
.venv/bin/python skeleton/bench/run.py              # both apps on the same skeleton
.venv/bin/python -m pytest -q tests/test_skeleton_*.py
```

Live mode reads `CHIMERA_GPU_URL`, `CHIMERA_GPU_KEY`, `CRUSOE_API_KEY` and `CHIMERA_DB_URL` from `.env`. No key goes in a TOML.

More: `skeleton/apps/coder/README.md`, `skeleton/apps/store/README.md`.

## Results (demo, see `skeleton/RESULTS.md`)

| | Store, 200 shopper questions | Coder, 3 tasks x 2 |
|---|---|---|
| Cache hits | 181 of 200 (90.5%) | 3 of 6 (every second ask) |
| Wrong cache answers | 0 | 0 (tests re-run on each cached patch) |
| Climbs to the 763B | 7 (questions the guide cannot answer) | 1 (the 30B's patch failed its tests) |
| $ spent vs all-763B estimate | $0.0016 vs $0.0463 | $0.000052 |

These are demo numbers with stub models. No live run of these two apps yet: the A6000 was busy with another measured run. The same core, live on the A6000, cut 70.7% of 763B calls with 0 wrong cache answers (`bench/results_a6000.md`).

Limits: the store puts its whole guide in every model prompt (fine to about 200 items). A cached answer that later fails its check is skipped, but it stays in the cache. The store app runs on port 8766 because it is its own app; the Chimera site stays alone on 8765.
