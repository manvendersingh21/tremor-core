"""Record the LIVE demo (site/docs/demo_live.md): the same shots as scripts/demo_record.py, but the Count's chat
calls the real ladder on a local `make web` (cache -> our 30B -> Crusoe 763B), and the closing adds the owned-A6000
result card (numbers read from bench/results_a6000.md).

Usage: .venv/bin/python scripts/demo_record_live.py [--url http://127.0.0.1:8765/] [--v2-only]
Needs ffmpeg and a LIVE server on --url. Writes site/docs/demo_live.mp4 (1920x1080, 30 fps, captions burned in, one
silent AAC track for the voice-over), demo_live.srt, demo_live.json (shot times and every live call's numbers) and
site/docs/demo_cut_v2.mp4 (the saved-replay cut with the A6000 card added at the end).
Live captions are built from GET /api/stats `recent[0]` after each answer, never typed in.
"""
import base64
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_record import CAP_JS, COST, FPS, H, OUT, ROOT, V3, W, arg, saved_examples  # noqa: E402

TMP = ROOT / 'bench/.scratch/demo_live'
A6 = 'bench/results_a6000.md'
LIVE = 'live call · site/docs/demo_live.json'
CARD_S = 12


def a6000():
    """The card's numbers, read from bench/results_a6000.md."""
    t = (ROOT / A6).read_text()
    cut = re.search(r'qwen3:30b-instruct: cache \+ answer check cut ([\d.]+)% of big-model calls with 0 wrong answers from the cache', t)
    ok = re.search(r'Cost case: correct of (\d+) \| (\d+) \| \d+ \| \*\*(\d+)\*\*', t)
    p50 = re.search(r'p50 ([\d.]+) s vs ([\d.]+) s \(cost case\)', t)
    if not (cut and ok and p50):
        raise SystemExit(f'{A6}: a number the card needs was not found')
    return {'cut': cut[1], 'n': ok[1], 'base_ok': ok[2], 'ladder_ok': ok[3], 'p50': p50[1], 'p50_base': p50[2]}


def card_js():
    a = a6000()
    return ('<h1>CHIMERA</h1><p class="p">On our own GPU: one RTX A6000, our 30B, the Supabase cache, the 763B last.</p>'
            f'<p class="n"><span class="dwin">{a["cut"]}% fewer 763B calls, 0 wrong answers from the cache</span><br>'
            f'<span class="dwin">{a["ladder_ok"]} of {a["n"]} coding tasks right, against {a["base_ok"]} for the 763B alone</span><br>'
            f'<span class="dlose">A loss: slower on a first pass, {a["p50"]} s against {a["p50_base"]} s (median)</span></p>'
            f'<p class="f">{A6} · github.com/manvendersingh21/tremor-core · Kiroween 2026</p>'), a


def recent(url, prompt):
    """The server's own record of the last call (docs/api.md /api/stats recent[0]); it must be this prompt."""
    for _ in range(20):
        with urllib.request.urlopen(url + 'api/stats', timeout=10) as r:  # noqa: S310 (loopback)
            rec = (json.load(r).get('recent') or [{}])[0]
        if rec.get('prompt', '')[:40] == prompt[:40]:
            return rec
        time.sleep(0.3)
    raise SystemExit('the last call in /api/stats is not the one just asked')


def step(rec, name):
    return [s for s in rec.get('steps', []) if s.get('step') == name]


def encode(stamps, t0, total, mp4):
    """frames -> constant 30 fps (each frame lasts until the next arrived), plus one silent stereo track for the voice."""
    lines, keep = [], [(i, s) for i, s in enumerate(stamps) if s >= t0 - 0.05]
    for k, (i, s) in enumerate(keep):
        nxt = keep[k + 1][1] if k + 1 < len(keep) else t0 + total
        lines.append(f"file 'frames/{i:06d}.jpg'\nduration {max(0.001, nxt - max(s, t0)):.4f}")
    lines.append(f"file 'frames/{keep[-1][0]:06d}.jpg'")
    (TMP / 'frames.txt').write_text('\n'.join(lines) + '\n')
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(TMP / 'frames.txt'),
                    '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-map', '0:v', '-map', '1:a',
                    '-vf', f'fps={FPS},scale={W}:{H}:flags=lanczos,format=yuv420p', '-c:v', 'libx264', '-preset', 'slow', '-crf', '20',
                    '-r', str(FPS), '-c:a', 'aac', '-b:a', '128k', '-shortest', '-movflags', '+faststart', str(mp4)], check=True)
    return len(keep)


