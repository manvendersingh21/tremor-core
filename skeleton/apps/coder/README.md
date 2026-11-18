# Coder: a terminal coding agent on the skeleton

It asks a coding task, shows each step (tier, tokens, $ spent, $ saved, tests), and the diff. A patch that fails the tests climbs from the 30B to the 763B. A patch that passed is cached, so the same task on the same files costs 0 tokens next time.

## Quickstart

```bash
make setup                                    # once: the repo venv
.venv/bin/python -m skeleton.apps.coder demo  # offline: stub models, a climb, then cache hits
# your own repo (demo stubs answer only the demo tasks; use --live for real models)
.venv/bin/python -m skeleton.apps.coder ask "Fix add() so add(2, 3) == 5" \
    --repo path/to/repo --file calc.py --test "python -m pytest -q" --live
# --live: the self-hosted 30B (CHIMERA_GPU_URL), then the 763B (CRUSOE_API_KEY), Supabase cache (CHIMERA_DB_URL)
# add --apply to write the patch once its tests pass
```

## How it uses the skeleton

`coder.py` makes one `Assistant(coder.toml)` and calls `ask(task, context=files, verify=tests_pass)`. `tests_pass` applies the patch to a temp copy of the repo and runs the test command there. That is the whole app. Edit parsing reuses `apps/terminal/edits.py`.

Safety: it edits only the files you name, inside `--repo`. It refuses `.env`, key files and `.git/`. Tests run in a temp copy. The repo changes only with `--apply`, and only after the tests pass.
