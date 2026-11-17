"""Record the Kiroween demo video (site/docs/demo_video.md): the castle walk, the Count's chat with its routing trace,
a cache hit, FizzBuzz on the 30B, a hard task that climbs to the 763B, the cost chart, the Workshop and a closing card.

Usage: .venv/bin/python scripts/demo_record.py [--url URL] [--closing-extra "TEXT (bench/results_a6000.md)"]
Needs ffmpeg. Writes site/docs/demo_cut.mp4 (1920x1080, 30 fps, captions burned in), site/docs/demo_cut.srt,
site/docs/demo_cut.json (shot times) and one still per shot in site/docs/demo_shots/.

The page runs in DEMO mode: every /api/* request fails, as on GitHub Pages, so no model and no GPU is called.
The DEMO chat replays saved events. For this recording its saved questions are swapped for real /api/chat events of
the tuned run behind bench/results_backend_v3.md (repeat 1, read from bench/.scratch/backend_v3/, git-ignored).
The page says on screen that it is a replay and names the file. Frames come from the DevTools screencast.
"""
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / 'bench/.scratch/backend_v3/repeats/ladder_r1'
TMP = ROOT / 'bench/.scratch/demo_video'
OUT = ROOT / 'site/docs'
W, H, FPS = 1920, 1080, 30
V3 = 'bench/results_backend_v3.md'
COST = 'bench/results_company_cost.md'


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def saved_examples():
    """The /api/chat events of the tuned run (repeat 1): COLD = first ask, WARM = the same question again, BASE = 763B alone."""
    rows = [json.loads(x) for x in (RUN / 'backend_rows.jsonl').read_text().splitlines() if x.strip()]
    tel = [json.loads(x) for x in (RUN / 'backend_telemetry.jsonl').read_text().splitlines() if x.strip()]
    if len(rows) != len(tel):
        raise SystemExit('rows and telemetry differ in length')
    by = {(r['pass'], r['id']): (r, t) for r, t in zip(rows, tel)}
    prompts = {p['id']: p for p in map(json.loads, (ROOT / 'bench/prompts.jsonl').read_text().splitlines()) if p}
    answers = json.loads((ROOT / 'bench/raw.json').read_text())['answers']
    ev = lambda t: [[e['step'], {k: v for k, v in e.items() if k != 'step'}] for e in t['events']]  # noqa: E731
    out = {}
    for pid in ('e2', 'c2', 'h2'):
        (cold, tc), (_, tw), (base, _) = by[('COLD', pid)], by[('WARM', pid)], by[('BASE', pid)]
        text = answers[f'A:{pid}']['answer'].replace('```python\n', '').replace('```', '').replace('**', '').replace('### ', '').strip()
        if len(text) > 420:
            text = text[:417].rsplit(' ', 1)[0] + '…'
        out[pid] = {'id': pid, 'q': prompts[pid]['prompt'], 'answer': text, 'first': ev(tc), 'repeat': ev(tw),
                    'base_ms': base['latency_ms'], 'base_tokens': base['big_in'] + base['big_out'], 'base_usd': base['dollars'],
                    'cold': cold}
    return out


