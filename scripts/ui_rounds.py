"""One polish round of the castle UI on Playwright: walk in, open every room, the chat cache test, the tour, and
robustness checks. Writes bench/.scratch/ui/rounds/<round>/<browser>_<view>_<mode>/ (screenshots + result.json).

Usage: .venv/bin/python scripts/ui_rounds.py <round> chromium|webkit desktop|phone demo|live [--url URL] [--full-tour] [--video]
  demo: every /api/* and /events request fails, as on the public link (GitHub Pages).
  live: the real backend on 127.0.0.1:8765; also checks that the page falls to DEMO when /api/stats goes down.
Run one browser at a time (memory). Needs `pip install playwright` and `playwright install chromium webkit`.
"""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BAD = ["pending", "NaN", "undefined", "[object", "null ", "Infinity", "could not", "Could not"]
SMALL_JS = """(min) => { let n = 0, ex = []; const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (w.nextNode()) { const t = w.currentNode, s = t.textContent.trim(); if (!s) continue; const e = t.parentElement;
    if (!e || !e.offsetParent && getComputedStyle(e).position !== 'fixed') continue; const r = e.getBoundingClientRect(); if (!r.width || r.bottom < 0 || r.top > innerHeight) continue;
    if (e.closest('[hidden]') || getComputedStyle(e).visibility === 'hidden' || +getComputedStyle(e).opacity === 0) continue;
    const cx = Math.min(innerWidth - 1, Math.max(0, r.left + r.width / 2)), cy = Math.min(innerHeight - 1, Math.max(0, r.top + Math.min(r.height, 20) / 2)), top = document.elementFromPoint(cx, cy);
    if (!top || !(top === e || e.contains(top) || top.contains(e))) continue;   // covered by something else: not seen
    const fs = parseFloat(getComputedStyle(e).fontSize); if (fs < min) { n++; if (ex.length < 8) ex.push(s.slice(0, 30) + ' @' + fs.toFixed(1)); } } return { n, ex }; }"""
NONAME_JS = """() => [...document.querySelectorAll('button, a, input, [role=button]')].filter((b) => b.offsetParent && !((b.getAttribute('aria-label') || b.innerText || b.title || b.value || '').trim())).map((b) => b.id || b.className).slice(0, 10)"""


