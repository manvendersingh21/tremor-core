"""Capture site/docs/walk.gif and walk_map.png from a running server (default http://127.0.0.1:8798).

Drives the walkable castle with real key events over the DevTools protocol: walk the hall (WASD), climb the
stairs, enter the Observatory, leave, travel to the bat, ask a question (cache miss, model answers), then ask it
again (cache hit). Needs Chrome or the Playwright headless shell, and a server with /api/chat.
  .venv/bin/python scripts/capture_walk.py [base_url] [question]
"""
import asyncio, io, sys, time
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).parent))
from cdp import Page

ROOT = Path(__file__).resolve().parent.parent
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8798"
Q = sys.argv[2] if len(sys.argv) > 2 else "What is the largest planet in our solar system?"
W, H, OUT_W = 1280, 720, 560
DUMP = __import__("os").environ.get("DUMP")


async def main():
    import urllib.request  # warm the embedder and models first so the GIF shows real lookup times, not a cold start
    try:
        urllib.request.urlopen(urllib.request.Request(BASE + "/api/chat", data=b'{"prompt": "Say hello."}',
                               headers={"Content-Type": "application/json"}), timeout=200).read()
    except Exception as e:  # noqa: BLE001
        print("warm-up failed:", type(e).__name__)
    p = await Page.open(BASE + "/world/index.html", W, H)
    await asyncio.sleep(3)
    frames, rec = [], {"on": True}

    async def recorder():
        while rec["on"]:
            t = time.monotonic()
            frames.append((t, await p.shot(fmt="jpeg")))
            await asyncio.sleep(max(0, rec.get("dt", 0.11) - (time.monotonic() - t)))  # slow while a model thinks

    async def hold(keys, s):
        for k in keys: await p.key(k)
        await asyncio.sleep(s)
        for k in keys: await p.key(k, False)

    task = asyncio.create_task(recorder())
    await hold(["a"], 0.3); await hold(["d"], 0.3)                      # A / D: look around the courtyard
    await hold(["Shift", "s"], 2.3)                                     # run S through the hall to the grand stairs
    await hold(["s"], 0.6)                                              # step onto the stairs: fade up to floor 1
    await asyncio.sleep(0.5)
    await hold(["d"], 0.75); await hold(["w"], 0.9)                     # walk to the Observatory door and push in
    await asyncio.sleep(1.6)                                            # live dashboard panel
    await p.key("Escape"); await p.key("Escape", False); await asyncio.sleep(0.6)
    await p.key("m"); await p.key("m", False); await asyncio.sleep(0.9)  # fast travel list
    await p.js("document.querySelector('[data-room=agent]').click()"); await asyncio.sleep(1.0)
    traces = []
    for q, wait in ((Q, 150), (Q, 20)):
        await p.js("document.getElementById('c-in').focus()")
        await p.insert(q); await asyncio.sleep(0.4)
        await p.js("document.getElementById('c-form').requestSubmit()")
        await asyncio.sleep(1.2); rec["dt"] = 1.5
        for _ in range(wait * 10):
            await asyncio.sleep(0.1)
            if await p.js("!document.getElementById('c-send').disabled"): break
        rec["dt"] = 0.11
        await asyncio.sleep(1.8)
        traces.append(await p.js("document.getElementById('c-trace').innerText"))
    rec["on"] = False; await task
    await p.close()
    draw_map(ROOT / "site/docs/walk_map.png")

    # long waits (model thinking) are sped up in the GIF but stay in order
    imgs, durs = [], []
    for i, (t, data) in enumerate(frames):
        nxt = frames[i + 1][0] if i + 1 < len(frames) else t + 1.5
        if DUMP and i % 8 == 0:
            open(f"{DUMP}/f{i:03}.jpg", "wb").write(data)
        im = Image.open(io.BytesIO(data)).convert("RGB").resize((OUT_W, OUT_W * H // W), Image.LANCZOS)
        imgs.append(im.quantize(colors=40, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
        durs.append(int(min(nxt - t, 0.25) * 1000))  # model waits are sped up
    durs[-1] = 2500
    out = ROOT / "site/docs/walk.gif"
    imgs[0].save(out, save_all=True, append_images=imgs[1:], duration=durs, loop=0, optimize=True)
    print(f"{out}: {len(imgs)} frames, {sum(durs)/1000:.1f} s, {out.stat().st_size/1e6:.2f} MB")
    print("\n----\n".join(traces))

def draw_map(out):
    """All floors of site/world/map.json side by side, with doors, stairs, NPCs and room names."""
    import json
    from PIL import ImageDraw, ImageFont
    m = json.loads((ROOT / "site/world/map.json").read_text())
    T, pad = 14, 24
    col = {"#": "#2a1636", "t": "#e9a03a", "w": "#6a7ab8", "b": "#6a3a1c", "f": "#5a4a60", "~": "#31526e", "c": "#e9c46a",
           "D": "#ff6a8a", ".": "#4e3e58", ",": "#3e4250", "=": "#8a1a3a", "U": "#e9c46a", "d": "#b0a070"}
    ws = [len(f["rows"][0]) * T for f in m["floors"]]
    W, H = sum(ws) + pad * (len(ws) + 1), max(len(f["rows"]) for f in m["floors"]) * T + 90
    im = Image.new("RGB", (W, H), "#0b0510"); g = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 12)
    except OSError:
        font = ImageFont.load_default()
    x0 = pad
    for f, w in zip(m["floors"], ws):
        g.text((x0, 8), f"Floor {f['id'] + 1}: {f['name'].split(': ', 1)[-1]}", fill="#f4d58d", font=font)
        for y, row in enumerate(f["rows"]):
            for x, c in enumerate(row):
                if c != " ":
                    g.rectangle([x0 + x * T, 30 + y * T, x0 + x * T + T - 1, 30 + y * T + T - 1], fill=col.get(c, "#000"))
        for d in (d for d in m["doors"] if d["floor"] == f["id"]):
            g.text((x0 + d["stand"][0] * T + 2, 30 + d["stand"][1] * T + 2), m["rooms"][d["room"]]["title"].replace("The ", ""), fill="#ffffff", font=font)
        for n in (n for n in m["npcs"] if n["floor"] == f["id"]):
            cx, cy = x0 + n["x"] * T + T // 2, 30 + n["y"] * T + T // 2
            g.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill="#ff4060" if n["kind"] == "bat" else "#ffffff")
            g.text((cx + 7, cy - 6), "Bat agent" if n["kind"] == "bat" else "Count", fill="#ffd0d8", font=font)
        x0 += w + pad
    g.text((pad, H - 40), "pink: doors (rooms)   gold: stairs and candles   red dot: bat agent   white dot: the Count   red: carpet", fill="#d9c9e0", font=font)
    im.save(out, optimize=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--map":
        draw_map(ROOT / "site/docs/walk_map.png")
    else:
        asyncio.run(main())
