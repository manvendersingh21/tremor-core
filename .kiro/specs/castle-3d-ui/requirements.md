# Requirements: castle UI (one URL)

Scope: the one web page on `127.0.0.1:8765` (`make web`). Today: a walkable 2D castle (`site/world/`), dashboard blocks (`site/dashboard.js`), posters (`site/rooms.js`). In progress: a 3D castle (`site/castle/layout.json`, `physics.js`, `site/vendor/three.module.min.js`) with a gate, a guide desk, stairs, three doors and a 2D minimap. API: `docs/api.md`. Rules: `.kiro/steering/ui.md`.

## Requirements

### R1 One URL
1. THE product SHALL be served by one server on 127.0.0.1:8765 started by `make web`.
2. THE dashboard SHALL appear inside the castle (Observatory, Ledger, Ladder), not on a second page.

### R2 Walking
1. WHEN the visitor presses WASD or arrows, THE castle SHALL move the player. Shift SHALL run. E or Enter SHALL interact. Esc SHALL leave a room. A click SHALL walk to the point. A joystick SHALL show on touch screens.
2. THE player SHALL NOT leave the walkable area or pass through walls, and SHALL climb stairs between levels.

### R3 3D layout (in progress)
1. THE 3D castle SHALL have a gate, a guide desk, stairs and three doors.
2. THE layout SHALL come from `site/castle/layout.json`, shared by rendering and physics.

### R4 Minimap
1. THE page SHALL show a 2D minimap with the player position at all times. M SHALL open the full map.

### R5 Animation always on
1. ANIMATION SHALL run on every room at all times.
2. THE page SHALL NOT have a pause button, a reduced-motion stop or a hidden-tab pause.

### R6 Bat agent chat
1. THE chat SHALL POST to `/api/chat` and show each SSE step (`embed`, `cache_shared`, `memory`, `decide`, `call`, `draft`, `final`, `answer`).
2. THE page SHALL show a 429 or 503 with its `Retry-After`.

### R7 Honest text
1. EVERY number on the site SHALL link to a `bench/*.md` or doc source, with losses next to wins. `python3 site/build.py --check` SHALL pass.

### R8 Works offline
1. THE page SHALL render without network (font fallbacks).