def main():
    rnd, browser, view, mode = sys.argv[1:5]
    url = sys.argv[sys.argv.index('--url') + 1] if '--url' in sys.argv else 'http://127.0.0.1:8765/'
    full = '--full-tour' in sys.argv
    out = ROOT / 'bench/.scratch/ui/rounds' / rnd / f'{browser}_{view}_{mode}'
    out.mkdir(parents=True, exist_ok=True)
    R = {'round': rnd, 'browser': browser, 'view': view, 'mode': mode, 'url': url, 'checks': [], 'defects': [], 'timings': {}, 'shots': []}

    def check(name, ok, detail=''):
        R['checks'].append({'check': name, 'ok': bool(ok), 'detail': str(detail)[:400]})
        if not ok:
            R['defects'].append(f'{name}: {str(detail)[:300]}')
        print('PASS' if ok else 'FAIL', name, str(detail)[:200], flush=True)

    with sync_playwright() as pw:
        b = getattr(pw, browser).launch(args=['--no-sandbox'] if browser == 'chromium' else [])
        kw = dict(pw.devices['iPhone 13']) if view == 'phone' else {'viewport': {'width': 1280, 'height': 760}}
        if '--video' in sys.argv:
            kw['record_video_dir'] = str(out)
            kw['record_video_size'] = kw.get('viewport', {'width': 1280, 'height': 760})
        ctx = b.new_context(**kw)
        if mode == 'demo':
            ctx.route('**/api/**', lambda r: r.fulfill(status=404, body='not found'))
            ctx.route('**/events', lambda r: r.fulfill(status=404, body='not found'))
        p = ctx.new_page()
        errs, bad_req = [], []
        p.on('pageerror', lambda e: errs.append('pageerror: ' + str(e)))
        p.on('console', lambda m: m.type == 'error' and not ('404' in m.text or 'Failed to load resource' in m.text) and errs.append('console: ' + m.text))
        p.on('response', lambda r: r.status >= 400 and '/api/' not in r.url and '/events' not in r.url and bad_req.append(f'{r.status} {r.url}'))
        js = p.evaluate

        def shot(name):
            f = out / f'{name}.jpg'
            p.screenshot(path=str(f), type='jpeg', quality=72)
            R['shots'].append(str(f.relative_to(ROOT)))

        def page_text():
            t = js("document.getElementById('m-panel').hidden ? '' : document.getElementById('m-pbody').innerText")
            t += js("(() => { const f = document.querySelector('.m-dash'); try { return f ? f.contentDocument.body.innerText : '' } catch (e) { return '' } })()")
            return t

        def bad_words(where, text):
            hits = [w for w in BAD if w in text]
            check(f'{where}: no pending/NaN/undefined/error text', not hits, hits)

        t0 = time.time()
        p.goto(url, wait_until='domcontentloaded')
        p.wait_for_function('!!window.MovieGame', timeout=20000)
        R['timings']['game_ready_s'] = round(time.time() - t0, 2)
        time.sleep(0.8)
        fcp = js("""(() => { const e = performance.getEntriesByType('paint').find((x) => x.name === 'first-contentful-paint') || performance.getEntriesByType('paint')[0];
          if (e) return e.startTime; const n = performance.getEntriesByType('navigation')[0]; return n ? n.domContentLoadedEventEnd : null; })()""")
        R['timings']['first_contentful_paint_ms'] = fcp
        check('first paint under 2 s', fcp is not None and fcp < 2000, fcp)
        time.sleep(1.0)
        shot('01_landing')
        badge = js("(document.getElementById('m-mode') || {}).textContent || ''")
        check(f'{mode.upper()} badge shown', ('DEMO' in badge) if mode == 'demo' else ('LIVE' in badge), badge)
        check('walk prompt on the landing (Hold W, or the stick on touch)', any(w in js("document.getElementById('m-prompt').innerText") for w in ('Hold', 'Push the stick')) and js("document.getElementById('m-prompt').classList.contains('on')"))
        check('no horizontal overflow', js('document.documentElement.scrollWidth <= innerWidth + 1'), js('document.documentElement.scrollWidth + " vs " + innerWidth'))
        if view == 'phone':
            sm = js(SMALL_JS, 14)
            check('landing: no text under 14 px (phone)', sm['n'] == 0, sm)
        nn = js(NONAME_JS)
        check('every control has a name', not nn, nn)

        # the walk-in: hold W (or the joystick) from the landing to the Great Hall, resize once mid-walk
        w0 = time.time()
        if view == 'phone':
            r = js("(()=>{const b=document.getElementById('m-joy').getBoundingClientRect();return [b.left+b.width/2,b.top+b.height/2]})()")
            p.mouse.move(r[0], r[1]); p.mouse.down(); p.mouse.move(r[0], r[1] - 48, steps=3)
        else:
            p.keyboard.down('w')
        mid = False
        while time.time() - w0 < 12 and not js('MovieGame.state.hall'):
            if not mid and time.time() - w0 > 1.5:
                shot('02_mid_walk')
                if view == 'desktop':
                    p.set_viewport_size({'width': 1100, 'height': 700}); time.sleep(0.2); p.set_viewport_size({'width': 1280, 'height': 760})
                mid = True
            time.sleep(0.05)
        walk = round(time.time() - w0, 2)
        if view == 'phone':
            p.mouse.up()
        else:
            p.keyboard.up('w')
        R['timings']['walk_in_s'] = walk
        check('walk-in to the Great Hall in 4.5 s or less (W held)', js('MovieGame.state.hall') and walk <= 4.5, walk)
        check('gates and door opened on the way', js('MovieGame.state.open.gates && MovieGame.state.open.door'))
        time.sleep(2.5)
        shot('03_hall')
        board = js("document.getElementById('m-board').innerText")
        check('savings board has numbers', 'Tokens kept off' in board and any(c.isdigit() for c in board), board.replace('\n', ' | ')[:200])
        bad_words('savings board', board)
        if view == 'phone':
            sm = js(SMALL_JS, 14)
            check('hall: no text under 14 px (phone)', sm['n'] == 0, sm)

        # every room
        doors = js('MovieGame.doors.map(d => [d.id, d.title])')
        R['rooms'] = []
        for k, (rid, title) in enumerate(doors):
            js(f'MovieGame.state.door={k}; MovieGame.use()')
            p.wait_for_function("!document.getElementById('m-panel').hidden", timeout=15000)
            time.sleep(4.0 if js("!!document.querySelector('.m-dash')") else 2.5)
            got = js("document.getElementById('m-ptitle').textContent")
            check(f'opens {title}', got == title, got)
            txt = page_text()
            bad_words(title, txt)
            if js("!!document.querySelector('.m-dash')"):
                n = js("(()=>{const f=document.querySelector('.m-dash');try{return f.contentDocument.body.innerText.length}catch(e){return -1}})()")
                check(f'{title}: dashboard has content', n > 300, n)
            if view == 'phone':
                sm = js(SMALL_JS, 14)
                check(f'{title}: no text under 14 px (phone)', sm['n'] == 0, sm)
            shot(f'10_room_{k:02d}_{rid}')
            R['rooms'].append({'id': rid, 'title': title, 'chars': len(txt)})
            p.keyboard.press('Escape'); time.sleep(1.0)
            check(f'Esc leaves {title}', js('!MovieGame.state.panel && !MovieGame.state.room'))

        # map
        p.keyboard.press('m'); time.sleep(0.4); check('M opens the map', js('MovieGame.state.map')); shot('20_map')
        p.keyboard.press('Escape'); time.sleep(0.3)

        # chat: the cache test (Ask twice)
        p.keyboard.press('c'); time.sleep(1.2)
        check('C opens the Count chat', js('!!MovieGame.state.panel'))
        if mode == 'demo':
            time.sleep(1.0)
            check('demo chat shows saved questions', js("!document.getElementById('c-chips').hidden"), js("document.getElementById('c-chips').innerText")[:120])
        else:
            p.fill('#c-in', f'Name one river that flows through Paris. (UI check {rnd} {int(time.time())})')   # new each run: a real miss first
        p.click('#c-twice')
        for _ in range(900):
            time.sleep(0.2)
            if js("!!document.querySelector('.c-cmp table') && !document.getElementById('c-twice').disabled"):
                break
        cmp = js("(document.querySelector('.c-cmp') || {}).innerText || ''")
        check('Ask twice shows the cache test', 'Cache test' in cmp and '2nd ask' in cmp, cmp.replace('\n', ' | ')[:300])
        check('second answer came from the cache', 'came from the cache' in cmp, cmp.replace('\n', ' | ')[-200:])
        bad_words('chat', js("document.getElementById('m-pbody').innerText"))
        shot('30_chat_cache_test')
        p.keyboard.press('Escape'); time.sleep(0.8)

        # the tour
        js('MovieGame.jump(0,false)'); time.sleep(0.6)
        p.keyboard.press('t')
        tt = time.time()
        stops_seen = []
        limit = 260 if full else 40
        while time.time() - tt < limit:
            n = js("(document.getElementById('m-tour-n')||{}).textContent||''")
            if n and (not stops_seen or stops_seen[-1] != n):
                stops_seen.append(n)
                if full or len(stops_seen) <= 4:
                    time.sleep(1.2); shot(f'40_tour_{len(stops_seen):02d}')
            if 'over' in n:
                break
            time.sleep(0.3)
        R['timings']['tour_s'] = round(time.time() - tt, 1)
        R['tour_stops'] = stops_seen
        check('tour starts with T and moves through stops', len(stops_seen) >= (13 if full else 3), stops_seen[-3:])
        if full:
            check('tour ends (about 3 minutes)', any('over' in s for s in stops_seen) and 150 <= R['timings']['tour_s'] <= 225, R['timings']['tour_s'])
            check('tour ends on the cost chart', js("!!document.querySelector('.m-cost')"))
        p.keyboard.press('Escape'); time.sleep(0.5); p.keyboard.press('Escape'); time.sleep(0.8)
        check('Esc ends the tour', not js('window.CastleTour.running()'))

        # fps: stand on the landing and in the hall
        js('MovieGame.jump(0,false)'); time.sleep(4)
        js('MovieGame.jump(MovieGame.segs.length-1,true)'); js('MovieGame.enterHall()'); time.sleep(4)
        f = sorted(js('MovieGame.fps()') or [0])[-8:]
        med = f[len(f) // 2] if f else 0
        R['timings']['fps_median_last8'] = med
        floor = 57 if view == 'desktop' else 30
        check(f'{floor}+ fps (median of the last 8 s)', med >= floor, f'median {med:.1f}, min {min(f):.1f}')

        # the backend goes down mid-session: the page must fall to DEMO, not break
        if mode == 'live':
            ctx.route('**/api/stats', lambda r: r.fulfill(status=503, body='{}'))
            time.sleep(7)
            badge = js("document.getElementById('m-mode').textContent")
            check('backend down mid-session: badge falls to DEMO', 'DEMO' in badge, badge)
            board = js("document.getElementById('m-board').innerText")
            check('backend down: savings board still shows numbers', 'Tokens kept off' in board, board[:120])
            shot('50_backend_down')
        check('no page or console errors', not errs, '; '.join(errs)[:400])
        check('no failed asset requests', not bad_req, '; '.join(bad_req)[:400])
        ctx.close(); b.close()
    (out / 'result.json').write_text(json.dumps(R, indent=1))
    print(json.dumps({'defects': len(R['defects']), 'timings': R['timings']}))


main()
