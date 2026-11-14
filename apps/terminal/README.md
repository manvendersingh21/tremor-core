# `chimera code`: terminal coding agent on the cascade

An Aider-style coding agent for the terminal. Every model call goes through
`SpeculativeCascadeRouter.generate()`, so easy edits are answered by the cache or the
self-hosted 30B, and only steps whose tests fail climb to the 763B.

## Install

Nothing extra. It uses the repo venv (`make setup`) and the stdlib (no TUI library).

```
bin/chimera code                    # REPL in the current directory
python -m apps.terminal --cwd path  # same thing
```

Settings come from `chimera.toml` (`[[tiers]]`, `[cache]`, `[telemetry]`). Keys come from `.env`.
`CHIMERA_GPU_URL` (or `--gpu-url`) points the `gpu-small` tier at your tunnel's local port.

## Usage

```
bin/chimera code app.py tests/test_app.py           # REPL with two files in context
bin/chimera code -m "add a fizzbuzz function with tests" --yes
echo "fix the failing test" | bin/chimera code --test-first --yes stack.py
printf '/add a.py\n/tier cloud\nrename f to g\n/cost\n' | bin/chimera code --yes   # a script of lines
```

| flag | meaning |
|---|---|
| `-m TEXT` | one request, then exit (exit code 1 when tests still fail) |
| `--yes` | apply edits without asking; risk >= 70 still needs the typed token |
| `--tier auto\|local\|gpu\|cloud` | start tier; `local` and `gpu` are both the 30B |
| `--test-cmd CMD` / `--no-test` | the check after each edit (default: `pytest -q` when tests exist) |
| `--test-first` | run the tests first and send the failure with the request |
| `--max-repairs N` | repair rounds after a failed check (default 3) |
| `--no-cache` | skip the Supabase cache |
| `--stats-json FILE` | per-call numbers of this run |

## Slash commands

| command | does |
|---|---|
| `/add <file>...` | add files to the context |
| `/drop [file]` | drop one file, or all |
| `/files` | list context files |
| `/diff` | `git diff` |
| `/undo` | undo the last write (new files are removed) |
| `/run <cmd>` | run a shell command (risk-scored) |
| `/test` | run the test command |
| `/fix` | run tests and ask for a fix |
| `/tier auto\|local\|gpu\|cloud` | choose the tier |
| `/cost` | session totals per tier and $ saved against an all-763B baseline |
| `/commit [msg]` | `git add -u && git commit`; never pushes |
| `/clear`, `/help`, `/exit` | |

## How a turn works

1. The prompt is: edit-format rules, a repo map (file names and top-level symbols, at most 500 chars),
   the context files (secrets redacted), the last test failure if any, and the request.
2. `router.generate()` looks the prompt up in the Supabase cache (exact hash, then cosine >= 0.97 with the
   guard). The cache namespace includes a hash of each context file's path and content. A request with no
   files can reuse a cached answer. A request on changed file text never gets a stale one.
3. On a miss, the tier pool calls the 30B (`gpu-small`, Ollama `qwen3:30b-instruct`).
4. The reply's SEARCH/REPLACE or `FILE: ... END FILE` blocks are parsed and shown as a colored diff.
   You answer `[y]es/[n]o/[a]lways`.
5. The test command runs. On failure the output goes back to the model, at most 3 times. In `auto`
   each failed round starts the next call one tier up (30B, then 763B).
6. One status line per call:

```
-> gpu (qwen3:30b-instruct) · 369 tok · $0 · 46.9 s · supabase MISS cos - · kept 369 tok off the big model
```

There is no answer cache on the Mac. The router's SQLite caches are replaced by a no-op in this app.

## Safety

- Every shell command (`/run`, `/test`, the repair loop) and every file write is scored by
  `firewall/risk_scorer.py`. A write outside the working directory is scored at least 70.
  A score of 70 or more needs the one-time token typed in, even with `--yes`.
- `.env`, `id_rsa*`, `*.pem`, `*.key`, `credentials*`, and anything under `.ssh`, `.aws`, `.gnupg`
  are never read or written. `.env.example` is allowed.
- Text sent to a model is redacted: private keys, `sk-`/`ghp_`-style tokens, bearer tokens, DSN
  passwords, `*_KEY=`/`*_TOKEN=` values, and any secret value found in the environment.
- Child processes get an environment without `*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*` variables.
- `.gitignore` is respected for `/add` and the repo map.

## Telemetry

Each call writes the router's normal row to the telemetry JSONL (`CHIMERA_TELEMETRY` or
`[telemetry] path`), so terminal sessions appear in the web Observatory.

## Tests

`.venv/bin/python -m pytest -q tests/test_terminal.py` (fake router, no models).
Live results: `bench/results_terminal_agent.md`.
