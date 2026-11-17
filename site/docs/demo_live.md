# Live demo video (Kiroween 2026)

This take is LIVE. The Count's chat called the real ladder on a local `make web`: the Supabase cache, then our own 30B (`qwen3:30b-instruct`) on one RTX A6000, then the Crusoe 763B. Nothing in the chat is a replay.

| File | What |
|---|---|
| `site/docs/demo_live.mp4` | The live video. 1920x1080, 30 fps, H.264, 2:42, captions burned in. One silent stereo AAC track, empty, for your voice. |
| `site/docs/demo_live.srt` | The same captions as soft subtitles. |
| `site/docs/demo_live.json` | When each shot and caption started, and the server's own record of every live call (`/api/stats` `recent`). |
| `site/docs/demo_live_shots/` | One still per shot. |
| `site/docs/demo_cut_v2.mp4` | The older replay cut (`demo_cut.mp4`, 2:46) with the A6000 card added at the end, 1 s cross-fade. 2:57, one silent track. Use it if you do not re-read the narration for the live take. |
| `site/docs/demo_cut_v2.srt` | `demo_cut.srt` plus one cue for the A6000 card. |
| `scripts/demo_record_live.py` | Records it again (needs a live server; see "How it was made"). `--v2-only` rebuilds only `demo_cut_v2.mp4`. |

The voice-over is yours to record. No AI or synthetic voice is in either file, and none should be added.

## The live calls

Read from `site/docs/demo_live.json` (`calls`). Cache tenant `demo-live-rec1-1117`, empty before the take.

| Shot | Question | Answered by | Time | Tokens in / out | Cost |
|---|---|---|---|---|---|
| 3 | What is the chemical symbol for gold? | our 30B (`gpu-small`), confidence 1.00 | 0.95 s (30B call 319 ms) | 16 / 11 | $0 |
| 4 | the same question again | Supabase cache, exact hit | 0.11 s | 0 / 0 | $0 |
| 5 | FizzBuzz (`c2` in `bench/prompts.jsonl`) | our 30B, confidence 0.995 | 1.4 s | 73 / 90 | $0 |
| 6 | rate limiter design (`h2`) | 30B tried (5.0 s, confidence 0.87 < 0.95), then the 763B (3.3 s) | 8.9 s | 136 / 1,397 | $0.00083 |

Shot 6 is a loss: the climb took 8.9 s, and the 763B alone took 5.0 s at about the same cost ($0.00088) in the saved tuned run (`bench/results_backend_v3.md`).

## Shots and timings (`demo_live.mp4`)

| # | Time | Screen | Number on screen | Source |
|---|---|---|---|---|
| 1 | 0:00-0:10 | Painted landing, gates shut | none | `site/` |
| 2 | 0:10-0:22 | Walk-in (3.8 s of held W) into the Great Hall | none | `site/game/` |
| 3 | 0:22-0:42 | Count's chat: gold question, routing trace | cache miss (cosine 0.35), 30B 0.95 s, 27 tokens, $0 | live |
| 4 | 0:42-0:54 | Same question again | cache hit 0.11 s, 0 tokens, $0 | live |
| 5 | 0:54-1:12 | FizzBuzz | 30B 1.4 s, 163 tokens, $0; 163 tokens kept off the 763B | live |
| 6 | 1:12-1:37 | Hard design task climbs | 0.87 < 0.95; 8.9 s, $0.00083; 763B alone 5.0 s | live, `bench/results_backend_v3.md` |
| 7 | 1:37-2:04 | The Ledger cost chart, 30% repeats | 62% to 87% less than GPT-5.5; 607% more than the 763B at 100,000 calls a day | `bench/results_company_cost.md` |
| 8 | 2:04-2:21 | The Workshop | 7 steering, 7 specs, 6 hooks, 4 agents; 4 bugs found, 4 fixed | `.kiro/`, `docs/handoff/property-tests.md` |
| 9 | 2:21-2:29 | Closing card | 62% to 87%; 607% more | `bench/results_company_cost.md` |
| 10 | 2:29-2:42 | A6000 card | 70.7% fewer 763B calls, 0 wrong answers from the cache; 292 of 301 vs 286 for the 763B alone; loss: median 3.1 s vs 0.7 s on a first pass | `bench/results_a6000.md` |

`demo_cut_v2.mp4`: shots 1 to 9 as in `site/docs/demo_video.md` (0:00-2:46), then the A6000 card from 2:45 to 2:57.

## Narration to read (`demo_live.mp4`)

Calm pace. Start each line when its shot starts. About 330 words.

