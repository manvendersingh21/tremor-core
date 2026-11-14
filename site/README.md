# CHIMERA site: the walk-in castle

One page, one port: http://127.0.0.1:8765. You are the camera. Hold W and you walk from the painted landing (moon, bats, the castle on its cliff) to the iron gates. E opens them. You walk up the lantern drive to the great door, and E opens it. Then you walk along the Great Hall. Its gold-plated doors open the rooms, each with its painting and its data. The Observatory holds the live Halloween dashboard. T talks to Count Cuspid through the real router.

The walk is a chain of painted video clips (`game/clips/`, made by `scripts/gen_video.py` with Seedance 2.0 on GMI). Each clip starts on the last frame of the clip before. A stretch whose clip is not made yet plays as a slow painted dolly over its keyframe. Costs: [art/README.md](art/README.md). Proof, screenshots and fps: [docs/one_url_gates.md](docs/one_url_gates.md).

No framework, no npm. Google Fonts is the only external request, with system fallbacks.

## Run

```
make web       # http://127.0.0.1:8765  (CHIMERA_PORT to change)
make demo      # the same page fed by invented demo telemetry, labelled demo
```

`make web` runs `apps/phantom-phone/hud-web/server.py`. That one server serves `site/`, the telemetry stream (`/events`, from the real log `~/.chimera/telemetry.jsonl`), `/api/bench`, `/api/evals`, and the backend API (`/api/chat`, `/api/health`, `/api/stats`, from `chimera_core.service`; see `docs/api.md`). It binds `127.0.0.1`.

## Controls

| Key | Does |
|---|---|
| W (hold), S (hold) | walk forward, walk back |
| Shift | run |
| A, D, mouse | look around; in the hall, choose a door |
| E, Enter | open the gates, the great door, the chosen door |
| T | talk to Count Cuspid (`/api/chat`, with the live trace) |
| M | map: jump to any stretch or door |
| Esc | leave a room, a panel or the map |

Phones get a joystick and an E button. The corner map shows the path and where you are.

## Rooms

The doors come from `rooms.js` (one per room, with its posters; every number links to its `bench/*.md` source). The Observatory, the Ledger and the Ladder also show the Halloween dashboard (`dashboard/halloween.html?view=live|evals|how&embed=1`, live `/api/stats`, `/events`, `/api/evals`). When a room has a clip `game/clips/room-<id>.mp4`, its door opens on video; otherwise the room fades in.

## Add a clip

Add it to `game/clips.json` (`first` keyframe or `from` another clip, optional `last` frame, prompt, seconds, resolution). Then run `.venv/bin/python scripts/gen_video.py run`. It skips clips already made, collects a request that was already paid for, and logs each call to `bench/.scratch/video/calls.jsonl`. The page plays the new file with no code change.

## Files

- `index.html`: the page, the dashboard blocks, the generated plain fallback.
- `game/`: `walk.js` (the walk, controls, bats, map), `panels.js` (rooms, Count chat), `walk.css`, `clips.json`, `clips/`, and `game.js` + `layers/` (the earlier layered scene).
- `dashboard/halloween.html`: the Halloween dashboard (from commit 91205b4, live data, Evals and Chat tabs).
- `world/chat.js`: the chat and trace, shared. `world/` and `castle/`: earlier 2D and 3D castles, off the main path.
- `rooms.js`, `build.py`, `styles.css`, `art/`.

## Without JavaScript

The plain HTML version shows every room as a section with its posters.

## Motion

One `requestAnimationFrame` loop that never pauses: a flock of 120 bats in three depths, fog, fireflies, candle glow, and the head bob while you walk.

## Limits

- Only Chromium was checked, headless (57 to 60 fps). No phone was tested.
- Until GMI credits return, four walk stretches and all rooms use the painted dolly, not video.
