# Demo v3 (Kiroween 2026): live, new voice, no dead gaps

This take is LIVE. The walk and every chat call ran on a local `make web` pointed at our own 30B (`qwen3:30b-instruct`) on GPU 1 of the A6000 box, then the Crusoe 763B. It fixes the three complaints about `demo_voiced.mp4`:

| Complaint | Fix in v3 |
|---|---|
| The voice (ElevenLabs George) | A different preset voice: **Bella**, warm and professional (below). |
| Numbers read badly | Every number in the narration is written as words. `scripts/demo_record_v3.py` refuses a line with a digit, `%` or `$` (test: `tests/test_demo_record_v3.py`). |
| Dead gaps and a frozen end | Each shot lasts as long as its spoken line plus 0.8 s, so no frame is held to fit the voice. A gold progress bar moves along the bottom the whole time. End cards and room paintings drift slowly, the chat answer scrolls while it is read. The only fade is 1 s at the very end. |

| File | What |
|---|---|
| `site/docs/demo_v3.mp4` | The video. 1920x1080, 30 fps, H.264 + AAC 48 kHz, 2:25.4, captions burned in, the voice mixed at -16.5 LUFS. |
| `site/docs/demo_v3.srt` | The spoken lines as subtitles, timed to the voice. |
| `site/docs/demo_v3.json` | Shot and caption times, line times, the server's own record of every live call (`/api/stats` `recent`), and the gap check. |
| `site/docs/demo_v3_shots/` | One still per shot. |
| `scripts/demo_record_v3.py` | `voice` (synthesize once), `rehearse` (landing + walk), `record` (the live take). |

The old cuts stay as they were: `demo_cut.mp4`, `demo_cut_v2.mp4`, `demo_live.mp4`, `demo_voiced.mp4`, `demo_cut_v2_voiced.mp4` (`site/docs/demo_live.md`).

## The voice (reproducible)

- ElevenLabs text-to-speech, premade voice **Bella - Professional, Bright, Warm** (`voice_id` `hpp4J3VqNfWAUOO0d1Us`, American, female, middle-aged, "informative educational"). Not George, not Adam.
- Model `eleven_multilingual_v2`, output `mp3_44100_128`.
- Settings: stability 0.5, similarity boost 0.8, style 0.15, speaker boost on, speed 1.0.
- One request per shot, 10 requests, 1,998 characters, each sent once. No sample, no retry. The account showed 211 of 10,000 free characters used before. The clips live in the git-ignored `bench/.scratch/demo_v3/voice/`; the script never sends a line whose clip exists.
- The key is read from `.env` (`ELEVENLABS_API_KEY`) and is in no committed file.
- Redo: `.venv/bin/python scripts/demo_record_v3.py voice`, then `record`.

Clip lengths: 8.5, 12.1, 19.8, 9.2, 6.6, 17.6, 19.7, 14.1, 4.2, 19.0 s (130.7 s of speech in a 145.4 s video).

## Shots and timings (`demo_v3.mp4`)

Each line starts 0.3 s into its shot.

