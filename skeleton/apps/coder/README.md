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

## A class: the first student pays, the rest get the cache

```bash
.venv/bin/python -m skeleton.apps.coder class                 # offline, stub models
.venv/bin/python -m skeleton.apps.coder class --live          # the 30B, the 763B, Supabase
```

A class asks the same things: the same assignment line, and "summarize this paper" about the same paper. `classroom.py` holds a tiny demo set: 3 assignments with starter files and tests, a sample paper (`classroom/paper.md`) and a chapter (`classroom/chapter.md`), all invented for the demo. Student 1 gets a model answer. Students 2..N get the cached answer, with 0 tokens and the $ saved shown. A patch is cached only after the assignment tests pass, and the tests run again on each cached patch. A summary is cached only when it is short and every number in it is in the text. "... without slicing" or "in 3 bullet points" is a new question: the guard keeps it from getting the cached answer.

Live, 150 student questions: 92.7% from the cache, 162 ms median hit, 0 wrong cache answers, 14 model calls (`skeleton/RESULTS.md`).

## How it uses the skeleton

`coder.py` makes one `Assistant(coder.toml)` and calls `ask(task, context=files, verify=tests_pass)`. `tests_pass` applies the patch to a temp copy of the repo and runs the test command there. That is the whole app. Edit parsing reuses `apps/terminal/edits.py`.

Safety: it edits only the files you name, inside `--repo`. It refuses `.env`, key files and `.git/`. Tests run in a temp copy. The repo changes only with `--apply`, and only after the tests pass.
