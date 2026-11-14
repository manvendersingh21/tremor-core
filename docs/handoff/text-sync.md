# Handoff: text sync with measured results

## Done
- Commit `1824da8` on `dev`: `README.md` (results, architecture table, roadmap), `docs/architecture.md` (pool, Spec+, gateway, shared cache, guard, Modal, Android), `site/rooms.js` and `site/index.html` (posters, rebuilt with `python3 site/build.py`), HUD text-only changes in `apps/phantom-phone/hud-web/index.html` (five text nodes), `.kiro/steering/*.md`, `.kiro/specs/chimera-speculative-os/*.md` (tasks ticked only with evidence files).
- Sources used: `bench/results.md`, `results_gpu.md`, `results_ladder.md`, `spec_results.md`, `results_specplus.md`, `results_modal.md`, `results_research_*.md`, `docs/vector-store.md`.
- 86 tests passed before the commit. No background jobs, tunnels or Modal apps were started by this item.

## Half done (next step)
- `bench/results_suite.md` did not exist at the last check. When it lands, add its numbers to `README.md` (Results), `.kiro/steering/product.md` (table) and tick task 24 in `.kiro/specs/chimera-speculative-os/tasks.md`.
- `bench/results_modal.md` is still the old "never served a request" version. When the gpt-oss-120b H200 numbers arrive, update the Modal sections in `README.md`, `docs/architecture.md`, `.kiro/steering/tech.md`, `site/rooms.js` ("The Castle's H200" poster), `apps/phantom-phone/hud-web/index.html` (Tier II text), and task 22.
- `bench/results_cache_eval.json` exists with no `.md` yet. Add its numbers once a report is written.
- `bench/spec_results.md` and `bench/results_ladder.md` still hold SSH details in their rerun sections (host, port, key path). They are other workers' files, not edited here. Remove those lines.
- The rest of the HUD file has other workers' uncommitted edits. Only my text hunks were committed.

## Resume
```
git pull --rebase origin dev
python3 site/build.py          # after editing site/rooms.js
python3 site/build.py --check
.venv/bin/python -m pytest -q tests
gh run list --branch dev --limit 2
```
