# Art and video: where it came from and what it cost

All art in `site/art/` and the walk-in clips in `site/game/clips/` were generated for this project. Keys come from `.env` only and are never printed or committed.

## Images

- Painter: Seedream 5.0 Pro on GMI (`scripts/gen_art.py`). Prompts in `prompts.json`.
- Art director: MiniMax-M3 (GMI chat API) rewrites each prompt once (`--enrich`), cached in `prompts.enriched.json`.
- The script skips files that already exist, so a rerun resumes.

| Batch | Images | MiniMax-M3 calls | Notes |
|---|---|---|---|
| First painted site (commit 9495aa2): gate, hall, door, 8 rooms, Count, parchment | 14 | 13 | per-image GMI price; the exact bill was not logged |
| Textures, windows, banner, doors, sky (2026-11-14) | 12 | 12 | `tex-*`, `glass-*`, `banner`, `door-*`, `sky-pano`; the run that was killed by a restart did not log its count |
| Walk pacing (2026-11-15): `hall-grand` (the Great Hall, 2 versions; `hall-grand-1` is used) and `great-door` (the closed castle doors) | 3 | 2 | the door is cut into a frame and two leaves offline by `scripts/cut_door.py` (`game/layers/door-*.webp`); GMI image calls only, no video |
| Walk polish (2026-11-15): `drive` (the lantern drive) and `count-full` (the Count, full length) | 3 | 3 | `count-full` was painted twice (the first had a beard); the cut-out `game/layers/count-full.webp` is made offline by `scripts/cut_count.py`. GMI image calls only; no video |

| UI rework v2 (2026-11-16): `pano-night` (a 2:1 painted night panorama, wrapped all the way round the 3D world in `game/world3d.js`; its left and right edges are blended offline so it has no seam) and `study-chat` (the Count's candle-lit study, behind the chat) | 2 | 2 | GMI image calls only, no video. The first try at 3072x1536 was refused (HTTP 500, "Backend error (400)"); 2720x1360 worked. Per-image GMI price; the exact bill was not logged |

Gate-layer cut-outs in `site/game/layers/` are made offline from `gate.webp` by `scripts/cut_layers.py` (no model call).

## Video (walk-in clips)

- Model: `seedance-2-0-260128` (BytePlus Seedance 2.0) on GMI's request queue, image-to-video with a first frame and optional last frame (`scripts/gen_video.py`, plan in `site/game/clips.json`).
- Each clip starts on the last frame of the clip before, so the walk joins without a cut.
- Price per second of video (GMI docs): 480p $0.07, 720p $0.152, 1080p $0.374.
- Every call is logged to `bench/.scratch/video/calls.jsonl`. A submitted request id is saved first, so a run that dies collects its video instead of paying again.

| When | Clip | Seconds | Resolution | Cost |
|---|---|---|---|---|
| 2026-11-14 00:40 | probe (test, not used) | 4 | 480p | $0.28 |
| 2026-11-14 00:46 | a-approach: the landing, walking up to the iron gates | 8 | 1080p | $2.99 |
| | **Total** | 12 | | **$3.27** |

The next call (b-gates) was refused with HTTP 402 "Insufficient credits". Clips b to e and the 9 room clips are not made yet. Until they are, those stretches play as a slow painted dolly over their keyframe image.
