# CHIMERA site

A castle you walk through. Count Cuspid greets you at the gate. The great hall has eight doors. Each room has posters that bats hang on the wall.

No framework, no npm. The only external request is Google Fonts.

## Run

```
python3 -m http.server 8765 --bind 127.0.0.1 --directory site
```

or `make site`. Open http://127.0.0.1:8765. Stop it with Ctrl-C.

## Add a room or a poster

Edit `site/rooms.js`. It is plain JSON assigned to `window.ROOMS`. Each room has `id`, `title`, `door` (plaque line), `say` (what Count Cuspid says, one string per step) and `posters`. A poster has `at` (the step when bats bring it), `bats` (1 to 3), `title`, `big` or `steps`, `lines`, and `src` (label and repo path).

Then run `python3 site/build.py`. It writes the no-JS fallback (doors and one plain section per room) into `index.html`. `python3 site/build.py --check` fails if they are out of date. Use only real numbers from `bench/*.md`.

## Routes

`#entrance`, `#hall`, `#room/<id>`. The browser Back button works. Esc leaves a room. Enter opens the gate. Arrow keys step through his lines.

## Files

- `index.html`: page, Dracula SVG, generated fallback.
- `styles.css`, `tour.js`, `rooms.js`, `build.py`.
- `life.js`: Pause motion button (saved in localStorage `chimera-motion`), pause when the tab is hidden, mouse parallax on desktop.
- `docs/landing.png` (hall), `docs/room.png` (a room), `docs/animated.gif` (4.8 s of the gate), `docs/animated_still.png`.

## Motion

Bats (10, or 6 on phones) slide across on a linear x layer and swoop on a y layer, with a flapping SVG. Three bats circle the moon now and then. Clouds are three seamless gradient strips, 70 to 170 s per loop. The moon glow and halo breathe at 7 and 9 s. Candle flames, castle windows and embers use opacity and scale. Only `transform` and `opacity` animate. Bats and fog sit behind the speech bubble and posters.

## Deploy

Any static host: upload the `site/` folder.

GitHub Pages: `.github/workflows/pages.yml` publishes `site/` on pushes to `dev`. It does nothing until you enable Pages: repo Settings, Pages, Source "GitHub Actions". Then run the workflow or push a change under `site/`.

## Limits

- Screenshots came from headless Chromium driven over the DevTools protocol. Only Chromium was checked.
- No JS: all rooms show as plain sections. Reduced motion: no flying, no typing, no door swing, no bats; the moon glow stays as a still.
- Bats are not cut out behind the castle: the art has no depth layers, so far bats are small and dim instead.
- Candle and window glows are placed by eye on `gate.webp`; they drift a little from the art during the slow zoom.