| # | Time | Screen | Number on screen | Source |
|---|---|---|---|---|
| 1 | 0:00-0:09.6 | Painted landing, gates shut, camera sways | none | `site/` |
| 2 | 0:09.6-0:23.8 | Hold W to the gates (0.9 s), A, A (look left, yaw 0.32 rad), one click on the gate opens it, W through the drive and the great door into the Great Hall (3.5 s) | none | `site/game/walk.js` |
| 3 | 0:23.8-0:44.7 | Count's chat: gold question, routing trace | cache miss (best cosine 0.27), 30B 1.1 s, 27 tokens, $0 | live |
| 4 | 0:44.7-0:54.9 | Same question again | shared cache exact hit 0.11 s, 0 tokens, $0 | live |
| 5 | 0:54.9-1:04.0 | FizzBuzz | 30B 1.6 s, 163 tokens, $0, confidence 1.00; 163 tokens kept off the 763B | live |
| 6 | 1:04.0-1:23.1 | Hard design task climbs | 30B 0.85 < 0.95; 9.2 s, $0.00085; 763B alone 5.0 s | live, `bench/results_backend_v3.md` |
| 7 | 1:23.1-1:43.9 | The Ledger cost chart, 30% repeats | 62% to 87% less than GPT-5.5; 607% more than the 763B at 100,000 calls a day | `bench/results_company_cost.md` |
| 8 | 1:43.9-1:59.0 | The Workshop | 7 steering, 7 specs, 6 hooks, 4 agents; 4 bugs found, 4 fixed | `.kiro/`, `docs/handoff/property-tests.md` |
| 9 | 1:59.0-2:04.3 | Closing card over the moving landing | 62% to 87%; 607% more | `bench/results_company_cost.md` |
| 10 | 2:04.3-2:25.4 | A6000 card, then a 1 s fade-out | 70.7% fewer 763B calls, 0 wrong answers from the cache; 292 of 301 vs 286 for the 763B alone; loss: median 3.1 s vs 0.7 s on a first pass | `bench/results_a6000.md` |

The gate opens because of the click, not by walking into it: W stops at 4.4 m, before the 3.6 m where the gates open by themselves. The click is a new, small input in `site/game/walk.js`: a click (not a drag) on a shut gate or door you look at opens it. The on-screen hint now says "E or a click opens now". A gold ring shows where the click landed.

## The live calls

From `site/docs/demo_v3.json` (`calls`). Cache tenant `demo-v3-rec3-1117`, empty before the take except one warm-up question ("Name one primary colour.").

| Shot | Question | Answered by | Time | Tokens in / out | Cost |
|---|---|---|---|---|---|
| 3 | What is the chemical symbol for gold? | our 30B (`gpu-small`), confidence 1.00 | 1.14 s (30B call 291 ms) | 16 / 11 | $0 |
| 4 | the same question again | Supabase cache, exact hit | 0.11 s | 0 / 0 | $0 |
| 5 | FizzBuzz (`c2` in `bench/prompts.jsonl`) | our 30B, confidence 0.996 | 1.63 s | 73 / 90 | $0 |
| 6 | rate limiter design (`h2`) | 30B tried (5.5 s, confidence 0.85 < 0.95), then the 763B (3.2 s) | 9.2 s | 136 / 1,483 | $0.00085 |

Shot 6 is a loss: the climb took 9.2 s; the 763B alone took 5.0 s at about the same cost ($0.00088) in the saved tuned run (`bench/results_backend_v3.md`).

The narration states no live number, so it cannot drift from the take: it says "about a second" (1.14 s), "a fraction of a second" (0.11 s), "a second or two" (1.63 s) and "slower than asking the big model alone" (9.2 s vs 5.0 s). The recorder refuses a take whose calls do not go miss, hit, 30B, climb.

Two earlier takes were dropped. Take 1: the first 30B call took 5.5 s, most likely because the server's `num_thread` option made Ollama reload the model after a warm-up sent without it, so "about a second" was false; it also had held stretches in the chat and on the end card. Take 2: a 5 s pause after the FizzBuzz line. Take 3 warmed the model through the server and fixed both.

## Gap check (`demo_v3.json` `gaps`)

ffmpeg over the final file. Frozen = no change for 1 s in the frame above the progress bar (`freezedetect=n=-60dB:d=1`), so the bar alone cannot pass it.

| Check | Result |
|---|---|
| Black frames of 0.3 s or more | none |
| Frozen picture of 1 s or more | one, 1.0 s at 1:00.3: the browser sent no frame for 0.98 s just after the FizzBuzz answer rendered, while the voice was speaking. Take 1 had it at the same spot. |
| Silence of 2.5 s or more | one, 2.9 s at 1:01.4, between the FizzBuzz and hard-task lines, while the captions change |
| The end | the voice ends at 2:23.6, then 0.7 s of the moving card, then a 1 s fade. No held last frame. |

## Narration (word form)

Every number is written as words, so the voice says it right. `scripts/demo_record_v3.py` refuses a line with a digit, `%` or `$`.