def captions(X, K):
    e2, c2, h2 = X['e2'], X['c2'], X['h2']
    fin = lambda x: next(d for n, d in x['first'] if n == 'final')  # noqa: E731
    rep = lambda x: next(d for n, d in x['repeat'] if n == 'final')  # noqa: E731
    call30 = next(d for n, d in h2['first'] if n == 'draft')
    f2, fc, fh = fin(e2), fin(c2), fin(h2)
    s = lambda v: f'{v / 1000:.1f} s'  # noqa: E731
    return {
        'landing': [(0, 'CHIMERA sends each AI call to the cheapest helper that gets it right', ''),
                    (5.5, 'The gates are shut. Hold W to walk in.', '')],
        'walk': [(0, 'Hold W: the gates open as you reach them, then the great door', ''),
                 (6, 'The Great Hall. Each gold door is a room of measured numbers', 'site/game/')],
        'ask': [(0, 'Ask the Count. The call climbs a ladder: cache, then our 30B, then the 763B', ''),
                (9, f'Cache miss. Our own 30B answered: {s(f2["ms"])}, '
                    f'{f2["tokens_in"] + f2["tokens_out"]} tokens, $0 in tokens', V3)],
        'twice': [(0, 'Ask the same question again', ''),
                  (6, f'Cache hit: {s(rep(e2)["ms"])}, 0 tokens, $0. No model was called', V3)],
        'fizz': [(0, 'FizzBuzz does not need a frontier model', ''),
                 (6.5, f'Our 30B wrote it: {s(fc["ms"])}, {fc["tokens_in"] + fc["tokens_out"]} tokens, $0 in tokens', V3),
                 (14, f'The 763B alone: {s(c2["base_ms"])}, ${c2["base_usd"]:.5f}. Our GPU box: $0.18-0.52 per 1,000 calls',
                  V3 + ' · bench/results_akash_tuning.md')],
        'climb': [(0, 'A hard design task', ''),
                  (6.5, f'The 30B was unsure ({call30["confidence"]:.2f}, below {call30["gate"]:.2f}), so the call climbed to the 763B', V3),
                  (15, f'A loss: {s(fh["ms"])} against {s(h2["base_ms"])} for the 763B alone, at the same cost', V3)],
        'ledger': [(0, 'The bill: a month of coding calls', COST),
                   (8, 'With 30% repeats: 62% to 87% less than GPT-5.5 alone', COST),
                   (18, 'A loss: at 100,000 calls a day the cheap 763B alone costs less. We cost 607% more', COST)],
        'workshop': [(0, f'Built with Kiro: {len(K["steering"])} steering files, {len(K["specs"])} specs, {len(K["hooks"])} hooks, '
                         f'{len(K["agents"])} agents, MCP tools and a Power', '.kiro/'),
                     (10, f'Property tests from the specs found {K["bugs_found"]} real bugs. {K["bugs_fixed"]} are fixed', 'docs/handoff/property-tests.md')],
        'closing': [(0, 'Stop paying a frontier model for FizzBuzz. We prove it with tests.', '')],
    }


SHOTS = [('landing', 10), ('walk', 12), ('ask', 22), ('twice', 16), ('fizz', 20), ('climb', 25), ('ledger', 28), ('workshop', 20), ('closing', 12)]

CAP_JS = """(() => {
  if (document.getElementById('demo-cap')) return;
  const s = document.createElement('style');
  s.textContent = `#demo-cap{position:fixed;left:50%;bottom:14px;transform:translateX(-50%);z-index:2147483647;pointer-events:none;
    width:max-content;max-width:1500px;padding:12px 26px 10px;border-radius:12px;background:rgba(12,4,18,.9);border:1px solid rgba(233,196,106,.7);
    box-shadow:0 8px 30px rgba(0,0,0,.55);color:#fff4dc;font:600 29px/1.3 Inter,system-ui,sans-serif;text-align:center;
    transition:opacity .35s;opacity:0}
    .m-panel{bottom:136px !important}
    #demo-cap.on{opacity:1} #demo-cap small{display:block;margin-top:4px;font:500 18px/1.2 Inter,system-ui,sans-serif;color:#e9c46a}
    #demo-card{position:fixed;inset:0;z-index:2147483646;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;
    background:radial-gradient(ellipse at center,rgba(12,4,18,.86),rgba(6,2,10,.96));color:#fff4dc;text-align:center;opacity:0;transition:opacity 1s}
    #demo-card.on{opacity:1} #demo-card h1{margin:0;font:700 124px/1 Cinzel,Georgia,serif;letter-spacing:.06em;color:#e9c46a;text-shadow:0 0 40px rgba(255,160,70,.45)}
    #demo-card .p{font:500 46px/1.25 'Cormorant Garamond',Georgia,serif;font-style:italic;max-width:1400px;margin:0}
    #demo-card .n{font:600 34px/1.35 Inter,system-ui,sans-serif;margin:0;max-width:1500px} #demo-card .dwin{color:#6ee7a0} #demo-card .dlose{color:#ff8a7a}
    #demo-card .f{font:500 22px/1.3 Inter,system-ui,sans-serif;color:#cdb8d8;margin:0} #demo-card .x{font:600 30px/1.3 Inter,system-ui,sans-serif;color:#6ee7a0;margin:0}`;
  document.head.appendChild(s);
  const d = document.createElement('div'); d.id = 'demo-cap'; document.body.appendChild(d);
  window.demoCap = (t, src) => { if (!t) { d.classList.remove('on'); return; } d.innerHTML = ''; d.append(t); if (src) { const m = document.createElement('small'); m.textContent = src; d.append(m); } d.classList.add('on'); };
})()"""


