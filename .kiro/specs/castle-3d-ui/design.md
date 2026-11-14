# Design: castle UI

## Layers
```
server.py (stdlib, :8765)  --/-->  site/index.html + site/world (2D today) / site/castle (3D, in progress)
        |--/api/chat (SSE)--> bat agent room
        |--/events, /api/bench, /api/evals--> dashboard.js blocks in Observatory, Ledger, Ladder
```

## Components
| Part | File |
|---|---|
| Server | `apps/phantom-phone/hud-web/server.py` |
| 2D castle, grid, A* click-to-walk | `site/world/world.js`, `grid.js`, `map.json` |
| Bat chat | `site/world/chat.js` |
| 3D layout and physics | `site/castle/layout.json`, `site/castle/physics.js` |
| Renderer | `site/vendor/three.module.min.js` (three.js) |
| Dashboard blocks | `site/dashboard.js`, `dashboard.css` |
| Posters and text | `site/rooms.js`, `site/build.py` |

## Decisions
- No framework: stdlib server and plain JS, because of limited Mac disk space.
- One layout file feeds both the 3D scene and the physics, so the minimap and the walls agree.
- Animation has no off switch by user order.

## Correctness properties
Router, cache and firewall properties belong to `.kiro/specs/chimera-speculative-os/`.

| ID | Property | Requirement |
|---|---|---|
| P1 | From spawn, every door, the guide desk and the stairs top are reachable (A* finds a path). | R2.2, R3 |
| P2 | For any move sequence, the player stays inside the walkable zones. | R2.2 |
| P3 | The minimap position equals the player position after any move. | R4 |
| P4 | The shipped source contains no pause control and no `prefers-reduced-motion` stop. | R5 |
| P5 | The SSE parser renders any event order the API allows and ignores unknown fields. | R6 |
| P6 | `site/build.py --check` passes. | R7 |

Tests: `tests/test_world.py` (map schema, A* reachability, `grid.js` via node), `tests/test_hud.py` (server routes).