**Shot 1.** "Companies pay a frontier model for every coding call, even FizzBuzz. Chimera answers each call at the cheapest place that gets it right."

**Shot 2.** "This take is live, on our own graphics card. I hold W and walk up to the gates. I look left, and left again. One click, and the gates swing open. Then the great door, and the Great Hall."

**Shot 3.** "I ask the Count a question. The call climbs a ladder. First our shared cache, then our own thirty billion model, then the big seven hundred sixty-three billion model. The cache has not seen this question. So our thirty billion model answers, on our own card, in about a second. No token bill."

**Shot 4.** "I ask the same question again. This time the shared cache answers, in a fraction of a second. Zero tokens, and no model was called."

**Shot 5.** "Now FizzBuzz. Our thirty billion model writes it in a second or two, and every token stays off the big model."

**Shot 6.** "Now a hard design task. The thirty billion model tries first, but it is not sure enough. So the call climbs to the seven hundred sixty-three billion model. Here is a loss. With the climb, this call is slower than asking the big model alone, at about the same cost."

**Shot 7.** "Here is the bill for a month of coding calls. When three in ten calls are repeats, we spend sixty-two to eighty-seven percent less than G P T five point five alone. Now the loss. Against the cheap seven hundred sixty-three billion model, at a hundred thousand calls a day, we cost six hundred seven percent more."

**Shot 8.** "We built this with Kiro. Seven steering files, seven specs, six hooks, four custom agents, M C P tools and a Power. Property tests from the specs found four real bugs, and all four are fixed."

**Shot 9.** "Stop paying a frontier model for FizzBuzz. We prove it with tests."

**Shot 10.** "On our own A six thousand card, calls to the seven hundred sixty-three billion model fell seventy point seven percent, with zero wrong answers from the cache. We got two hundred ninety-two of three hundred one coding tasks right. The big model alone got two hundred eighty-six. The loss: a first pass is slower."

## How it was made

- GPU: GPU 1 only. `bench/a6000/serve.sh 1 <GPU 1 UUID>` started by hand (the script pins Ollama with `CUDA_VISIBLE_DEVICES` set to that GPU's UUID), with the watchdog in `manual` mode: it starts nothing and kills our server, proxy and tunnel on any contention on either GPU. Another user's job held GPU 0 (one process, about 19 GB) the whole time and was never touched.
- Access: the bearer-token proxy (401 without the token) behind a Cloudflare quick tunnel, for this recording only. Its URL and token sat in a mode-600 git-ignored scratch file and the server's environment, never in git. The file is deleted.
- Page: `make web` on 127.0.0.1:8765 with a scratch copy of `chimera.toml` that sets a fresh cache tenant. Every chat call went through `SpeculativeCascadeRouter.generate()`. Afterwards the usual `scripts/web_keep.sh` loop was started again with the normal config.
- Frames: Chrome DevTools screencast (Playwright Chromium, `--no-sandbox`, 1920x1080) at 59.4 fps, made a steady 30 fps by ffmpeg. Captions and the progress bar are page text drawn on top, so they are burned in.
- Mix: ffmpeg `adelay` per line, `amix`, `loudnorm` to -16 LUFS, AAC 192 kb/s, 48 kHz; video and audio fade out over the last 1 s.

## GPU log (box time, EST)

| Time | What happened |
|---|---|
| 18:46 | GPU 0: the other user's job (one pid, 19.3 GB, busy). GPU 1: 12 MiB, no process. |
| 18:54 | Our Ollama started on GPU 1 (watchdog `manual`). |
| 18:55-19:11 | Three takes. No yield was needed: the yield log has no new line. |
| 19:12:01 | Our server, proxy and tunnel stopped (`want=stop`). |

Proof GPU 1 is clear after the take: `nvidia-smi` showed GPU 1 at 12 MiB, 0% use, no compute process. No Ollama, proxy or tunnel of ours ran, and the take's tunnel URL returned 530. The one older quick tunnel from 2026-10-22 on the same box account was left alone, as before.
