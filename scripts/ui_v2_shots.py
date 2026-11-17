"""Screenshots for site/docs/ui_rework_v2.md: the landing, the walk (frames every 0.25 s while W is held, with the
walk position, so a jump back shows), the minimap, the Count chat, a room, the map and the tour.

Usage: .venv/bin/python scripts/ui_v2_shots.py <tag> chromium|webkit desktop|phone [--url URL] [--video]
Writes site/docs/v2/<tag>_<browser>_<view>_*.jpg and bench/.scratch/ui/v2/<tag>_<browser>_<view>.json.
Every /api/* request fails, as on GitHub Pages. One browser at a time (memory).
"""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
POS = """(() => { const S = MovieGame.state; return { s: +(S.s != null ? S.s : S.seg + S.t / MovieGame.segs[S.seg].secs).toFixed(3),
  hall: !!S.hall, gates: !!S.open.gates, door: !!S.open.door, yaw: +(S.yaw || 0).toFixed(3) }; })()"""


def main():
    tag, browser, view = sys.argv[1:4]
    url = sys.argv[sys.argv.index('--url') + 1] if '--url' in sys.argv else 'https://manvendersingh21.github.io/tremor-core/'
    docs = ROOT / 'site/docs/v2'
    docs.mkdir(parents=True, exist_ok=True)
    scratch = ROOT / 'bench/.scratch/ui/v2'
    scratch.mkdir(parents=True, exist_ok=True)
    name = f'{tag}_{browser}_{view}'
    R = {'tag': tag, 'browser': browser, 'view': view, 'url': url, 'walk': [], 'shots': [], 'errors': []}
    with sync_playwright() as pw:
        args = ['--no-sandbox', '--enable-gpu', '--use-angle=metal', '--ignore-gpu-blocklist'] if browser == 'chromium' else []
        b = getattr(pw, browser).launch(args=args)
        kw = dict(pw.devices['iPhone 13']) if view == 'phone' else {'viewport': {'width': 1280, 'height': 760}}
        if '--video' in sys.argv:
            kw['record_video_dir'] = str(scratch / name)
            kw['record_video_size'] = kw.get('viewport', {'width': 1280, 'height': 760})
        ctx = b.new_context(**kw)
        ctx.route('**/api/**', lambda r: r.fulfill(status=404, body='not found'))
        ctx.route('**/events', lambda r: r.fulfill(status=404, body='not found'))
        p = ctx.new_page()
        p.on('pageerror', lambda e: R['errors'].append(str(e)))
        js = p.evaluate

        def shot(n, clip=None):
            f = docs / f'{name}_{n}.jpg'
            p.screenshot(path=str(f), type='jpeg', quality=78, clip=clip)
            R['shots'].append(str(f.relative_to(ROOT)))

        p.goto(url, wait_until='domcontentloaded')
        p.wait_for_function('!!window.MovieGame', timeout=30000)
        time.sleep(2.5)
        R['gl'] = js("""(() => { try { const c = document.createElement('canvas').getContext('webgl2') || document.createElement('canvas').getContext('webgl');
          const d = c.getExtension('WEBGL_debug_renderer_info'); return d ? c.getParameter(d.UNMASKED_RENDERER_WEBGL) : 'webgl'; } catch (e) { return 'none'; } })()""")
        shot('01_landing')
        mini = js("(() => { const e = document.getElementById('m-mini') || document.querySelector('.m-minimap'); if (!e) return null; const r = e.getBoundingClientRect(); return {x: r.left - 6, y: r.top - 6, width: r.width + 12, height: r.height + 12}; })()")
        if mini:
            shot('02_minimap', clip=mini)
        vw = js('innerWidth'); vh = js('innerHeight')
        def drag(dx, dy=0):   # look around by dragging (the same as the mouse with the pointer locked)
            p.mouse.move(vw / 2, vh / 2); p.mouse.down(); p.mouse.move(vw / 2 + dx, vh / 2 + dy, steps=10); p.mouse.up()
        if js('MovieGame.state.yaw') is not None:
            for side_name, dx in (('left', -420), ('right', 840), ('behind', None)):
                if dx is None:
                    js('MovieGame.state.yaw = Math.PI')   # straight behind you: the road you came on
                else:
                    drag(dx)
                time.sleep(0.8)
                shot(f'03_look_{side_name}')
                R.setdefault('look', []).append({side_name: js('MovieGame.state.yaw')})
            js('MovieGame.state.yaw = 0; MovieGame.state.pitch = 0.06')
            time.sleep(0.6)
        # the walk: hold W, a frame every 0.25 s with the position
        if view == 'phone':
            r = js("(()=>{const b=document.getElementById('m-joy').getBoundingClientRect();return [b.left+b.width/2,b.top+b.height/2]})()")
            p.mouse.move(r[0], r[1]); p.mouse.down(); p.mouse.move(r[0], r[1] - 48, steps=3)
        else:
            p.keyboard.down('w')
        t0 = time.time()
        k = 0
        while time.time() - t0 < 8:
            pos = js(POS)
            pos['t'] = round(time.time() - t0, 2)
            R['walk'].append(pos)
            if k % 2 == 0 and k <= 24:
                shot(f'10_walk_{k:02d}')
            k += 1
            if pos['hall'] and time.time() - t0 > 0.3:
                R['hall_at_s'] = pos['t']
                break
            time.sleep(0.25)
        if view == 'phone':
            p.mouse.up()
        else:
            p.keyboard.up('w')
        back = [a['s'] for a in R['walk']]
        if js('!!(MovieGame.world)'):
            js('MovieGame.jump(2, false)'); time.sleep(0.8)
            js('MovieGame.state.yaw = Math.PI; MovieGame.state.pitch = 0.05'); time.sleep(0.8)
            shot('15_gates_open_behind')
            p.keyboard.press('e'); time.sleep(1.0)
            R['gates_closed'] = js('!MovieGame.state.open.gates && MovieGame.state.anim.gates === 0')
            shot('16_gates_closed_behind')
            js('MovieGame.state.yaw = 0'); js('MovieGame.jump(4, true)'); time.sleep(1.0)
        R['jumped_back'] = [(a, b2) for a, b2 in zip(back, back[1:]) if b2 < a - 0.01]
        time.sleep(1.5)
        shot('20_hall')
        if js('!!(MovieGame.world)'):
            js('MovieGame.state.yaw = Math.PI; MovieGame.state.pitch = 0.05')   # turn round inside: the great door, open
            time.sleep(0.7)
            shot('22_door_open_behind')
            p.keyboard.press('e')
            time.sleep(1.2)
            R['door_closed'] = js('!MovieGame.state.open.door && MovieGame.state.anim.door === 0')
            shot('23_door_closed_behind')
            for a in (-0.9, 0.9):
                js(f'MovieGame.state.yaw = {a}; MovieGame.state.pitch = 0.25')
                time.sleep(0.6)
                shot(f'24_hall_look_{"right" if a < 0 else "left"}_up')
            js('MovieGame.state.yaw = 0; MovieGame.state.pitch = 0')
        if mini:
            mini = js("(() => { const e = document.getElementById('m-mini') || document.querySelector('.m-minimap'); const r = e.getBoundingClientRect(); return {x: r.left - 6, y: r.top - 6, width: r.width + 12, height: r.height + 12}; })()")
            shot('21_minimap_hall', clip=mini)
        js('void MovieGame.talk()')
        time.sleep(2)
        shot('30_chat')
        if js("!!document.querySelector('.c-chip-q')"):
            p.click('.c-chip-q')
            time.sleep(0.7)
            shot('31_chat_climbing')
            time.sleep(2.5)
            shot('32_chat_answered')
        js('MovieGame.closePanel()')
        time.sleep(0.6)
        js("(() => { const k = MovieGame.doors.findIndex((d) => d.id === 'crypt'); MovieGame.state.door = k; void MovieGame.use(); })()")
        time.sleep(7)
        shot('40_room_crypt')
        js('MovieGame.closePanel()')
        time.sleep(1.2)
        js('MovieGame.openMap()')
        time.sleep(0.8)
        shot('50_map')
        p.keyboard.press('Escape')
        time.sleep(0.5)
        if js('!!window.CastleTour'):
            js('void CastleTour.start()')   # start() resolves when the 3-minute tour ends: do not wait for it
            time.sleep(6)
            shot('60_tour')
            js('CastleTour.stop()')
        R['fps'] = js('MovieGame.fps()')
        ctx.close()
        b.close()
    (scratch / f'{name}.json').write_text(json.dumps(R, indent=1))
    print(json.dumps({k: R[k] for k in ('gl', 'hall_at_s', 'jumped_back', 'errors', 'gates_closed', 'door_closed', 'look') if k in R}, indent=1))
    print('fps', R.get('fps', [])[-5:])


if __name__ == '__main__':
    main()