def main():
    url = arg('--url', 'http://127.0.0.1:8765/')
    extra = arg('--closing-extra', '')
    X = json.loads(json.dumps(saved_examples()))
    demo = json.loads((ROOT / 'site/demo.json').read_text())
    CAPS = captions(X, demo['kiro'])
    frames = TMP / 'frames'
    frames.mkdir(parents=True, exist_ok=True)
    for f in frames.glob('*.jpg'):
        f.unlink()
    (OUT / 'demo_shots').mkdir(parents=True, exist_ok=True)
    for f in [*(OUT / 'demo_shots').glob('*.jpg'), *(OUT / 'demo_shots').glob('*.png')]:
        f.unlink()
    stamps, marks = [], []

    def demo_json(route):   # the real demo.json, with the chat's saved questions taken from the tuned run
        r = route.fetch()
        d = r.json()
        d['chat'] = {'examples': [{k: v for k, v in X[p].items() if k not in ('cold', 'base_usd')} for p in ('e2', 'c2', 'h2')],
                     'source': V3, 'answers_from': 'bench/raw.json (the tuned run saved route, time and tokens, not the text)',
                     'note': 'Repeat 1 of the tuned ladder run (bench/results_backend_v3.md): COLD = first ask, WARM = the same question again.'}
        route.fulfill(response=r, body=json.dumps(d), headers={**r.headers, 'content-type': 'application/json'})

    with sync_playwright() as pw:
        b = pw.chromium.launch(args=['--no-sandbox', '--enable-gpu', '--use-angle=metal', '--ignore-gpu-blocklist', '--autoplay-policy=no-user-gesture-required'])
        ctx = b.new_context(viewport={'width': W, 'height': H}, device_scale_factor=1)
        ctx.route('**/api/**', lambda r: r.fulfill(status=404, body='not found'))
        ctx.route('**/events', lambda r: r.fulfill(status=404, body='not found'))
        ctx.route('**/demo.json', demo_json)
        p = ctx.new_page()
        p.goto(url + ('&' if '?' in url else '?') + 'demo=1', wait_until='domcontentloaded')
        p.wait_for_function('!!window.MovieGame && !!window.ChimeraMode', timeout=60000)
        p.wait_for_timeout(2500)
        p.evaluate(CAP_JS)
        js = p.evaluate
        cdp = ctx.new_cdp_session(p)

        def frame(e):
            n = len(stamps)
            (frames / f'{n:06d}.jpg').write_bytes(base64.b64decode(e['data']))
            ts = e['metadata'].get('timestamp')   # the frame's swap time (epoch s); arrival time if it is missing or off
            stamps.append(ts if ts and abs(ts - time.time()) < 5 else time.time())
            try:
                cdp.send('Page.screencastFrameAck', {'sessionId': e['sessionId']})
            except Exception:  # noqa: BLE001 - the session closes at the end
                pass
        cdp.on('Page.screencastFrame', frame)
        cdp.send('Page.startScreencast', {'format': 'jpeg', 'quality': 88, 'maxWidth': W, 'maxHeight': H, 'everyNthFrame': 1})
        p.wait_for_timeout(600)
        t_zero = time.time()
        plan = 0.0

        def at(sec):   # wait until this many seconds after the start of the video
            left = t_zero + sec - time.time()
            if left > 0:
                p.wait_for_timeout(int(left * 1000))

        def turn(total, secs):
            n = max(1, int(secs * 30))
            for _ in range(n):
                js(f'MovieGame.look({total / n})')
                p.wait_for_timeout(33)

        def room(rid):
            js(f"(() => {{ const G = MovieGame, k = G.doors.findIndex(d => d.id === '{rid}'); G.state.door = k; G.openRoom(G.doors[k]); }})()")
            p.wait_for_function('MovieGame.state.panel', timeout=8000)

        def scroll(sel_top_js, secs):   # scroll the panel body smoothly to a target offset
            js(f"(() => {{ const pb = document.getElementById('m-pbody'); pb.style.scrollBehavior = 'auto'; window.__sc = {{ y0: pb.scrollTop, y1: {sel_top_js}, t0: performance.now(), d: {secs * 1000} }};"
               "const step = () => { const s = window.__sc, k = Math.min(1, (performance.now() - s.t0) / s.d), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;"
               "pb.scrollTop = s.y0 + (s.y1 - s.y0) * e; if (k < 1) requestAnimationFrame(step); }; requestAnimationFrame(step); })()")

        def ask_chip(pid):
            js("(q) => [...document.querySelectorAll('#c-chips [data-q]')].find((b) => b.dataset.q === q).click()", X[pid]['q'])

        def shot(name, secs, run):
            nonlocal plan
            marks.append({'shot': name, 'planned_start': plan, 'start': round(time.time() - t_zero, 2), 'captions': []})
            run(plan, CAPS[name])
            at(plan + secs - 0.05)
            marks[-1]['end'] = round(time.time() - t_zero, 2)
            plan += secs

        def cap(text, src):   # show a caption and log when it really appeared, for the .srt
            js('([t, s]) => demoCap(t, s)', [text, src])
            marks[-1]['captions'].append({'at': round(time.time() - t_zero, 2), 'text': text, 'src': src})

        def cap_runner(base, caps, actions):
            """Run actions [(t, fn)] and captions [(t, text, src)] in time order, relative to the shot start."""
            todo = sorted([(t, lambda tx=tx, sr=sr: cap(tx, sr)) for t, tx, sr in caps] + actions, key=lambda x: x[0])
            for t, fn in todo:
                at(base + t)
                fn()

        def snap(name):
            p.screenshot(path=str(OUT / 'demo_shots' / f'{len(marks)}_{name}.jpg'), type='jpeg', quality=80)

        # 1. landing, gates shut
        shot('landing', 10, lambda b0, c: cap_runner(b0, c, [(3.0, lambda: turn(0.25, 1.4)), (4.6, lambda: turn(-0.25, 1.4)), (8.0, lambda: snap('landing'))]))

        # 2. one smooth walk-in: hold W from the road into the Great Hall
        def walk(b0, c):
            def go():
                p.keyboard.down('w')
                t0 = time.time()
                while not js('MovieGame.state.hall') and time.time() - t0 < 12:
                    p.wait_for_timeout(40)
                marks[-1]['walk_in_s'] = round(time.time() - t0, 2)
                p.wait_for_timeout(900)
                p.keyboard.up('w')
            cap_runner(b0, c, [(0.3, go), (6.8, lambda: turn(0.35, 1.6)), (8.6, lambda: turn(-0.35, 1.6)), (10.6, lambda: snap('hall'))])
        shot('walk', 12, walk)

        # 3. the Count's chat: type a question, watch the trace
        def ask(b0, c):
            def open_chat():
                js('MovieGame.talk()')
                p.wait_for_selector('#c-chips:not([hidden])', timeout=8000)
            def type_q():
                p.click('#c-in')
                p.keyboard.type(X['e2']['q'], delay=55)
                p.wait_for_timeout(350)
                p.keyboard.press('Enter')
            cap_runner(b0, c, [(0.2, open_chat), (2.5, type_q), (16.0, lambda: snap('ask'))])
        shot('ask', 22, ask)

        # 4. the same question again: Ask twice replays the first ask, then the repeat from the cache
        def twice(b0, c):
            def go():
                p.click('#c-in')
                p.keyboard.type(X['e2']['q'], delay=20)
                p.wait_for_timeout(300)
                p.click('#c-twice')
            cap_runner(b0, c, [(1.0, go), (12.5, lambda: snap('twice'))])
        shot('twice', 16, twice)

        # 5. FizzBuzz on the 30B
        shot('fizz', 20, lambda b0, c: cap_runner(b0, c, [(2.0, lambda: ask_chip('c2')), (11.0, lambda: snap('fizz'))]))

        # 6. a hard task climbs to the 763B
        shot('climb', 25, lambda b0, c: cap_runner(b0, c, [(2.0, lambda: ask_chip('h2')), (18.0, lambda: snap('climb'))]))

        # 7. the Ledger: the monthly bill, 30% repeats, the loss against the 763B
        def ledger(b0, c):
            def go():
                js('MovieGame.closePanel()')
                p.wait_for_timeout(500)
                room('ledger')
                p.wait_for_selector('.m-cost', timeout=8000)
            def to_chart():
                scroll("document.querySelector('.m-cost').offsetTop - document.getElementById('m-pbody').offsetTop - 8", 2.2)
            def repeats():
                p.click('.m-cost [data-h="repeats_30"]')
            cap_runner(b0, c, [(0.1, go), (3.0, to_chart), (7.0, repeats), (12.0, lambda: snap('ledger_gpt55')),
                               (16.5, lambda: scroll("document.querySelector('.m-cost .m-cost-g').offsetTop - document.getElementById('m-pbody').offsetTop - 8", 1.2)),
                               (24.0, lambda: snap('ledger_loss'))])
        shot('ledger', 28, ledger)

        # 8. the Workshop: how Kiro built it
        def workshop(b0, c):
            def go():
                js('MovieGame.closePanel()')
                p.wait_for_timeout(500)
                room('workshop')
                p.wait_for_selector('.m-keys', timeout=8000)
            cap_runner(b0, c, [(0.1, go), (6.0, lambda: snap('workshop')),
                               (9.0, lambda: scroll("Math.min(document.getElementById('m-pbody').scrollHeight, 900)", 6.0))])
        shot('workshop', 20, workshop)

        # 9. the closing card over the painted landing
        def closing(b0, c):
            def go():
                js('demoCap("")')
                js('MovieGame.closePanel()')
                js('MovieGame.jump(0, false)')
                p.wait_for_timeout(700)
                js('''(x) => { const d = document.createElement('div'); d.id = 'demo-card';
                  d.innerHTML = '<h1>CHIMERA</h1><p class="p">Stop paying a frontier model for FizzBuzz. We prove it with tests.</p>' +
                    '<p class="n"><span class="dwin">62% to 87% less than GPT-5.5 a month</span> (30% repeats)<br><span class="dlose">and 607% more than the cheap 763B at 100,000 calls a day</span></p>' +
                    (x ? '<p class="x"></p>' : '') +
                    '<p class="f">bench/results_company_cost.md · github.com/manvendersingh21/tremor-core · Kiroween 2026</p>';
                  if (x) d.querySelector('.x').textContent = x;
                  const say = document.getElementById('m-say'); if (say) say.style.visibility = 'hidden';
                  document.body.appendChild(d); requestAnimationFrame(() => d.classList.add('on')); }''', extra)
            cap_runner(b0, [], [(0.1, go), (8.0, lambda: snap('closing'))])
            # the card itself carries the pitch; the .srt still gets it as a cue
            marks[-1]['captions'] = [{'at': round(b0 + 0.5, 2), 'text': t, 'src': s} for _, t, s in c]
        shot('closing', 12, closing)

        cdp.send('Page.stopScreencast')
        p.wait_for_timeout(300)
        total = time.time() - t_zero
        fps_in = len(stamps) / max(1e-6, stamps[-1] - stamps[0]) if len(stamps) > 1 else 0
        ctx.close()
        b.close()

    # frames -> constant 30 fps: each frame lasts until the next one arrived (concat demuxer)
    t0 = t_zero
    lines = []
    keep = [(i, s) for i, s in enumerate(stamps) if s >= t0 - 0.05]
    for k, (i, s) in enumerate(keep):
        nxt = keep[k + 1][1] if k + 1 < len(keep) else t0 + total
        lines.append(f"file 'frames/{i:06d}.jpg'\nduration {max(0.001, nxt - max(s, t0)):.4f}")
    lines.append(f"file 'frames/{keep[-1][0]:06d}.jpg'")
    (TMP / 'frames.txt').write_text('\n'.join(lines) + '\n')
    mp4 = OUT / 'demo_cut.mp4'
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(TMP / 'frames.txt'),
                    '-vf', f'fps={FPS},scale={W}:{H}:flags=lanczos,format=yuv420p', '-c:v', 'libx264', '-preset', 'slow', '-crf', '20',
                    '-r', str(FPS), '-movflags', '+faststart', '-an', str(mp4)], check=True)

    # soft captions: the same lines and times as the burned-in ones
    def ts(v):
        v = max(0.0, v)
        return f'{int(v // 3600):02d}:{int(v % 3600 // 60):02d}:{int(v % 60):02d},{int(round(v % 1 * 1000)) % 1000:03d}'
    cues = []
    for m in marks:
        for c in m['captions']:
            cues.append((c['at'], c['text'] + (f" ({c['src']})" if c['src'] else '')))
    srt = []
    for k, (a, text) in enumerate(cues):
        end = cues[k + 1][0] - 0.05 if k + 1 < len(cues) else total
        srt.append(f'{k + 1}\n{ts(a)} --> {ts(end)}\n{text}\n')
    (OUT / 'demo_cut.srt').write_text('\n'.join(srt))
    probe = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=width,height,r_frame_rate,nb_frames:format=duration',
                                       '-of', 'json', str(mp4)], capture_output=True, text=True, check=True).stdout)
    info = {'url': url, 'closing_extra': extra, 'screencast_frames': len(keep), 'screencast_fps': round(fps_in, 1), 'seconds': round(total, 2),
            'video': probe, 'shots': marks}
    (OUT / 'demo_cut.json').write_text(json.dumps(info, indent=1) + '\n')
    print(json.dumps({k: v for k, v in info.items() if k != 'shots'}, indent=1))
    for m in marks:
        print(m['shot'], m['planned_start'], m['start'], m.get('end'), m.get('walk_in_s', ''))
    print(mp4, mp4.stat().st_size // 1024, 'KB')


if __name__ == '__main__':
    main()