def srt_time(v):
    v = max(0.0, v)
    return f'{int(v // 3600):02d}:{int(v % 3600 // 60):02d}:{int(v % 60):02d},{int(round(v % 1 * 1000)) % 1000:03d}'


def write_srt(cues, total, path):
    out = []
    for k, (a, text) in enumerate(cues):
        end = cues[k + 1][0] - 0.05 if k + 1 < len(cues) else total
        out.append(f'{k + 1}\n{srt_time(a)} --> {srt_time(end)}\n{text}\n')
    path.write_text('\n'.join(out))


def probe(mp4):
    return json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,width,height,r_frame_rate:format=duration',
                                      '-of', 'json', str(mp4)], capture_output=True, text=True, check=True).stdout)


def make_v2(info):
    """demo_cut.mp4 + the A6000 card cut from demo_live.mp4, 1 s cross-fade, silent track. Also demo_cut_v2.srt."""
    card = next(m for m in info['shots'] if m['shot'] == 'a6000')
    cut, live, v2 = OUT / 'demo_cut.mp4', OUT / 'demo_live.mp4', OUT / 'demo_cut_v2.mp4'
    # the A6000 card fades in 7.5 s into the old closing card, so the voiced v2 (scripts/demo_voice.py) fits 2:59
    closing = next(m for m in json.loads((OUT / 'demo_cut.json').read_text())['shots'] if m['shot'] == 'closing')
    d0 = min(float(probe(cut)['format']['duration']), closing['start'] + 7.5 + 1)
    start, length = card['start'] + 0.3, card['end'] - card['start'] - 0.3
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(cut), '-ss', f'{start:.2f}', '-t', f'{length:.2f}', '-i', str(live),
                    '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-filter_complex',
                    f'[0:v]fps={FPS},format=yuv420p,settb=AVTB[a];[1:v]fps={FPS},format=yuv420p,settb=AVTB[b];'
                    f'[a][b]xfade=transition=fade:duration=1:offset={d0 - 1:.2f}[v]',
                    '-map', '[v]', '-map', '2:a', '-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-r', str(FPS),
                    '-c:a', 'aac', '-b:a', '128k', '-shortest', '-movflags', '+faststart', str(v2)], check=True)
    old = (OUT / 'demo_cut.srt').read_text().strip()
    n = old.count(' --> ')
    head, _, tail = old.rpartition(' --> ')   # the old last cue ends where the card starts
    old = f"{head} --> {srt_time(d0 - 1.05)}{tail[12:]}"
    a = info['a6000']
    text = (f"On our own A6000: {a['cut']}% fewer 763B calls, 0 wrong answers from the cache; {a['ladder_ok']} of {a['n']} "
            f"coding tasks right vs {a['base_ok']} for the 763B alone. A loss: slower on a first pass ({A6})")
    end = float(probe(v2)['format']['duration'])
    (OUT / 'demo_cut_v2.srt').write_text(f'{old}\n\n{n + 1}\n{srt_time(d0 - 1)} --> {srt_time(end)}\n{text}\n')
    return v2


