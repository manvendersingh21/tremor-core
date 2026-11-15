"""Clip smoothness and seams on WebKit (Playwright) and Chrome (CDP). Usage: scripts/ui_seams.py webkit|chrome (rerun when a clip lands in site/game/clips/)
For every clip in site/game/clips/: frames shown per second while W is held (requestVideoFrameCallback or
currentTime changes), distinct positions per second while S is held, and the pixel jump at each joint: the mean absolute
difference (0-255) of the screen, every live layer hidden, before and after the next stretch takes over."""
import asyncio, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'bench/.scratch/ui'
OUT.mkdir(parents=True, exist_ok=True)
B = 'http://127.0.0.1:8765/'

PROBE = """async (args) => {
  const [mode, secs] = args, S = MovieGame.state, v = () => document.querySelectorAll('#m-stage > video')[S.seg % 2];
  const seen = new Set(); let frames = 0, stalls = 0, last = performance.now(), lastT = -1;
  const t0 = performance.now();
  await new Promise((res) => { const step = () => { const now = performance.now(), ct = +v().currentTime.toFixed(3);
      if (ct !== lastT) { seen.add(ct); frames++; lastT = ct; if (now - last > 120) stalls++; last = now; }
      if (now - t0 < secs * 1000) requestAnimationFrame(step); else res(); }; requestAnimationFrame(step); });
  return { mode, per_s: frames / secs, distinct: seen.size, stalls, t: S.t, seg: S.seg };
}"""
HIDE = """(on) => { ['#m-fx', '.m-veil', '.m-anchor', '.m-say', '.m-prompt', '.m-bar', '#m-mini', '.m-help', '.m-fade', '.m-doors', '.m-board'].forEach((s) => document.querySelectorAll(s).forEach((e) => { e.style.visibility = on ? 'hidden' : ''; })); }"""
async def grab(js, shot):
    """The screen with every live layer hidden, as a 64x36 thumbnail: what you actually see of the painting."""
    import io
    from PIL import Image
    await js(f'({HIDE})(true)'); await asyncio.sleep(0.3)
    png = await shot()
    await js(f'({HIDE})(false)')
    return list(Image.open(io.BytesIO(png)).convert('RGB').resize((64, 36)).tobytes())


def mad(a, b):
    return None if a is None or b is None else round(sum(abs(x - y) for x, y in zip(a, b)) / len(a), 1)


async def run(js, key, browser, shot):
    have = await js('JSON.stringify(MovieGame.have)')
    have = json.loads(have)
    rows = []
    segs = await js('MovieGame.segs.map(s=>s.id)')
    for i, sid in enumerate(segs):
        if not have.get(sid):
            continue
        await js(f'MovieGame.jump({i}, false)'); await asyncio.sleep(1.2)
        await key('w', True); await asyncio.sleep(0.3)
        w = await js(f'({PROBE})(["W", 2.5])'); await key('w', False); await asyncio.sleep(0.3)
        await key('s', True); s = await js(f'({PROBE})(["S", 1.5])'); await key('s', False)
        # the joint into the next stretch: the last frame of this clip vs the first of the next
        await js(f'MovieGame.jump({i}, true)'); await asyncio.sleep(3.5)
        a = await grab(js, shot)
        if i + 1 < len(segs):
            await js(f'MovieGame.jump({i + 1}, false)'); await asyncio.sleep(1.5)
            b = await grab(js, shot)
        else:
            b = None
        # the same joint reached by walking: hold W to the end of the clip, then E (a gate or door) or keep walking
        walked = None
        if i + 1 < len(segs):
            await js(f'MovieGame.jump({i}, false)'); await asyncio.sleep(1.5)
            d = await js(f'document.querySelectorAll("#m-stage > video")[{i % 2}].duration')
            await key('w', True); await asyncio.sleep(d + 1.0); await key('w', False); await asyncio.sleep(0.6)
            c = await grab(js, shot)
            if await js(f'MovieGame.state.seg') == i:
                await key('e', True); await key('e', False)
            await asyncio.sleep(1.5)
            e = await grab(js, shot)
            walked = {'stopped_at_t': await js('MovieGame.state.t'), 'seg_after': await js('MovieGame.state.seg'), 'mad': mad(c, e)}
        rows.append({'browser': browser, 'clip': sid, 'W': w, 'S': s, 'joint_to': segs[i + 1] if i + 1 < len(segs) else None, 'joint_mad': mad(a, b), 'walked_joint': walked})
        print(json.dumps(rows[-1]), flush=True)
    return rows


async def chrome():
    sys.path.insert(0, str(ROOT / 'scripts'))  # cdp.py
    from cdp import Page
    p = await Page.open(B, 1280, 720, extra=['--use-angle=metal'])
    await asyncio.sleep(6)
    async def js(e): return await p.js(e)
    async def key(k, down): await p.key(k, down)
    rows = await run(js, key, 'chrome', p.shot)
    await p.close()
    return rows


async def webkit():
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b = await pw.webkit.launch(); p = await b.new_page(viewport={'width': 1280, 'height': 720}); await p.goto(B); await asyncio.sleep(6)
        async def js(e):
            return await p.evaluate(e)
        async def key(k, down):
            await (p.keyboard.down if down else p.keyboard.up)(k)
        rows = await run(js, key, 'webkit', p.screenshot)
        await b.close()
    return rows


if __name__ == '__main__':
    which = sys.argv[1]
    rows = asyncio.run(chrome() if which == 'chrome' else webkit())
    (OUT / f'seam_{which}.json').write_text(json.dumps(rows, indent=1))
