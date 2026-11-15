"""The castle e2e on Playwright. Usage: scripts/ui_e2e.py webkit|chromium desktop|iphone (needs `pip install playwright` and `playwright install webkit`; the page must be up on 127.0.0.1:8765). Writes bench/.scratch/ui/e2e_<browser>_<view>.json"""
import json, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'bench/.scratch/ui'
OUT.mkdir(parents=True, exist_ok=True)
B = 'http://127.0.0.1:8765/'
R = []


def check(name, ok, detail=''):
    R.append({'check': name, 'ok': bool(ok), 'detail': str(detail)})
    print('PASS' if ok else 'FAIL', name, detail, flush=True)


def main(browser, view):
    with sync_playwright() as pw:
        bt = getattr(pw, browser)
        b = bt.launch()
        if view == 'iphone':
            ctx = b.new_context(**pw.devices['iPhone 13'])
        else:
            ctx = b.new_context(viewport={'width': 1280, 'height': 760})
        p = ctx.new_page()
        errs = []
        p.on('pageerror', lambda e: errs.append(str(e)))
        p.goto(B); time.sleep(5)
        js = p.evaluate
        S = 'MovieGame.state'
        check('game started', js('!!window.MovieGame'), js('navigator.userAgent'))
        check('no horizontal overflow', js('document.documentElement.scrollWidth <= innerWidth + 1'), js('document.documentElement.scrollWidth + " vs " + innerWidth'))
        check('clip a-approach can play', js('MovieGame.have["a-approach"]'), js('document.getElementById("m-v0").canPlayType("video/mp4")'))
        t0 = js(f'{S}.t')
        if view == 'iphone':
            r = js("(()=>{const b=document.getElementById('m-joy').getBoundingClientRect();return [b.left+b.width/2,b.top+b.height/2]})()")
            p.mouse.move(r[0], r[1]); p.mouse.down(); p.mouse.move(r[0], r[1] - 45, steps=4)
            time.sleep(2.5); joy = js(f'{S}.joy.y'); p.mouse.up()
            t1 = js(f'{S}.t')
            check('joystick walks', joy < -0.3 and t1 > t0 + 0.5, f'joy.y={joy} t {t0:.2f}->{t1:.2f}')
        else:
            p.keyboard.down('w'); time.sleep(2.5); p.keyboard.up('w')
            t1 = js(f'{S}.t'); check('W walks forward', t1 > t0 + 0.5, f't {t0:.2f}->{t1:.2f}')
            p.keyboard.down('s'); time.sleep(1.0); p.keyboard.up('s')
            t2 = js(f'{S}.t'); check('S walks back', t2 < t1, f't {t1:.2f}->{t2:.2f}')
            p.keyboard.down('d'); time.sleep(0.3); p.keyboard.up('d')
            check('A/D look moves yaw', js(f'Math.abs({S}.yaw) > 0.001'), js(f'{S}.yaw'))
        js('MovieGame.jump(0,true)'); time.sleep(1)
        if view == 'iphone':
            p.tap('#m-act')
        else:
            p.keyboard.press('e')
        time.sleep(0.5); check('E opens the gates', js(f'!!{S}.open.gates'))
        js('MovieGame.jump(3,true)'); time.sleep(1); p.keyboard.press('e'); time.sleep(0.5)
        check('E opens the great door', js(f'!!{S}.open.door'))
        js('MovieGame.jump(4,true)'); time.sleep(1.5); js('MovieGame.enterHall()'); time.sleep(3)
        check('hall shows doors', js("!document.getElementById('m-doors').hidden"))
        board = js("document.getElementById('m-board').innerText")
        check('savings board has live totals', 'Tokens kept off' in board, board.replace('\n', ' | ')[:160])
        names = js("[...document.querySelectorAll('.m-door strong')].map(e=>e.textContent)")
        for room in ['The Ledger', 'The Ladder', 'The Observatory']:
            k = names.index(room)
            js(f'{S}.door={k}; document.querySelectorAll(".m-door")[{k}].click()'); time.sleep(7)
            txt = js("document.getElementById('m-ptitle').textContent")
            check(f'opens {room}', txt == room, txt)
            d = js("(()=>{const f=document.querySelector('.m-dash');try{return f?f.contentDocument.body.innerText.length:0}catch(e){return -1}})()")
            check(f'{room} dashboard has content', d > 300, d)
            p.screenshot(path=str(OUT / f'pw_{browser}_{view}_{room.split()[-1]}.png'))
            p.keyboard.press('Escape'); time.sleep(1.2)
            check(f'Esc leaves {room}', js(f'!{S}.panel && !{S}.room'))
            js('MovieGame.enterHall()'); time.sleep(0.5)
        p.keyboard.press('m'); time.sleep(0.5); check('M opens the map', js(f'{S}.map'))
        p.keyboard.press('Escape'); time.sleep(0.5); check('Esc closes the map', js(f'!{S}.map'))
        check('minimap drawn', js("(()=>{const c=document.getElementById('m-mini');const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;let n=0;for(let i=3;i<d.length;i+=4)if(d[i])n++;return n>500&&c.getBoundingClientRect().width>0})()"))
        p.keyboard.press('t'); time.sleep(1.5); check('T opens the Count chat', js(f'!!{S}.panel'))
        q = 'What is the capital of Italy?'
        p.fill('#c-in', q); p.press('#c-in', 'Enter')
        for _ in range(1500):
            time.sleep(0.2)
            if js("!document.getElementById('c-send').disabled"):
                break
        time.sleep(1)
        ans = js("document.getElementById('m-pbody').innerText")
        check('Count answers a real question', 'Rome' in ans, ans[-160:].replace('\n', ' | '))
        p.screenshot(path=str(OUT / f'pw_{browser}_{view}_chat.png'))
        p.keyboard.press('Escape'); time.sleep(5)
        f = sorted(js('MovieGame.fps()') or [0])
        med = f[len(f) // 2]
        check('50+ fps (median)', med >= 50, f'median {med:.1f}, min {f[0]:.1f}, n={len(f)}')
        check('no page errors', not errs, '; '.join(errs)[:300])
        b.close()
    (OUT / f'e2e_{browser}_{view}.json').write_text(json.dumps(R, indent=1))


main(sys.argv[1], sys.argv[2])