def main():
    url = arg('--url', 'http://127.0.0.1:8765/')
    if '--v2-only' in sys.argv:
        print(make_v2(json.loads((OUT / 'demo_live.json').read_text())))
        return
    with urllib.request.urlopen(url + 'api/health', timeout=10) as r:  # noqa: S310 (loopback)
        h = json.load(r)
    if not (h.get('gpu_tunnel') or {}).get('up'):
        raise SystemExit('the GPU 30B is not up on this server: no live recording')
    prompts = {p['id']: p['prompt'] for p in map(json.loads, (ROOT / 'bench/prompts.jsonl').read_text().splitlines()) if p}
    base_h2 = saved_examples()['h2']   # the 763B alone on the hard task, from the tuned run (bench/results_backend_v3.md)
    card_html, A = card_js()
    frames = TMP / 'frames'
    frames.mkdir(parents=True, exist_ok=True)
    for f in frames.glob('*.jpg'):
        f.unlink()
    shots_dir = OUT / 'demo_live_shots'
    shots_dir.mkdir(parents=True, exist_ok=True)
    stamps, marks, calls = [], [], {}

    with sync_playwright() as pw:
        b = pw.chromium.launch(args=['--no-sandbox', '--enable-gpu', '--use-angle=metal', '--ignore-gpu-blocklist',
                                     '--autoplay-policy=no-user-gesture-required', '--window-size=1920,1080'])
        ctx = b.new_context(viewport={'width': W, 'height': H}, device_scale_factor=1)
        p = ctx.new_page()
        p.goto(url, wait_until='domcontentloaded')
        p.wait_for_function('!!window.MovieGame && !!window.ChimeraMode', timeout=60000)
        if p.evaluate('ChimeraMode.detect()') != 'live':
            raise SystemExit('the page is in DEMO mode: no live recording')
        p.wait_for_timeout(2500)
        p.evaluate(CAP_JS)
        js = p.evaluate
        cdp = ctx.new_cdp_session(p)

        def frame(e):
            n = len(stamps)
            (frames / f'{n:06d}.jpg').write_bytes(base64.b64decode(e['data']))
            ts = e['metadata'].get('timestamp')
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

        def now():
            return time.time() - t_zero

        def at(sec):
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

        def scroll(sel_top_js, secs):
            js(f"(() => {{ const pb = document.getElementById('m-pbody'); pb.style.scrollBehavior = 'auto'; window.__sc = {{ y0: pb.scrollTop, y1: {sel_top_js}, t0: performance.now(), d: {secs * 1000} }};"
               "const step = () => { const s = window.__sc, k = Math.min(1, (performance.now() - s.t0) / s.d), e = k < .5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;"
               "pb.scrollTop = s.y0 + (s.y1 - s.y0) * e; if (k < 1) requestAnimationFrame(step); }; requestAnimationFrame(step); })()")

        def cap(text, src=''):
            js('([t, s]) => demoCap(t, s)', [text, src])
            marks[-1]['captions'].append({'at': round(now(), 2), 'text': text, 'src': src})

        def snap(name):
            p.screenshot(path=str(shots_dir / f'{len(marks)}_{name}.jpg'), type='jpeg', quality=80)

        def shot(name, secs, run):
            """Run a shot; it lasts at least `secs`, longer when a live answer takes longer."""
            nonlocal plan
            marks.append({'shot': name, 'planned_start': round(plan, 2), 'start': round(now(), 2), 'captions': []})
            run(plan)
            at(plan + secs - 0.05)
            marks[-1]['end'] = round(now(), 2)
            plan = max(plan + secs, now())

        def ask(key, q, delay):
            """Type a question into the Count's chat, send it, wait for the answer; returns the server's record."""
            p.click('#c-in')
            p.keyboard.type(q, delay=delay)
            p.wait_for_timeout(300)
            n0 = js("document.querySelectorAll('#c-log .c-tag').length")
            t = now()
            p.keyboard.press('Enter')
            p.wait_for_function(f"document.querySelectorAll('#c-log .c-tag').length > {n0} && !document.getElementById('c-send').disabled",
                                timeout=150000)
            rec = recent(url, q)
            calls[key] = {'asked_at': round(t, 2), 'answered_at': round(now(), 2), **rec}
            return rec

        def sec(v):
            return f'{v / 1000:.2f} s' if v < 1000 else f'{v / 1000:.1f} s'

        def tok(r):
            return (r.get('tokens_in') or 0) + (r.get('tokens_out') or 0)

        # 1. landing, gates shut
        def landing(b0):
            cap('CHIMERA sends each AI call to the cheapest helper that gets it right')
            at(b0 + 3.0); turn(0.25, 1.4); turn(-0.25, 1.4)
            at(b0 + 5.5); cap('This time it is LIVE: our 30B runs on our own A6000 GPU')
            at(b0 + 8.0); snap('landing')
        shot('landing', 10, landing)

        # 2. one smooth walk-in
        def walk(b0):
            cap('Hold W: the gates open as you reach them, then the great door')
            at(b0 + 0.3)
            p.keyboard.down('w')
            t0 = time.time()
            while not js('MovieGame.state.hall') and time.time() - t0 < 12:
                p.wait_for_timeout(40)
            marks[-1]['walk_in_s'] = round(time.time() - t0, 2)
            p.wait_for_timeout(900)
            p.keyboard.up('w')
            at(b0 + 6.0); cap('The Great Hall. Each gold door is a room of measured numbers', 'site/game/')
            at(b0 + 6.8); turn(0.35, 1.6); turn(-0.35, 1.6)
            at(b0 + 10.6); snap('hall')
        shot('walk', 12, walk)

        # 3. a fresh question: cache miss, our 30B answers
        def first(b0):
            cap('Ask the Count. The call climbs a ladder: cache, then our 30B, then the 763B')
            js('MovieGame.talk()')
            p.wait_for_selector('#c-in', timeout=8000)
            at(b0 + 2.5)
            r = ask('first', prompts['e2'], 55)
            cs = (step(r, 'cache_shared') or [{}])[0]
            cap(f'LIVE · cache miss (best cosine {cs.get("score") or 0:.2f}). Our 30B on the A6000 answered: '
                f'{sec(r["ms"])}, {tok(r)} tokens, $0 in tokens', LIVE)
            p.wait_for_timeout(5000); snap('ask')
        shot('ask', 20, first)

        # 4. the same question again: the shared cache answers
        def again(b0):
            cap('Ask the same question again')
            at(b0 + 1.0)
            r = ask('repeat', prompts['e2'], 20)
            cap(f'LIVE · cache hit ({r.get("cache") or "shared"}): {sec(r["ms"])}, {tok(r)} tokens, $0. No model was called', LIVE)
            p.wait_for_timeout(5000); snap('twice')
        shot('twice', 12, again)

        # 5. FizzBuzz on the 30B
        def fizz(b0):
            cap('FizzBuzz does not need a frontier model')
            at(b0 + 1.0)
            r = ask('fizz', prompts['c2'], 8)
            d = (step(r, 'draft') or [{}])[0]
            cap(f'LIVE · our 30B wrote it: {sec(r["ms"])}, {tok(r)} tokens, $0 in tokens (confidence {d.get("confidence", 0):.2f})', LIVE)
            p.wait_for_timeout(5500)
            kept = (step(r, 'final') or [{}])[0].get('tokens_kept_off_big', tok(r))
            cap(f'{kept} tokens kept off the 763B. The A6000 is ours, so it is priced $0', LIVE + ' · ' + A6)
            p.wait_for_timeout(4500); snap('fizz')
        shot('fizz', 18, fizz)

        # 6. a hard task: the 30B is unsure, the call climbs to the 763B
        def climb(b0):
            cap('A hard design task')
            at(b0 + 1.0)
            r = ask('climb', prompts['h2'], 6)
            d = (step(r, 'draft') or [{}])[0]
            if r.get('tier') == 'cloud-deepseek' and d.get('confidence') is not None:
                cap(f'LIVE · the 30B was unsure ({d["confidence"]:.2f}, below {d["gate"]:.2f}), so the call climbed to the 763B', LIVE)
            else:
                cap(f'LIVE · answered by {r.get("tier")}: {sec(r["ms"])}', LIVE)
            p.wait_for_timeout(6500)
            cap(f'A loss: {sec(r["ms"])} and ${r.get("dollars", 0):.5f} with the climb. '
                f'The 763B alone took {sec(base_h2["base_ms"])} in the saved run', LIVE + ' · ' + V3)
            p.wait_for_timeout(6000); snap('climb')
        shot('climb', 22, climb)

        # 7. the Ledger: the monthly bill
        def ledger(b0):
            js('MovieGame.closePanel()')
            p.wait_for_timeout(500)
            room('ledger')
            p.wait_for_selector('.m-cost', timeout=8000)
            cap('The bill: a month of coding calls', COST)
            at(b0 + 3.0); scroll("document.querySelector('.m-cost').offsetTop - document.getElementById('m-pbody').offsetTop - 8", 2.2)
            at(b0 + 7.0); p.click('.m-cost [data-h="repeats_30"]')
            at(b0 + 8.0); cap('With 30% repeats: 62% to 87% less than GPT-5.5 alone', COST)
            at(b0 + 12.0); snap('ledger_gpt55')
            at(b0 + 16.5); scroll("document.querySelector('.m-cost .m-cost-g').offsetTop - document.getElementById('m-pbody').offsetTop - 8", 1.2)
            at(b0 + 18.0); cap('A loss: at 100,000 calls a day the cheap 763B alone costs less. We cost 607% more', COST)
            at(b0 + 24.0); snap('ledger_loss')
        shot('ledger', 27, ledger)

        # 8. the Workshop
        def workshop(b0):
            K = json.loads((ROOT / 'site/demo.json').read_text())['kiro']
            js('MovieGame.closePanel()')
            p.wait_for_timeout(500)
            room('workshop')
            p.wait_for_selector('.m-keys', timeout=8000)
            cap(f'Built with Kiro: {len(K["steering"])} steering files, {len(K["specs"])} specs, {len(K["hooks"])} hooks, '
                f'{len(K["agents"])} agents, MCP tools and a Power', '.kiro/')
            at(b0 + 5.0); snap('workshop')
            at(b0 + 8.0); scroll("Math.min(document.getElementById('m-pbody').scrollHeight, 900)", 5.0)
            at(b0 + 9.0); cap(f'Property tests from the specs found {K["bugs_found"]} real bugs. {K["bugs_fixed"]} are fixed',
                              'docs/handoff/property-tests.md')
        shot('workshop', 17, workshop)

        # 9. the pitch card, then 10. the A6000 card, over the painted landing
        def closing(b0):
            js('demoCap("")')
            js('MovieGame.closePanel()')
            js('MovieGame.jump(0, false)')
            p.wait_for_timeout(700)
            js('''() => { const d = document.createElement('div'); d.id = 'demo-card';
              d.innerHTML = '<h1>CHIMERA</h1><p class="p">Stop paying a frontier model for FizzBuzz. We prove it with tests.</p>' +
                '<p class="n"><span class="dwin">62% to 87% less than GPT-5.5 a month</span> (30% repeats)<br><span class="dlose">and 607% more than the cheap 763B at 100,000 calls a day</span></p>' +
                '<p class="f">bench/results_company_cost.md · github.com/manvendersingh21/tremor-core · Kiroween 2026</p>';
              for (const id of ['m-say', 'm-mode']) { const e = document.getElementById(id); if (e) e.style.visibility = 'hidden'; }
              document.body.appendChild(d); requestAnimationFrame(() => d.classList.add('on')); }''')
            marks[-1]['captions'].append({'at': round(now(), 2), 'text': 'Stop paying a frontier model for FizzBuzz. We prove it with tests.', 'src': COST})
            at(b0 + 6.5); snap('closing')
        shot('closing', 8, closing)

        def card(b0):
            js('''(h) => { const d = document.getElementById('demo-card'); d.classList.remove('on');
              setTimeout(() => { d.innerHTML = h; d.classList.add('on'); }, 1000); }''', card_html)
            marks[-1]['captions'].append({'at': round(now() + 1, 2), 'text': f'On our own A6000: {A["cut"]}% fewer 763B calls, 0 wrong answers from the cache; '
                                          f'{A["ladder_ok"]} of {A["n"]} coding tasks right vs {A["base_ok"]} for the 763B alone. '
                                          f'A loss: slower on a first pass', 'src': A6})
            at(b0 + 8.0); snap('a6000')
        shot('a6000', CARD_S, card)

        cdp.send('Page.stopScreencast')
        p.wait_for_timeout(300)
        total = now()
        fps_in = len(stamps) / max(1e-6, stamps[-1] - stamps[0]) if len(stamps) > 1 else 0
        ctx.close()
        b.close()

    if total > 179:
        raise SystemExit(f'the live take ran {total:.1f} s, over 2:59; record again')
    mp4 = OUT / 'demo_live.mp4'
    n = encode(stamps, t_zero, total, mp4)
    cues = [(c['at'], c['text'] + (f" ({c['src']})" if c['src'] else '')) for m in marks for c in m['captions']]
    write_srt(cues, total, OUT / 'demo_live.srt')
    keepk = ('ts', 'prompt', 'tier', 'model', 'cache', 'score', 'tokens_in', 'tokens_out', 'ms', 'dollars', 'dollars_saved', 'steps', 'asked_at', 'answered_at')
    info = {'url': url, 'mode': 'live', 'screencast_frames': n, 'screencast_fps': round(fps_in, 1), 'seconds': round(total, 2),
            'video': probe(mp4), 'a6000': A, 'calls': {k: {x: v[x] for x in keepk if x in v} for k, v in calls.items()}, 'shots': marks}
    (OUT / 'demo_live.json').write_text(json.dumps(info, indent=1) + '\n')
    v2 = make_v2(info)
    for m in marks:
        print(m['shot'], m['planned_start'], m['start'], m.get('end'), m.get('walk_in_s', ''))
    for k, c in calls.items():
        print(k, c.get('tier'), c.get('ms'), c.get('tokens_in'), c.get('tokens_out'), c.get('dollars'))
    print(mp4, mp4.stat().st_size // 1024, 'KB;', v2, v2.stat().st_size // 1024, 'KB')


if __name__ == '__main__':
    main()
