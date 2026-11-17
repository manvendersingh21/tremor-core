# UI rework v2: the castle is a real 3D world

The user rejected the Pages build of 2026-11-16 ([manvendersingh21.github.io/tremor-core](https://manvendersingh21.github.io/tremor-core/)) with seven complaints. Each one is fixed below, with a screenshot from the Pages build before and after. All "after" screenshots and numbers come from the Pages build of commit `bbd8751` (or later), with every `/api/*` call failing, the same as for a visitor.

What changed underneath: the walk-in no longer plays painted video clips over a flat painting. It is a 3D world built with three.js r170 (already vendored in `site/vendor/`), in a new file, `site/game/world3d.js`. You are the camera on one rail. The road outside the iron gates leads through the gates, up the lantern drive and through the great door into the Great Hall. The gates, the great door and the ten room doors are real hinged objects. The painted art is used as textures:

| Texture | Source art |
|---|---|
| sky | new 2:1 panorama, `art/pano-night.webp` |
| stone, vault, floor, road | `art/tex-*.webp` |
| door leaves | `game/layers/door-leaf-*.webp`, cut from the painted great door |
| rose and lancet windows | `art/glass-*.webp` |
| banners | `art/banner.webp` |
| the Count | `game/layers/count-full.webp`, a cut-out with a shadow and fog at his feet |

Two new paintings were made with MiniMax-M3 writing the prompts and Seedream on GMI painting them: `pano-night` and `study-chat` (`site/art/README.md`). No video was made.

The user rules still hold:

- One URL and one page.
- Animation never stops. There is no pause control and no reduced-motion or hidden-tab stop.
- The numbers are the same saved results as before (`site/demo.json`, read from `bench/*.md`).
- `python3 site/build.py --check` passes.

## Measured on the Pages build

`scripts/ui_rounds.py v2 <browser> <view> demo` ran against the public link. Each run walks in with W held (the stick on a phone), opens every door, opens the map and the chat, runs the cache test and the tour, and checks for small text, unnamed controls and errors.

| Browser | View | Checks passed | First paint | First W to inside the Great Hall | fps (median) |
|---|---|---|---|---|---|
| Chromium | desktop 1280 x 760 | 53 of 53 | 472 ms | 3.76 s | 60 |
| Chromium | iPhone 13 view (390 x 664) | 65 of 65 | 432 ms | 3.75 s | 60 |
| WebKit | desktop 1280 x 760 | 53 of 53 | 285 ms | 3.67 s | 100 (headless WebKit is not vsynced) |
| WebKit | iPhone 13 view | 65 of 65 | 248 ms | 3.76 s | 100 (same) |

`scripts/ui_v2_shots.py after <browser> <view>` also ran on the Pages build. It records your place on the rail every 0.25 s while W is held, and turns round to close the gates and the door. In all four runs:

- Your place on the rail never went back (0 backward steps).
- E shut the gates behind you, and they ended closed.
- E shut the great door behind you, and it ended closed.

The walk video, [ui_rework_v2_walk.mp4](ui_rework_v2_walk.mp4) (21 s, WebKit, the Pages build), shows the full sequence:

1. Look round outside the shut gates.
2. Hold W. The Great Hall is reached after 3.66 s of W.
3. Turn round.
4. Press E. The great door shuts.
5. Turn back.

Its step log is in [ui_rework_v2_walk.json](ui_rework_v2_walk.json).

The phone rows above ran in an iPhone 13 view on this Mac's GPU (Apple M4). They are not a real phone. The 30+ fps phone target has not been measured on a phone.

## 1. The iron gates are shut when the page opens

Before, the landing painting (`art/gate.webp`) shows the gates already open. Now the gates are two 3D leaves that are closed at the start. They swing open as you reach them: the trigger is 3.6 m away, about 1 s into the walk.

| Before (Pages, 2026-11-16) | After, Chromium | After, WebKit |
|---|---|---|
| ![before](v2/before_chromium_desktop_01_landing.jpg) | ![after](v2/after_chromium_desktop_01_landing.jpg) | ![after webkit](v2/after_webkit_desktop_01_landing.jpg) |

| After, phone (WebKit) | After, phone (Chromium) |
|---|---|
| ![phone](v2/after_webkit_phone_01_landing.jpg) | ![phone](v2/after_chromium_phone_01_landing.jpg) |

## 2. You can stand outside and look round

The view responds to the mouse, a drag on desktop or phone, and A/D or the arrow keys:

- **Mouse:** click the castle to lock the mouse, then look anywhere. Esc frees the mouse.
- **Drag:** works on desktop and on a phone.
- **Keys:** A/D and the arrow keys turn the head.

The sky is a full 360° painting, so every direction shows something: the castle, the fence and forest on both sides, the road you came on, and the moon with its bat flock. Before, the mouse only moved a flat painting a few percent, so "left" and "right" look the same as the landing.

| Before: look left | Before: look right |
|---|---|
| ![before left](v2/before_chromium_desktop_03_look_left.jpg) | ![before right](v2/before_chromium_desktop_03_look_right.jpg) |

| After: look left | After: look right | After: turn round |
|---|---|---|
| ![left](v2/after_chromium_desktop_03_look_left.jpg) | ![right](v2/after_chromium_desktop_03_look_right.jpg) | ![behind](v2/after_chromium_desktop_03_look_behind.jpg) |

| After, WebKit: turn round | After, phone: drag to look left |
|---|---|
| ![webkit behind](v2/after_webkit_desktop_03_look_behind.jpg) | ![phone left](v2/after_webkit_phone_03_look_left.jpg) |

## 3. One forward walk, no jump back

Before, the gate clip ended close to the gates. The next stretch then started from a frame further back, so stepping through "took you back". The two frames below were taken about 0.5 s apart while W was held.

Now there are no clips in the walk. W moves you along one rail, and its position (`railZ` in `world3d.js`) only falls as you walk. The test `tests/test_castle.py::test_3d_walk_rail_only_goes_forward_and_reaches_the_hall_in_4_s` checks this every 0.01 s of the rail. If a gate or door has not swung clear yet, you wait a beat in place. You are never moved back.

| Before: at the gates | Before: 0.5 s later, further back |
|---|---|
| ![before 1](v2/before_chromium_desktop_10_walk_04.jpg) | ![before 2](v2/before_chromium_desktop_10_walk_06.jpg) |

After: frames about 0.5 s apart while W is held. The gates are shut, then open, then you walk through, then the drive, then the great door. The contact sheet below has 12 frames from the video at 3 per second.

| | |
|---|---|
| ![a](v2/after_chromium_desktop_10_walk_04.jpg) | ![b](v2/after_chromium_desktop_10_walk_06.jpg) |
| ![c](v2/after_chromium_desktop_10_walk_08.jpg) | ![d](v2/after_chromium_desktop_10_walk_10.jpg) |

![contact sheet](v2/after_walk_contact_sheet.jpg)

## 4. The minimap is a painted map

Before, the minimap was a thin grey L with 9 px labels. Now it is a parchment map (`art/parchment-paper.webp`) in a gold and purple frame with a "The Castle" ribbon. It is drawn in ink and gold from the same plan as the 3D world:

- the fence and the gates (wine red when shut, gold when open, drawn at their real swing)
- the road and the lantern drive, with lantern dots
- the castle towers and the great door (open or shut)
- the hall's columns and red carpet
- the ten room doors as lettered gold arches; the one you look at glows
- you, as a glowing dot with a cone where you look

The caption under the map names the place, or the door you are looking at. M opens the same map large, with every room named outside the walls and a lettered list to jump to.

| Before | After (outside) | After (in the hall) | After (phone) |
|---|---|---|---|
| ![before](v2/before_chromium_desktop_02_minimap.jpg) | ![after](v2/after_chromium_desktop_02_minimap.jpg) | ![hall](v2/after_chromium_desktop_21_minimap_hall.jpg) | ![phone](v2/after_webkit_phone_02_minimap.jpg) |

| Before: M | After: M (Chromium) | After: M (WebKit) | After: M (phone) |
|---|---|---|---|
| ![before map](v2/before_chromium_desktop_50_map.jpg) | ![map](v2/after_chromium_desktop_50_map.jpg) | ![map webkit](v2/after_webkit_desktop_50_map.jpg) | ![map phone](v2/after_chromium_phone_50_map.jpg) |

## 5. The chat is the Count's candle-lit study

The chat now opens in the Count's study:

- The new `art/study-chat.webp` painting is the background: moonlight through a gothic window, candles.
- A candle glow flickers over it and two fog layers drift.
- The Count's portrait sits in a gold ring that glows.
- His messages are parchment bubbles; yours are wine-red bubbles.
- The saved-question chips are gold-rimmed, and the input and buttons are gold.

The routing trace now starts with a ladder: Cache, then GPU 30B, then 763B. Each rung lights up as the call reaches it (pulsing while it waits), with that step's time and tokens, and the rung that answered is marked "answered". Every value on the ladder is read from the `/api/chat` events, or from the saved events in DEMO. In the saved COLD row, the cache lookup was over its time budget (`unavailable · 301 ms`) and the 30B answered in 36,811 ms. Those are the real saved numbers.

| Before | After, waiting | After, climbing | After, answered |
|---|---|---|---|
| ![before](v2/before_chromium_desktop_30_chat.jpg) | ![after](v2/after_chromium_desktop_30_chat.jpg) | ![climbing](v2/after_chromium_desktop_31_chat_climbing.jpg) | ![answered](v2/after_chromium_desktop_32_chat_answered.jpg) |

| After, WebKit | After, phone |
|---|---|
| ![webkit](v2/after_webkit_desktop_32_chat_answered.jpg) | ![phone](v2/after_webkit_phone_32_chat_answered.jpg) |

## 6. Every overlay has the same art

Every overlay now shares one style:

- **Room panels:** the room's own painting is behind the numbers (its painted clip, if one was made, loops there). The panel has a gold gothic frame with corner flourishes, a velvet title ribbon, moving candlelight and fog, parchment posters, and gold-rimmed number cards.
- **Map (M):** uses the same frame.
- **Tour:** a parchment scroll with the Count's portrait.
- **Savings board:** a gold-framed plaque.
- **Dashboards:** the Observatory, Ledger and Ladder dashboards sit in a gold frame.
- **Hall signs:** the room signs are gold plaques with real text, hung over each door in 3D.

| Before: a room | After: the Crypt | After: the Observatory |
|---|---|---|
| ![before](v2/before_chromium_desktop_40_room_crypt.jpg) | ![crypt](v2/after_chromium_desktop_40_room_crypt.jpg) | ![observatory](v2/after_chromium_desktop_41_room_observatory.jpg) |

| After: the tour | After: the hall's door signs and savings board |
|---|---|
| ![tour](v2/after_chromium_desktop_60_tour.jpg) | ![hall](v2/after_chromium_desktop_20_hall.jpg) |

## 7. Inside, you can look round and shut the doors behind you

The hall is 46 m long and 18 m wide, with a ribbed vault 18 m up. It has 14 columns, 3 chandeliers, lancet windows, a rose window with moonlight, banners, a red carpet with candle stands, and ten gold doors.

You look round it the same way as outside. Look at a gold door and press E, or click its sign, and it swings open into its room. W walks you on down the hall.

When you turn round, the great door you came through is open. E shuts it, and you see it shut; it opens again if you walk back to it. The iron gates work the same way from the drive.

| The hall | Look up left | Look up right |
|---|---|---|
| ![before hall](v2/before_chromium_desktop_20_hall.jpg) (before: a flat painting) | ![left](v2/after_chromium_desktop_24_hall_look_left_up.jpg) | ![right](v2/after_chromium_desktop_24_hall_look_right_up.jpg) |

| Turn round: the great door, open | E: shut behind you | WebKit: shut | Phone: shut |
|---|---|---|---|
| ![open](v2/after_chromium_desktop_22_door_open_behind.jpg) | ![closed](v2/after_chromium_desktop_23_door_closed_behind.jpg) | ![webkit](v2/after_webkit_desktop_23_door_closed_behind.jpg) | ![phone](v2/after_webkit_phone_23_door_closed_behind.jpg) |

| From the drive: the gates, open | E: shut behind you | WebKit: shut |
|---|---|---|
| ![gates open](v2/after_chromium_desktop_15_gates_open_behind.jpg) | ![gates shut](v2/after_chromium_desktop_16_gates_closed_behind.jpg) | ![webkit gates](v2/after_webkit_desktop_16_gates_closed_behind.jpg) |

On a phone, the hall's doors are one row of named gold doors you can scroll, above the stick. The row scrolls to the door you look at.

| Phone hall (WebKit) | Phone hall (Chromium) |
|---|---|
| ![phone hall](v2/after_webkit_phone_20_hall.jpg) | ![phone hall chromium](v2/after_chromium_phone_20_hall.jpg) |

## Files

| File | What it does |
|---|---|
| `site/game/world3d.js` (new) | the 3D world, the rail and the hall's door list |
| `site/game/walk.js` (rewritten) | input, walking, E to open and close, the painted map and minimap, the bat flock, signs, panels |
| `site/game/walk.css` | the frames, map, chat, ladder and phone layout |
| `site/game/panels.js` | the chat header |
| `site/world/chat.js` | the ladder |
| `site/index.html` | loads the 3D module |
| `site/game/scene.js` | deleted: the old painted-hall overlay |

The `MovieGame` interface that the tour and the test scripts use is kept: `state.hall`, `state.open`, `doors`, `use`, `jump`, `talk`, `openMap`, `fps`. The tour still runs: 13 stops, and it walks in for real.

## Commands run

```
.venv/bin/python scripts/gen_art.py --enrich pano-night study-chat        # 2 MiniMax-M3 prompts, 2 Seedream images on GMI
.venv/bin/python -m pytest -q tests/test_castle.py tests/test_site_demo.py tests/test_world.py tests/test_hud.py tests/test_site_results.py
python3 site/build.py --check
.venv/bin/python scripts/ui_rounds.py v2 chromium|webkit desktop|phone demo --url https://manvendersingh21.github.io/tremor-core/
.venv/bin/python scripts/ui_v2_shots.py before|after chromium|webkit desktop|phone       # Pages build
.venv/bin/python scripts/ui_v2_record.py webkit                                           # Pages build, writes the mp4
python3 .kiro/hooks/scripts/secret_scan.py --staged                                       # before every commit
```

`scripts/ui_rounds.py` now starts Chromium on the GPU (`--enable-gpu --use-angle=metal`). Without that, headless Chromium draws WebGL in software at about 20 fps, which is a test setting and not what a visitor sees. WebKit needed no change. Chromium's own video recorder slowed the page to about 20 fps, so the video was recorded in WebKit, which stayed at about 97 fps while recording.

## Not done or not measured

- A real phone was not tested. The phone rows are an iPhone 13 view on a Mac.
- The castle outside is built from shapes with painted textures. It is not one painting, so it looks less detailed than `art/gate.webp` up close.
- The room door clips (`game/clips/room-*.mp4`) now loop behind a room's numbers instead of playing as a door opening. They were painted for the old flat hall, and the doors now open in 3D. The files in `game/clips/` were not changed.
- `.kiro/steering/ui.md` still describes the walk as painted video clips. This work did not touch `.kiro/`.
