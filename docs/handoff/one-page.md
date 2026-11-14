# Handoff: one page, one port (castle site + HUD)

Goal: serve the castle site and the HUD from one server on 127.0.0.1:8765. Not finished.

## Done
- `site/dashboard.css`: HUD CSS moved here, every rule scoped under `.dash`, clashing names renamed (dstage, dflame, dwin, din, dhalo).
- `site/dashboard.js`: HUD JS moved here (SSE `/events`, per-model ledger, donut, benchmarks, evals, theme toggle). Exposes `window.Dash.enter(roomId)`.
- Commit: see `git log -- site/dashboard.js`.

## Half done (edited in the working tree, NOT committed, mixed with other workers' edits)
- `site/index.html`: links dashboard.css and dashboard.js, adds an `orn` symbol, `#dash-bar` and `.dash[data-dash=observatory|ledger|ladder]` blocks inside `#v-room`, "Nine doors" text. Rebuilt with `python3 site/build.py`.
- `site/rooms.js`: new first room `observatory` (no posters, art `room-tower`).
- `site/tour.js`: route aliases (#live, #bench, #evals, #how, bare room ids), shows the matching `.dash` block and calls `Dash.enter`.

## Not started
1. `apps/phantom-phone/hud-web/server.py`: serve `site/` at `/` and `/art/*` (safe join under site/, mime types), keep `/events`, `/api/bench`, `/api/evals`; port from `CHIMERA_PORT` or `HUD_PORT`, host from `CHIMERA_HOST` or `HUD_HOST`. Drop the `/gate-bg.webp` route.
2. `apps/phantom-phone/hud-web/index.html` -> meta-refresh redirect to `/#observatory`; `git rm gate-bg.webp`.
3. `site/dashboard.css`: check the 9 doors layout (`.doors` 3 columns) and readability on screenshots.
4. `deploy/docker-compose.yml` hud service: mount `../site`, `../bench`, hud-web; rename to `web`.
5. Makefile: `make web` (server), `make demo` (demo.py in background + server), `site` -> web.
6. Docs: README, site/README.md, hud-web/README.md, deploy/README.md (one URL, one command).
7. `tests/test_hud.py`: static `/`, `/dashboard.js`, `/art/...`, traversal 404, `/events`, `/api/bench`.
8. Screenshots on a free port (8799): `site/docs/one_page.png`, `site/docs/one_page_observatory.png` (run demo.py so data flows).
9. The Evals worker kept editing `apps/phantom-phone/hud-web/index.html`. Re-diff its Evals block against `site/dashboard.js` before replacing that file. The scratch converters were in the session scratch dir and are not saved.

## Resume
```
git status --short site apps/phantom-phone
python3 site/build.py --check
.venv/bin/python -m pytest -q tests
```
