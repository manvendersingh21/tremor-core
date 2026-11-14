"""Record the painted game from a running server with real key presses (headless Chromium, DevTools protocol).

  .venv/bin/python scripts/capture_game.py checkpoint   -> site/docs/game_checkpoint.gif (scene 1: walk in, bats, gates open)
"""
import asyncio, io, json, sys, time
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).parent))
from cdp import Page

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "site" / "docs"
BASE = "http://127.0.0.1:8765"
W, H, OUT_W = 1280, 720, 640


async def record(p, plan, fps=10):
    frames, on = [], {"v": True}

    async def rec():
        while on["v"]:
            t = time.monotonic()
            frames.append((t, await p.shot(fmt="jpeg")))
            await asyncio.sleep(max(0, 1 / fps - (time.monotonic() - t)))
    task = asyncio.create_task(rec())
    await plan()
    on["v"] = False
    await task
    return frames


def save_gif(frames, out, colors=96):
    imgs, durs = [], []
    for i, (t, data) in enumerate(frames):
        nxt = frames[i + 1][0] if i + 1 < len(frames) else t + 1.5
        im = Image.open(io.BytesIO(data)).convert("RGB").resize((OUT_W, OUT_W * H // W), Image.LANCZOS)
        imgs.append(im.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
        durs.append(int((nxt - t) * 1000))
    durs[-1] = 1500
    imgs[0].save(out, save_all=True, append_images=imgs[1:], duration=durs, loop=0, optimize=True)
    return {"frames": len(imgs), "seconds": round(sum(durs) / 1000, 1), "mb": round(out.stat().st_size / 1e6, 2)}


async def checkpoint():
    p = await Page.open(BASE + "/game/index.html", W, H, extra=["--use-angle=metal"])
    await asyncio.sleep(4)

    async def hold(k, s):
        await p.key(k); await asyncio.sleep(s); await p.key(k, False)

    async def plan():
        await asyncio.sleep(1.2)                 # the bats flock around the moon
        await hold("w", 2.4)                     # walk up to the iron gates
        await asyncio.sleep(0.4)
        await p.key("e"); await p.key("e", False)  # E: the gates swing open
        await asyncio.sleep(2.2)
        await hold("w", 3.4)                     # through the gates, up the drive: the castle grows
        await hold("a", 0.6); await hold("d", 1.0)
        await hold("w", 1.6)
    frames = await record(p, plan)
    fps = await p.js("CastleGame.fps()")
    await p.close()
    out = DOCS / "game_checkpoint.gif"
    st = save_gif(frames, out)
    st["fps_min"] = round(min(fps), 1); st["fps_mean"] = round(sum(fps) / len(fps), 1)
    print(json.dumps(st))


def save_mp4(frames, out):
    """Frames at their real timestamps -> H.264 mp4 (ffmpeg concat with per-frame durations)."""
    tmp = ROOT / "bench" / ".scratch" / "ui" / "mp4frames"
    tmp.mkdir(parents=True, exist_ok=True)
    for f in tmp.glob("*.jpg"):
        f.unlink()
    lines = []
    for i, (t, data) in enumerate(frames):
        (tmp / f"{i:05}.jpg").write_bytes(data)
        nxt = frames[i + 1][0] if i + 1 < len(frames) else t + 1.5
        lines += [f"file '{i:05}.jpg'", f"duration {max(0.02, nxt - t):.3f}"]
    lines.append(f"file '{len(frames) - 1:05}.jpg'")
    (tmp / "list.txt").write_text("\n".join(lines) + "\n")
    import subprocess
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"), "-vf", "fps=30,scale=1280:-2",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "24", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], check=True)
    return {"seconds": round(frames[-1][0] - frames[0][0] + 1.5, 1), "mb": round(out.stat().st_size / 1e6, 2), "frames": len(frames)}


async def walk(question="What is the capital of Poland?"):
    """A real play-through of the walk-in game: W at the landing to the Observatory, then the Count answers."""
    p = await Page.open(BASE + "/", W, H, extra=["--use-angle=metal", "--autoplay-policy=no-user-gesture-required"])
    await asyncio.sleep(5)
    shots = {}

    async def hold(k, s, run=False):
        if run:
            await p.key("Shift")
        await p.key(k); await asyncio.sleep(s); await p.key(k, False)
        if run:
            await p.key("Shift", False)

    async def tap(k, wait=0.5):
        await p.key(k); await p.key(k, False); await asyncio.sleep(wait)

    async def shot(name):
        shots[name] = DOCS / f"game_{name}.png"
        await p.shot(str(shots[name]))

    async def plan():
        await asyncio.sleep(1.0); await shot("1_landing")
        await hold("w", 4.0, run=True)            # the landing: walk up to the iron gates (real Seedance clip)
        await asyncio.sleep(0.5); await shot("2_gates")
        await tap("e", 1.0)                        # the gates open
        await hold("w", 2.0); await shot("3_through_gates")
        await hold("w", 2.2, run=True)
        await hold("w", 2.0, run=True); await shot("4_drive")   # the castle grows
        await hold("w", 3.2, run=True)
        await asyncio.sleep(0.4); await shot("5_great_door")
        await tap("e", 0.8)                        # the great door opens
        await hold("w", 2.0); await shot("6_door_opening")
        await hold("w", 2.2, run=True)
        await hold("w", 5.4, run=True)             # along the Great Hall
        await asyncio.sleep(0.6); await shot("7_hall_doors")
        await tap("e", 4.5)                        # the Observatory
        await shot("8_observatory")
        await tap("Escape", 1.2)
        await tap("d", 0.4); await tap("d", 0.4); await tap("d", 0.6)
        await tap("e", 2.5); await shot("9_room")  # a room with its posters
        await tap("Escape", 1.0)
        await tap("t", 1.2)                        # talk to the Count
        await p.js("document.getElementById('c-in').focus()"); await p.insert(question); await asyncio.sleep(0.4)
        await p.js("document.getElementById('c-form').requestSubmit()")
        for _ in range(1500):
            await asyncio.sleep(0.1)
            if await p.js("!document.getElementById('c-send').disabled"):
                break
        await asyncio.sleep(2.0); await shot("10_count_chat")
        await tap("Escape", 0.6); await tap("m", 1.2); await shot("11_map"); await tap("Escape", 0.4)
    frames = await record(p, plan, fps=12)
    fps = await p.js("MovieGame.fps()")
    answer = await p.js("(document.querySelector('.c-log')||{lastElementChild:{innerText:''}}).lastElementChild.innerText")
    have = await p.js("JSON.stringify(MovieGame.have)")
    await p.close()
    st = save_mp4(frames, DOCS / "game_walk.mp4")
    for f in shots.values():
        Image.open(f).convert("RGB").resize((960, 540), Image.LANCZOS).quantize(colors=200).save(f, optimize=True)
    st.update(fps_min=round(min(fps), 1), fps_mean=round(sum(fps) / len(fps), 1), answer=answer, clips=json.loads(have))
    print(json.dumps(st, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "checkpoint"
    asyncio.run({"checkpoint": checkpoint, "walk": walk}[cmd]())
