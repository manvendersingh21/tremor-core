"""Time the walk-in on Chrome (DevTools) or WebKit (Playwright): hold W from page load and log when the gates open,
the great door opens, you are inside the Great Hall (its stretch is on screen) and the hall doors show. Presses E only
when the walk is stuck at a closed gate or door for 0.6 s (the old pacing needed that; e_presses counts them). Also the frame rate while walking.

  scripts/ui_pace.py chrome|webkit [walk|run] [--video out.webm]   (the page must be up on 127.0.0.1:8765)
Writes bench/.scratch/ui/pace_<browser>_<mode>.json and prints it."""
import asyncio, json, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'bench/.scratch/ui'
OUT.mkdir(parents=True, exist_ok=True)
B = 'http://127.0.0.1:8765/'
STATE = "JSON.stringify({seg: MovieGame.state.seg, gates: !!MovieGame.state.open.gates, door: !!MovieGame.state.open.door, hall: MovieGame.state.hall, ask: document.getElementById('m-prompt').classList.contains('on') && /Open/.test(document.getElementById('m-prompt').textContent), fps: MovieGame.fps().slice(-1)[0] || 0, t: MovieGame.state.t})"


async def drive(js, key, run, limit=60):
    marks, fps, last_e, last_pos, still_since = {}, [], 0, None, 0
    await asyncio.sleep(1.0)
    st0 = json.loads(await js(STATE))
    marks['gates_closed_at_load'] = not st0['gates']
    marks['door_closed_at_load'] = not st0['door']
    if run:
        await key('Shift', True)
    await key('w', True)
    t0 = time.monotonic()
    segs = await js('MovieGame.segs.map(s=>s.id)')
    hall_seg = len(segs) - 1
    while time.monotonic() - t0 < limit:
        st = json.loads(await js(STATE))
        now = round(time.monotonic() - t0, 2)
        if st['gates'] and 'gates_open' not in marks:
            marks['gates_open'] = now
        if st['door'] and 'door_open' not in marks:
            marks['door_open'] = now
        if st['seg'] == hall_seg and 'inside_hall' not in marks:
            marks['inside_hall'] = now
        if st['hall'] and 'hall_doors' not in marks:
            marks['hall_doors'] = now
            break
        pos = (st['seg'], round(st['t'], 3))
        if pos != last_pos:
            last_pos, still_since = pos, now
        if st['ask'] and now - still_since > 0.6 and now - last_e > 0.6:   # stuck at a closed gate or door (the old pacing): E
            await key('e', True); await key('e', False); last_e = now
            marks.setdefault('e_presses', 0); marks['e_presses'] += 1
        fps.append(st['fps'])
        await asyncio.sleep(0.05)
    await key('w', False)
    if run:
        await key('Shift', False)
    # S walks back out of the hall stretch
    await js('MovieGame.jump(MovieGame.segs.length - 1, false); MovieGame.state.t = 0.5'); await asyncio.sleep(0.5)
    seg_before = await js('MovieGame.state.seg')
    await key('s', True); await asyncio.sleep(1.2); await key('s', False)
    marks['s_walks_back'] = (await js('MovieGame.state.seg')) < seg_before
    f = sorted(x for x in fps if x)
    marks['fps_median'] = f[len(f) // 2] if f else None
    marks['fps_min'] = f[0] if f else None
    return marks


async def chrome(run):
    sys.path.insert(0, str(ROOT / 'scripts'))
    from cdp import Page
    p = await Page.open(B, 1280, 720, extra=['--use-angle=metal'])
    await asyncio.sleep(6)

    async def js(e):
        return await p.js(e)

    async def key(k, down):
        await p.key(k, down)
    m = await drive(js, key, run)
    await p.close()
    return m


async def webkit(run, video=None):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b = await pw.webkit.launch()
        kw = {'viewport': {'width': 1280, 'height': 720}}
        if video:
            kw.update(record_video_dir=str(OUT / 'pace_video'), record_video_size={'width': 1280, 'height': 720})
        ctx = await b.new_context(**kw)
        p = await ctx.new_page()
        await p.goto(B); await asyncio.sleep(6)

        async def js(e):
            return await p.evaluate(e)

        async def key(k, down):
            await (p.keyboard.down if down else p.keyboard.up)(k)
        m = await drive(js, key, run)
        if video:
            await asyncio.sleep(1.5)
            path = await p.video.path()
            await ctx.close()
            Path(path).replace(video)
            m['video'] = str(video)
        await b.close()
    return m


if __name__ == '__main__':
    which, mode = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else 'walk')
    video = sys.argv[sys.argv.index('--video') + 1] if '--video' in sys.argv else None
    m = asyncio.run(chrome(mode == 'run') if which == 'chrome' else webkit(mode == 'run', video))
    m.update(browser=which, mode=mode)
    (OUT / f'pace_{which}_{mode}.json').write_text(json.dumps(m, indent=1))
    print(json.dumps(m))