**Shot 1 (0:00).** "Companies pay a frontier model for every coding call, even FizzBuzz. CHIMERA answers each call at the cheapest place that gets it right. This take is live, on our own GPU."

**Shot 2 (0:10).** "The whole app is one page. Hold W. The gates open, then the great door. Every gold door is a room of measured numbers."

**Shot 3 (0:22).** "I ask the Count a question. The call climbs a ladder: our shared cache first, then our own 30B, then the big 763B. The cache has not seen this one. So our 30B answers, on our A6000, in under a second. No token bill."

**Shot 4 (0:42).** "The same question again. The cache answers in a tenth of a second. Zero tokens. No model was called."

**Shot 5 (0:54).** "FizzBuzz. Our 30B writes it in about one and a half seconds. All 163 tokens stay off the 763B."

**Shot 6 (1:12).** "Now a hard design task. The 30B tries first, but it is not sure: 0.87, under our 0.95 bar. So the call climbs to the 763B. Here is a loss. With the climb it took 9 seconds. The 763B alone took 5, at about the same cost."

**Shot 7 (1:37).** "Here is the bill for a month of coding calls. With 3 in 10 calls being repeats, we spend 62 to 87 percent less than GPT-5.5 alone. Now the loss. Against the cheap 763B, at 100 thousand calls a day, we cost 607 percent more."

**Shot 8 (2:04).** "We built this with Kiro. Seven steering files, seven specs, six hooks, four custom agents, MCP tools and a Power. Property tests from the specs found four real bugs. All four are fixed."

**Shot 9 (2:21).** "Stop paying a frontier model for FizzBuzz. We prove it with tests."

**Shot 10 (2:29).** "On our own A6000, the cache and the answer check cut 763B calls by 70.7 percent, with zero wrong answers from the cache. The ladder got 292 of 301 coding tasks right. The 763B alone got 286. The loss: on a first pass we are slower. CHIMERA, for Kiroween 2026."

For `demo_cut_v2.mp4`, read the shot lines in `site/docs/demo_video.md`, then the shot 10 line above at 2:45.

## Join your voice

Record with QuickTime (File, New Audio Recording) while the video plays. Save it as `voice.m4a`. Then, in the repo folder:

```
ffmpeg -i site/docs/demo_live.mp4 -i voice.m4a -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k demo_final.mp4
```

This replaces the silent track. Keep `demo_final.mp4` out of git. Upload with `site/docs/demo_live.srt` as subtitles. The title, description and Devpost steps in `site/docs/demo_video.md` still apply.

## How it was made

- GPU: the shared A6000 box, GPU 1 only (the serve script pins Ollama to that GPU's UUID). Another user's job held GPU 0 and was never touched. `qwen3:30b-instruct`, flash attention, q8 KV cache, 4 slots, kept loaded (`bench/a6000/serve.sh`).
- Access: a bearer-token proxy (401 without the token) behind a Cloudflare quick tunnel, for this recording only. Its URL lived in the server's process environment and a git-ignored scratch file, never in git, and the scratch file is deleted. The public site stays in DEMO mode.
- Page: a local `make web` on 127.0.0.1:8765 with a scratch copy of `chimera.toml` that sets a fresh cache tenant. Every chat call went through `SpeculativeCascadeRouter.generate()`.
- Frames: Chrome DevTools screencast at 59.3 fps, made a steady 30 fps by ffmpeg. Captions are page text drawn on top, so they are burned into the frames. Each live caption is built from the server's record of that call, not typed in.
- The guard: `bench/a6000/watchdog.sh` polled both GPUs every 5 s, in manual mode (it starts nothing; it kills our server, proxy and tunnel on any contention).

## GPU yields during this work

| Box time (EST) | What happened |
|---|---|
| 15:48:46 | A new pid on GPU 0 (the other user's job). Our GPU 1 server and tunnel were killed. Correct yield. |
| 15:52-15:57 | Waited for 5 quiet minutes on both GPUs, then restarted on GPU 1. |
| 15:57:38 | False yield: our own model load read as 3,700 MiB "not ours". The watchdog read the process list before the GPU total, and the load grew in between. Fixed: totals are read first. `bench/a6000/selftest.sh` passed on the box (4 of 4). |
| 16:00-16:07 | Fixed watchdog running. The take ran with no yield. |
| 16:07:57 | Our server stopped (`want=stop`). |

Proof GPU 1 is clear after the take: `nvidia-smi` showed GPU 1 at 12 MiB, 0% use, no compute process. GPU 0 showed 123 MiB and no process. No Ollama, proxy or tunnel of ours was running, and the old tunnel URL returned 530. One older quick tunnel from 2026-10-22 runs under the same box account on another port. This work did not start it and left it alone.
