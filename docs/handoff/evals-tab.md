# Handoff: Evals tab (one log of every benchmark run)

## Done
- `2dab63d` (dev): `bench/evallog.py` (EvalRow, importers, SQLite `~/.chimera/evals.db`, Supabase upsert, leaderboard), `bin/chimera evals import|list|leaderboard`, `/api/evals`, Evals tab, `deploy/sql/004_eval_runs.sql`, `tests/test_evallog.py`, `docs/evals.png`.
- Follow-up commit (this one): the tab split into `apps/phantom-phone/hud-web/evals.js`, `evals.css`, `evals.html` (markup fragment, also inlined in `index.html`). `server.py` serves `/evals.js` and `/evals.css`. `evals.js` exposes `window.loadEvals()`.

## Half done / open
- Supabase: `eval_runs` migration `deploy/sql/004_eval_runs.sql` is NOT applied. Upsert fails with UndefinedTable until it is. Next: apply it, then `bin/chimera evals import`. If the suite worker adds its own 004, reconcile.
- Suite rows come from `bench/.scratch/suite_*.jsonl` (POOL was still running, 18 rows). The importer prefers `bench/.scratch/eval_log.jsonl` when present. Re-run import after POOL finishes.
- Not checked: Hollowkeep theme on the tab, AA contrast by measurement.
- Merge into the castle "Ledger" room: mount `evals.html` + link `evals.css` + `evals.js`, call `loadEvals()` when the room opens. Needs only `/api/evals`.

## Resume
```
.venv/bin/python apps/kiro-trimmer/cli.py evals import
.venv/bin/python apps/kiro-trimmer/cli.py evals leaderboard
.venv/bin/python apps/phantom-phone/hud-web/server.py   # http://127.0.0.1:8765/#evals
.venv/bin/python -m pytest -q tests/test_evallog.py
```
