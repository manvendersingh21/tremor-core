"""Capture site/docs/castle3d.gif and the proof screenshots for the 3D castle from a running server.

Real key events over the DevTools protocol: run to the gate, Enter opens it, walk in past the guide and the
savings board, climb the stairs, open the Dashboard door, then the Chat door and ask one question.
Mouse look is driven through Castle3D.look() (pointer lock does not exist headless).
  .venv/bin/python scripts/capture_castle.py [base_url] [question]
"""
import asyncio, io, json, math, sys, time
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).parent))
from cdp import Page

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "site" / "docs"
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
Q = sys.argv[2] if len(sys.argv) > 2 else "What is the capital of Poland?"
W, H, OUT_W = 1280, 720, 560
GL = ["--use-angle=metal"]  # the Mac GPU; use --use-angle=swiftshader on a machine without one


async def main():
    p = await Page.open(BASE + "/?dev", W, H, extra=GL)
    await asyncio.sleep(5)
    frames, rec = [], {"on": True, "dt": 0.14}

    async def recorder():
        while rec["on"]:
            t = time.monotonic()
            frames.append((t, await p.shot(fmt="jpeg")))
            await asyncio.sleep(max(0, rec["dt"] - (time.monotonic() - t)))

    async def hold(keys, s):
        for k in keys:
            await p.key(k)
        await asyncio.sleep(s)
        for k in keys:
            await p.key(k, False)

    async def turn(to, s=0.6, pitch=None):
        y0 = await p.js("Castle3D.state.yaw")
        n = max(1, int(s / 0.05))
        for i in range(1, n + 1):
            await p.js(f"Castle3D.look({y0 + (to - y0) * i / n}{', ' + str(pitch) if pitch is not None else ''})")
            await asyncio.sleep(0.05)

    async def tap(k, wait=0.5):
        await p.key(k); await p.key(k, False); await asyncio.sleep(wait)

    shots = {}
    async def shot(name):
        shots[name] = DOCS / f"castle_{name}.png"
        await p.shot(str(shots[name]))

    task = asyncio.create_task(recorder())
    await shot("1_outside")
    await hold(["Shift", "w"], 3.4)                       # run up to the gate
    await tap("Enter", 0.6); await shot("2_gate_opening")  # Enter opens it
    await asyncio.sleep(1.0)
    await hold(["Shift", "w"], 1.25)                      # walk into the Great Hall
    await turn(-0.55, 0.6); await asyncio.sleep(0.4); await shot("3_guide_desk")
    await turn(0.9, 0.9); await asyncio.sleep(0.5); await shot("4_savings_board")
    await turn(0.0, 0.6)
    await hold(["w"], 0.5); await shot("5_stairs")
    await hold(["Shift", "w"], 1.7)                       # climb the grand staircase
    await asyncio.sleep(0.3); await shot("6_three_doors")
    await hold(["Shift", "w"], 1.0)                       # to the Chat door (middle)
    await tap("e", 1.2)
    await p.js("document.getElementById('c-in').focus()"); await p.insert(Q); await asyncio.sleep(0.4)
    await p.js("document.getElementById('c-form').requestSubmit()")
    rec["dt"] = 2.0
    for _ in range(2400):
        await asyncio.sleep(0.1)
        if await p.js("!document.getElementById('c-send').disabled"):
            break
    rec["dt"] = 0.14
    await asyncio.sleep(1.5); await shot("8_chat")
    answer = await p.js("document.querySelector('.c-log').lastElementChild.innerText")
    await tap("Escape", 0.4)
    await hold(["a"], 1.9); await tap("e", 2.5); await shot("7_dashboard")   # the Dashboard door (left)
    await tap("Escape", 0.4)
    await hold(["d"], 3.8); await tap("e", 2.5); await shot("9_evals")      # the Evals door (right)
    fps = await p.js("Castle3D.fps()")
    rec["on"] = False
    await task
    await p.js("Castle3D.closePanel(); Castle3D.openMap()"); await asyncio.sleep(0.6); await shot("10_map")
    await p.close()

    imgs, durs = [], []
    for i, (t, data) in enumerate(frames):
        nxt = frames[i + 1][0] if i + 1 < len(frames) else t + 2
        im = Image.open(io.BytesIO(data)).convert("RGB").resize((OUT_W, OUT_W * H // W), Image.LANCZOS)
        imgs.append(im.quantize(colors=48, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
        durs.append(int(min(nxt - t, 0.16) * 1000))  # long model waits are sped up
    durs[-1] = 2500
    out = DOCS / "castle3d.gif"
    imgs[0].save(out, save_all=True, append_images=imgs[1:], duration=durs, loop=0, optimize=True)
    for f in shots.values():  # keep the screenshots small
        Image.open(f).convert("RGB").resize((960, 540), Image.LANCZOS).quantize(colors=160).save(f, optimize=True)
    stats = {"gif": str(out.relative_to(ROOT)), "frames": len(imgs), "seconds": round(sum(durs) / 1000, 1),
             "mb": round(out.stat().st_size / 1e6, 2), "fps_samples": [round(x, 1) for x in fps],
             "fps_min": round(min(fps), 1) if fps else None, "fps_mean": round(sum(fps) / len(fps), 1) if fps else None,
             "answer": answer}
    print(json.dumps(stats, indent=1))


asyncio.run(main())
