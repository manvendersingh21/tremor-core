---
inclusion: fileMatch
fileMatchPattern: "site/**"
---

# UI rules

- **One URL.** The whole product is one page on `127.0.0.1:8765`, started by `make web`. No second page, port or dashboard link. The dashboard lives inside the castle (Observatory, Ledger, Ladder rooms).
- **Animation is always on.** It runs on every room 24/7. No pause button, no `prefers-reduced-motion` stop, no hidden-tab pause. Do not add one back.
- **Keep the minimap.** The castle has a 2D minimap (M for the full map). Every castle change keeps it correct.
- The castle is a walk-in movie (`site/game/walk.js`): painted video clips from `scripts/gen_video.py`, a painted dolly where a clip is missing. Hold W to walk, S back, Shift runs, A/D or the mouse look, E opens gates and doors, T talks to the Count, M map, Esc leaves, a joystick on phones. The Observatory shows the Halloween dashboard (`site/dashboard/halloween.html`). The older 2D (`site/world/`) and 3D (`site/castle/`) castles are off the main path.
- The bat agent (Count Cuspid) chats through the real ladder and shows each step from `/api/chat` (`api.md`).
- Text on the site states measured numbers only, each linked to its `bench/*.md` source, with losses next to wins. `python3 site/build.py --check` must pass.
- Fonts and assets work offline (fallbacks exist). No network call is needed to render the page.
- Tests: `tests/test_castle.py`, `tests/test_world.py`, `tests/test_hud.py`.
