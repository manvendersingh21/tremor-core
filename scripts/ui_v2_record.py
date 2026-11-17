"""Record the walk-in for site/docs/ui_rework_v2.md: look round outside the closed gates, hold W to the Great Hall
(gates and door open as you reach them), turn round, press E to shut the great door, turn back.

Usage: .venv/bin/python scripts/ui_v2_record.py chromium|webkit [--url URL] [--out site/docs/ui_rework_v2_walk.mp4]
Needs ffmpeg. Every /api/* request fails, as on GitHub Pages. Writes a JSON log of the walk next to the video.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def main():
    browser = sys.argv[1]
    url = sys.argv[sys.argv.index('--url') + 1] if '--url' in sys.argv else 'https://manvendersingh21.github.io/tremor-core/'
    out = ROOT / (sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else 'site/docs/ui_rework_v2_walk.mp4')
    tmp = ROOT / 'bench/.scratch/ui/v2/video' / browser
    tmp.mkdir(parents=True, exist_ok=True)
    log = []
    with sync_playwright() as pw:
        b = getattr(pw, browser).launch(args=['--no-sandbox'] if browser == 'chromium' else [])
        ctx = b.new_context(viewport={'width': 1280, 'height': 720}, record_video_dir=str(tmp), record_video_size={'width': 1280, 'height': 720})
        ctx.route('**/api/**', lambda r: r.fulfill(status=404, body='not found'))
        ctx.route('**/events', lambda r: r.fulfill(status=404, body='not found'))
        p = ctx.new_page()
        t_open = time.time()
        p.goto(url, wait_until='domcontentloaded')
        p.wait_for_function('!!window.MovieGame', timeout=30000)
        js = p.evaluate
        mark = lambda what: log.append({'t': round(time.time() - t_open, 2), 'what': what, 's': js('MovieGame.state.s'), 'z': round(js('MovieGame.z()'), 2),
                                        'gates': js('MovieGame.state.open.gates'), 'door': js('MovieGame.state.open.door'), 'yaw': round(js('MovieGame.state.yaw'), 2)})
        time.sleep(2.0)
        mark('landing, gates shut')

        def turn(total, secs):   # turn the head smoothly, as the mouse does
            n = int(secs * 30)
            for _ in range(n):
                js(f'MovieGame.look({total / n})')
                time.sleep(1 / 30)
        turn(0.9, 1.2); mark('looked left'); turn(-1.8, 2.0); mark('looked right'); turn(0.9, 1.0); mark('ahead again')
        p.keyboard.down('w')
        w0 = time.time()
        while not js('MovieGame.state.hall') and time.time() - w0 < 10:
            time.sleep(0.05)
        mark(f'in the Great Hall after {time.time() - w0:.2f} s of W')
        time.sleep(1.2)
        p.keyboard.up('w')
        mark('stopped in the hall')
        turn(3.1416, 1.6); mark('turned round: the great door is open')
        p.keyboard.press('e'); time.sleep(1.6); mark('E: the great door shut')
        turn(-3.1416, 1.6); turn(0.5, 0.8); mark('looking at the hall again')
        time.sleep(1.0)
        video = p.video.path()
        ctx.close()
        b.close()
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', video, '-vf', 'scale=1280:-2', '-c:v', 'libx264', '-crf', '28', '-preset', 'slow', '-pix_fmt', 'yuv420p', '-an', str(out)], check=True)
    out.with_suffix('.json').write_text(json.dumps({'browser': browser, 'url': url, 'log': log}, indent=1))
    print(json.dumps(log, indent=1))
    print(out, out.stat().st_size // 1024, 'KB')


if __name__ == '__main__':
    main()
