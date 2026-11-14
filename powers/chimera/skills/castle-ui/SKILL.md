---
name: castle-ui
description: Work on the Chimera web page (the castle, minimap, bat agent chat, dashboard rooms). Use when editing site/ or the web server.
---

# Castle UI rules

- One URL: `127.0.0.1:8765`, started with `make web`. No second page or port.
- Animation runs 24/7 in every room. No pause button, no reduced-motion stop, no hidden-tab pause.
- Keep the 2D minimap (M opens the full map). The 3D castle (gate, guide desk, stairs, three doors) is in progress in `site/castle/`; the 2D walkable castle in `site/world/` works today.
- The chat calls `POST /api/chat` and shows each SSE step. The contract is `docs/api.md`; the backend owns it. Ignore unknown fields. Never invent a step.
- Every number on the site links to a `bench/*.md` source with losses next to wins.
- Check: `python3 site/build.py --check`, `tests/test_world.py`, `tests/test_hud.py`.
