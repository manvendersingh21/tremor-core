---
inclusion: fileMatch
fileMatchPattern: "site/**"
---

# UI rules

- **One URL.** The whole product is one page on `127.0.0.1:8765`, started by `make web`. No second page, port or dashboard link. The dashboard lives inside the castle (Observatory, Ledger, Ladder rooms).
- **Animation is always on.** It runs on every room 24/7. No pause button, no `prefers-reduced-motion` stop, no hidden-tab pause. Do not add one back.
- **Keep the minimap.** The castle has a 2D minimap (M for the full map). Every castle change keeps it correct.
- The castle: gate, guide desk, stairs, three doors. The 3D build is in progress (`site/castle/`, `site/vendor/` three.js); the 2D walkable castle in `site/world/` works today. WASD or arrows walk, Shift runs, E or Enter interacts, Esc leaves, click walks, a joystick on phones.
- The bat agent (Count Cuspid) chats through the real ladder and shows each step from `/api/chat` (`api.md`).
- Text on the site states measured numbers only, each linked to its `bench/*.md` source, with losses next to wins. `python3 site/build.py --check` must pass.
- Fonts and assets work offline (fallbacks exist). No network call is needed to render the page.
- Tests: `tests/test_world.py`, `tests/test_hud.py`.
