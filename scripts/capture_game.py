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


if __name__ == "__main__":
    asyncio.run({"checkpoint": checkpoint}[sys.argv[1] if len(sys.argv) > 1 else "checkpoint"]())
