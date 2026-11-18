"""Demo v3 (site/docs/demo_v3.md): the live walk and evaluation through our A6000 30B, a new ElevenLabs voice that says
every number as words, and no dead gaps (each shot lasts as long as its spoken line, a progress bar moves the whole
time, the only fade is one second at the end).

    .venv/bin/python scripts/demo_record_v3.py voice      # synthesize the 10 lines once -> bench/.scratch/demo_v3/voice/
    .venv/bin/python scripts/demo_record_v3.py rehearse   # landing + walk only (demo mode allowed) -> bench/.scratch/demo_v3/
    .venv/bin/python scripts/demo_record_v3.py record [--url http://127.0.0.1:8765/]

`record` needs a LIVE server (the Count's chat on the real ladder) and the voice clips. It writes site/docs/demo_v3.mp4
(1920x1080, 30 fps, captions burned in, the voice), demo_v3.srt (the spoken lines), demo_v3.json (shots, the server's
record of each live call, the gap check) and demo_v3_shots/. A take whose calls did not go the way the narration says
(30B miss, cache hit, 30B FizzBuzz, climb to the 763B) is refused before anything is written.
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
from demo_record_live import A6, LIVE, card_js, probe, recent, srt_time, step  # noqa: E402
from demo_voice import duration, synth  # noqa: E402

TMP = ROOT / 'bench/.scratch/demo_v3'
VDIR = TMP / 'voice'
DOC = OUT / 'demo_v3.md'
VOICE = {'name': 'Bella - Professional, Bright, Warm', 'voice_id': 'hpp4J3VqNfWAUOO0d1Us', 'model_id': 'eleven_multilingual_v2',
         'output_format': 'mp3_44100_128',
         'voice_settings': {'stability': 0.5, 'similarity_boost': 0.8, 'style': 0.15, 'use_speaker_boost': True, 'speed': 1.0}}
MAX_CHARS = 2300            # the free ElevenLabs quota; every line is sent once
LEAD, TAIL, FADE, MAX_S = 0.3, 0.8, 1.0, 179.0
SAID = {'cut': '70.7', 'ladder_ok': '292', 'n': '301', 'base_ok': '286'}   # what shot 10 says in words
LINE = re.compile(r'^\*\*Shot (\d+)\.\*\* "(.+)"\s*$')

BAR_JS = """(est) => {
  const b = document.createElement('div'); b.id = 'v3-bar';
  b.style.cssText = 'position:fixed;left:0;bottom:0;height:5px;width:0;z-index:2147483647;pointer-events:none;' +
    'background:linear-gradient(90deg,#9c6b1e,#ffd27a);box-shadow:0 0 10px #ffb84d';
  const s = document.createElement('style');   // slow drift on what would otherwise hold still: the room painting, the end cards
  s.textContent = '@keyframes v3drift{from{transform:scale(1)}to{transform:scale(1.07)}} @keyframes v3card{from{transform:scale(1)}to{transform:scale(1.045)}}' +
    '.m-pbg{animation:v3drift 9s linear infinite alternate} #demo-card.on>*{animation:v3card 9s linear infinite alternate}';
  document.head.appendChild(s);
  window.v3read = (secs) => { const el = document.getElementById('c-log'), last = el && el.lastElementChild; if (!last) return;
    const y1 = el.scrollHeight - el.clientHeight, y0 = Math.min(y1, Math.max(0, last.offsetTop - el.offsetTop - 8)); if (y1 - y0 < 4) return;
    el.style.scrollBehavior = 'auto'; el.scrollTop = y0; const t1 = performance.now();
    const g = () => { const k = Math.min(1, (performance.now() - t1) / (secs * 1000)); el.scrollTop = y0 + (y1 - y0) * k; if (k < 1) requestAnimationFrame(g); };
    requestAnimationFrame(g); };
  document.body.appendChild(b); const t0 = performance.now();
  const f = () => { b.style.width = Math.min(100, (performance.now() - t0) / (est * 10)).toFixed(3) + '%'; requestAnimationFrame(f); };
  requestAnimationFrame(f);
  window.v3ripple = (x, y) => { const r = document.createElement('div');
    r.style.cssText = `position:fixed;left:${x - 34}px;top:${y - 34}px;width:68px;height:68px;border-radius:50%;border:4px solid #ffd27a;` +
      'box-shadow:0 0 22px #ffb84d;z-index:2147483647;pointer-events:none;transition:transform .8s ease-out,opacity .8s ease-out';
    document.body.appendChild(r); requestAnimationFrame(() => { r.style.transform = 'scale(2.4)'; r.style.opacity = '0'; });
    setTimeout(() => r.remove(), 1000); };
}"""


def narration() -> dict[int, str]:
    """The 10 spoken lines from site/docs/demo_v3.md, every number in words."""
    text = DOC.read_text().split('## Narration (word form)', 1)[1].split('\n## ', 1)[0]
    out = {int(m[1]): m[2] for m in map(LINE.match, text.splitlines()) if m}
    if sorted(out) != list(range(1, 11)):
        raise SystemExit(f'{DOC.name}: want shot lines 1 to 10, found {sorted(out)}')
    bad = {n: t for n, t in out.items() if re.search(r'[0-9%$]', t)}
    if bad:
        raise SystemExit(f'digits or symbols in the narration (say them as words): {bad}')
    if sum(map(len, out.values())) > MAX_CHARS:
        raise SystemExit(f'{sum(map(len, out.values()))} characters, over the {MAX_CHARS} budget')
    return out


def voice() -> None:
    sys.path.insert(0, str(ROOT))
    import conftest  # noqa: F401  registers chimera_core
    from chimera_core.config import load_env
    load_env()
    VDIR.mkdir(parents=True, exist_ok=True)
    for n, t in narration().items():   # once per line: a clip on disk is never paid for again
        f = VDIR / f'{n:02d}.mp3'
        if not f.exists():
            synth(t, f, VOICE, [])
        print(n, round(duration(f), 2), 's', len(t), 'chars')


def clips() -> dict[int, float]:
    out = {}
    for n in narration():
        f = VDIR / f'{n:02d}.mp3'
        if not f.exists():
            raise SystemExit(f'{f} is missing: run `voice` first')
        out[n] = duration(f)
    return out


def encode(stamps, frames, t0, total, mp4):
    """frames -> a steady 30 fps video (each frame lasts until the next one arrived)."""
    keep = [(i, s) for i, s in enumerate(stamps) if s >= t0 - 0.05]
    lines = []
    for k, (i, s) in enumerate(keep):
        nxt = keep[k + 1][1] if k + 1 < len(keep) else t0 + total
        lines.append(f"file '{frames}/{i:06d}.jpg'\nduration {max(0.001, nxt - max(s, t0)):.4f}")
    lines.append(f"file '{frames}/{keep[-1][0]:06d}.jpg'")
    (TMP / 'frames.txt').write_text('\n'.join(lines) + '\n')
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(TMP / 'frames.txt'),
                    '-vf', f'fps={FPS},scale={W}:{H}:flags=lanczos,format=yuv420p', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
                    '-r', str(FPS), '-an', str(mp4)], check=True)
    return len(keep)


def mux(video, lines, out):
    """The voice clips at their times, loudness -16 LUFS; one FADE-second fade of picture and sound at the very end."""
    T = float(probe(video)['format']['duration'])
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-i', str(video)] + sum((['-i', str(x['clip'])] for x in lines), [])
    f = ''.join(f"[{i + 1}:a]adelay={int(x['at'] * 1000)}:all=1[a{i}];" for i, x in enumerate(lines))
    f += ''.join(f'[a{i}]' for i in range(len(lines))) + f'amix=inputs={len(lines)}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,' \
        f'aresample=48000,apad,atrim=0:{T:.3f},afade=t=out:st={T - FADE:.3f}:d={FADE}[a];[0:v]fade=t=out:st={T - FADE:.3f}:d={FADE}[v]'
    subprocess.run(cmd + ['-filter_complex', f, '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'slow', '-crf', '20',
                          '-pix_fmt', 'yuv420p', '-r', str(FPS), '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-t', f'{T:.3f}',
                          '-movflags', '+faststart', str(out)], check=True)


def gaps(mp4) -> dict:
    """Dead-gap check: frozen picture (bar strip cropped off, so it must be the scene that moves), black frames, long silence."""
    def run(vf=None, af=None):
        a = ['ffmpeg', '-hide_banner', '-i', str(mp4)] + (['-vf', vf, '-an'] if vf else ['-af', af, '-vn']) + ['-f', 'null', '-']
        return subprocess.run(a, capture_output=True, text=True).stderr
    T = float(probe(mp4)['format']['duration'])
    fr = run(vf=f'crop=iw:ih-12:0:0,freezedetect=n=-60dB:d=1.0')
    bl = run(vf='blackdetect=d=0.3:pix_th=0.10')
    si = run(af='silencedetect=n=-45dB:d=2.5')
    num = lambda pat, s: [float(v) for v in re.findall(pat, s)]  # noqa: E731
    return {'seconds': round(T, 2), 'frozen_1s': list(zip(num(r'freeze_start: ([\d.]+)', fr), num(r'freeze_duration: ([\d.]+)', fr))),
            'black_0_3s': list(zip(num(r'black_start:([\d.]+)', bl), num(r'black_duration:([\d.]+)', bl))),
            'silence_2_5s': list(zip(num(r'silence_start: ([\d.]+)', si), num(r'silence_duration: ([\d.]+)', si))),
            'rule': f'frozen = no change for 1 s in the frame above the progress bar; black = 0.3 s; the last {FADE:.0f} s is the fade-out'}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'voice':
        return voice()
    if mode not in ('record', 'rehearse'):
        raise SystemExit(__doc__)
    full = mode == 'record'
    url = arg('--url', 'http://127.0.0.1:8765/')
    say, dur = narration(), clips()
    card_html, A = card_js()
    if {k: A[k] for k in SAID} != SAID:
        raise SystemExit(f'{A6} changed: shot 10 says {SAID}, the file has {A}; fix the narration in {DOC.name}')
    if full:
        with urllib.request.urlopen(url + 'api/health', timeout=10) as r:  # noqa: S310 (loopback)
            if not (json.load(r).get('gpu_tunnel') or {}).get('up'):
                raise SystemExit('the GPU 30B is not up on this server: no live recording')
    prompts = {p['id']: p['prompt'] for p in map(json.loads, (ROOT / 'bench/prompts.jsonl').read_text().splitlines()) if p}
    base_h2 = saved_examples()['h2']   # the 763B alone on the hard task, from the tuned run (bench/results_backend_v3.md)
    K = json.loads((ROOT / 'site/demo.json').read_text())['kiro']

    def need(n, base):   # a shot lasts at least its line plus a breath
        return max(base, LEAD + dur[n] + TAIL)

    def cue(n, phrase):  # about when the voice reaches `phrase` in line n (characters are near-even in time)
        return LEAD + dur[n] * say[n].index(phrase) / len(say[n])

    BASE = {1: 8, 2: 14, 3: 14, 4: 9, 5: 8, 6: 16, 7: 20, 8: 12, 9: 5, 10: 12}
    est = sum(need(n, b) for n, b in BASE.items()) if full else need(1, 8) + need(2, 14)
    frames = TMP / ('frames' if full else 'frames_rehearse')
    frames.mkdir(parents=True, exist_ok=True)
    for f in frames.glob('*.jpg'):
        f.unlink()
    shots_dir = OUT / 'demo_v3_shots' if full else TMP / 'shots_rehearse'
    shots_dir.mkdir(parents=True, exist_ok=True)
    for f in shots_dir.glob('*.jpg'):
        f.unlink()
    stamps, marks, calls = [], [], {}

    with sync_playwright() as pw:
        b = pw.chromium.launch(args=['--no-sandbox', '--enable-gpu', '--use-angle=metal', '--ignore-gpu-blocklist',
                                     '--autoplay-policy=no-user-gesture-required', '--window-size=1920,1080'])
        ctx = b.new_context(viewport={'width': W, 'height': H}, device_scale_factor=1)
        p = ctx.new_page()
        p.goto(url, wait_until='domcontentloaded')
        p.wait_for_function('!!window.MovieGame && !!window.ChimeraMode', timeout=60000)
        if full and p.evaluate('ChimeraMode.detect()') != 'live':
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
        js(BAR_JS, est)
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

        def tap(key, ms=90):
            p.keyboard.down(key)
            p.wait_for_timeout(ms)
            p.keyboard.up(key)

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

        def shot(n, name, run):
            """Shot n starts its voice line LEAD s in and lasts at least the line plus TAIL; a slow live answer makes it longer."""
            nonlocal plan
            secs = need(n, BASE[n])
            marks.append({'n': n, 'shot': name, 'planned_start': round(plan, 2), 'start': round(now(), 2), 'captions': []})
            run(plan)
            at(plan + secs - 0.05)
            marks[-1]['end'] = round(now(), 2)
            plan = max(plan + secs, now())

        def ask(key, q, delay):
            p.click('#c-in')
            p.keyboard.type(q, delay=delay)
            p.wait_for_timeout(250)
            n0 = js("document.querySelectorAll('#c-log .c-tag').length")
            t = now()
            p.keyboard.press('Enter')
            p.wait_for_function(f"document.querySelectorAll('#c-log .c-tag').length > {n0} && !document.getElementById('c-send').disabled",
                                timeout=150000)
            js('v3read(6)')   # the answer scrolls by while it is read
            rec = recent(url, q)
            calls[key] = {'asked_at': round(t, 2), 'answered_at': round(now(), 2), **rec}
            return rec

        def sec(v):
            return f'{v / 1000:.2f} s' if v < 1000 else f'{v / 1000:.1f} s'

        def tok(r):
            return (r.get('tokens_in') or 0) + (r.get('tokens_out') or 0)

        # 1. the painted landing, gates shut
        def landing(b0):
            cap('CHIMERA sends each AI call to the cheapest helper that gets it right')
            at(b0 + 2.6); turn(0.22, 1.6); turn(-0.22, 1.6)
            at(b0 + 6.0); cap('This take is LIVE: our 30B runs on our own A6000 GPU')
            snap('landing')
        shot(1, 'landing', landing)

        # 2. W to the gates, A A (look left twice), click the gate, walk into the Great Hall
        def walk(b0):
            cap('Hold W: walk up to the iron gates')
            at(b0 + cue(2, 'I hold W'))
            p.keyboard.down('w')
            t0 = time.time()
            while js('MovieGame.z()') > 4.4 and time.time() - t0 < 6:   # stop short of 3.6 m, where they would open by themselves
                p.wait_for_timeout(15)
            p.keyboard.up('w')
            marks[-1]['to_gate_s'] = round(time.time() - t0, 2)
            at(b0 + cue(2, 'I look left'))
            cap('A, A: look left, and left again')
            tap('a')
            at(b0 + cue(2, 'and left again'))
            tap('a')
            marks[-1]['yaw_after_a_a'] = round(js('MovieGame.state.yaw'), 3)
            at(b0 + cue(2, 'One click') - 0.25)
            for _ in range(40):   # the gate must be what you look at; turn back a little if two taps went past it
                if js('(MovieGame.state.target || {}).kind') == 'gates':
                    break
                js('MovieGame.look(-0.02)')
                p.wait_for_timeout(33)
            x, y = js('(() => { const q = MovieGame.world.project(MovieGame.world.anchors.gates); return [q.x, q.y]; })()')
            js('([x, y]) => v3ripple(x, y)', [x, y])
            p.mouse.click(x, y)
            p.wait_for_function('MovieGame.state.open.gates', timeout=3000)
            marks[-1]['gates_opened_by'] = 'click'
            cap('One click: the gates swing open')
            p.wait_for_timeout(450)
            turn(-js('MovieGame.state.yaw'), 0.6)
            p.keyboard.down('w')
            t0 = time.time()
            while not js('MovieGame.state.hall') and time.time() - t0 < 12:
                p.wait_for_timeout(40)
            p.wait_for_timeout(800)
            p.keyboard.up('w')
            marks[-1]['gate_to_hall_s'] = round(time.time() - t0, 2)
            cap('The Great Hall. Each gold door is a room of measured numbers', 'site/game/')
            turn(0.25, 1.0); turn(-0.25, 1.0)
            snap('hall')
        shot(2, 'walk', walk)

        if full:
            # 3. a fresh question: cache miss, our 30B answers
            def first(b0):
                cap('Ask the Count. The call climbs a ladder: cache, then our 30B, then the 763B')
                js('MovieGame.talk()')
                p.wait_for_selector('#c-in', timeout=8000)
                at(b0 + max(2.5, cue(3, 'The cache has not seen') - 2.4))
                r = ask('first', prompts['e2'], 55)
                cs = (step(r, 'cache_shared') or [{}])[0]
                cap(f'LIVE · cache miss (best cosine {cs.get("score") or 0:.2f}). Our 30B on the A6000 answered: '
                    f'{sec(r["ms"])}, {tok(r)} tokens, $0 in tokens', LIVE.replace('demo_live', 'demo_v3'))
                p.wait_for_timeout(4000); snap('ask')
            shot(3, 'ask', first)

            # 4. the same question again: the shared cache answers
            def again(b0):
                cap('Ask the same question again')
                at(b0 + 1.0)
                r = ask('repeat', prompts['e2'], 20)
                cap(f'LIVE · cache hit ({r.get("cache") or "shared"}): {sec(r["ms"])}, {tok(r)} tokens, $0. No model was called',
                    LIVE.replace('demo_live', 'demo_v3'))
                p.wait_for_timeout(3000); snap('twice')
            shot(4, 'twice', again)

            # 5. FizzBuzz on the 30B
            def fizz(b0):
                cap('FizzBuzz does not need a frontier model')
                at(b0 + 1.0)
                r = ask('fizz', prompts['c2'], 8)
                d = (step(r, 'draft') or [{}])[0]
                cap(f'LIVE · our 30B wrote it: {sec(r["ms"])}, {tok(r)} tokens, $0 in tokens (confidence {d.get("confidence", 0):.2f})',
                    LIVE.replace('demo_live', 'demo_v3'))
                at(b0 + max(now() - b0 + 1.6, cue(5, 'and every token')))
                kept = (step(r, 'final') or [{}])[0].get('tokens_kept_off_big', tok(r))
                cap(f'{kept} tokens kept off the 763B. The A6000 is ours, so it is priced $0', 'live call · ' + A6)
                p.wait_for_timeout(1200); snap('fizz')
            shot(5, 'fizz', fizz)

            # 6. a hard task: the 30B is unsure, the call climbs to the 763B
            def climb(b0):
                cap('A hard design task')
                at(b0 + 1.0)
                r = ask('climb', prompts['h2'], 6)
                d = (step(r, 'draft') or [{}])[0]
                if r.get('tier') == 'cloud-deepseek' and d.get('confidence') is not None:
                    cap(f'LIVE · the 30B was unsure ({d["confidence"]:.2f}, below {d["gate"]:.2f}), so the call climbed to the 763B',
                        LIVE.replace('demo_live', 'demo_v3'))
                else:
                    cap(f'LIVE · answered by {r.get("tier")}: {sec(r["ms"])}', LIVE.replace('demo_live', 'demo_v3'))
                at(b0 + max(now() - b0 + 3.0, cue(6, 'Here is a loss')))
                cap(f'A loss: {sec(r["ms"])} and ${r.get("dollars", 0):.5f} with the climb. '
                    f'The 763B alone took {sec(base_h2["base_ms"])} in the saved run', 'live call · ' + V3)
                p.wait_for_timeout(3000); snap('climb')
            shot(6, 'climb', climb)

            # 7. the Ledger: the monthly bill
            def ledger(b0):
                js('MovieGame.closePanel()')
                p.wait_for_timeout(400)
                room('ledger')
                p.wait_for_selector('.m-cost', timeout=8000)
                cap('The bill: a month of coding calls', COST)
                at(b0 + 2.2); scroll("document.querySelector('.m-cost').offsetTop - document.getElementById('m-pbody').offsetTop - 8", 2.0)
                at(b0 + cue(7, 'When three in ten') - 0.6); p.click('.m-cost [data-h="repeats_30"]')
                at(b0 + cue(7, 'When three in ten')); cap('With 30% repeats: 62% to 87% less than GPT-5.5 alone', COST)
                at(b0 + cue(7, 'Now the loss') - 1.2)
                snap('ledger_gpt55')
                scroll("document.querySelector('.m-cost .m-cost-g').offsetTop - document.getElementById('m-pbody').offsetTop - 8", 1.2)
                at(b0 + cue(7, 'Now the loss'))
                cap('A loss: at 100,000 calls a day the cheap 763B alone costs less. We cost 607% more', COST)
                p.wait_for_timeout(3000); snap('ledger_loss')
            shot(7, 'ledger', ledger)

            # 8. the Workshop
            def workshop(b0):
                js('MovieGame.closePanel()')
                p.wait_for_timeout(400)
                room('workshop')
                p.wait_for_selector('.m-keys', timeout=8000)
                cap(f'Built with Kiro: {len(K["steering"])} steering files, {len(K["specs"])} specs, {len(K["hooks"])} hooks, '
                    f'{len(K["agents"])} agents, MCP tools and a Power', '.kiro/')
                at(b0 + 3.5); snap('workshop')
                scroll("Math.min(document.getElementById('m-pbody').scrollHeight, 900)", 5.0)
                at(b0 + cue(8, 'Property tests'))
                cap(f'Property tests from the specs found {K["bugs_found"]} real bugs. {K["bugs_fixed"]} are fixed',
                    'docs/handoff/property-tests.md')
            shot(8, 'workshop', workshop)

            # 9. the pitch card, then 10. the A6000 card, over the moving painted landing
            def closing(b0):
                js('demoCap("")')
                js('MovieGame.closePanel()')
                js('MovieGame.jump(0, false)')
                p.wait_for_timeout(500)
                js('''() => { const d = document.createElement('div'); d.id = 'demo-card';
                  d.innerHTML = '<h1>CHIMERA</h1><p class="p">Stop paying a frontier model for FizzBuzz. We prove it with tests.</p>' +
                    '<p class="n"><span class="dwin">62% to 87% less than GPT-5.5 a month</span> (30% repeats)<br><span class="dlose">and 607% more than the cheap 763B at 100,000 calls a day</span></p>' +
                    '<p class="f">bench/results_company_cost.md · github.com/manvendersingh21/tremor-core · Kiroween 2026</p>';
                  for (const id of ['m-say', 'm-mode']) { const e = document.getElementById(id); if (e) e.style.visibility = 'hidden'; }
                  d.style.background = 'radial-gradient(ellipse at center,rgba(12,4,18,.72),rgba(6,2,10,.9))';
                  document.body.appendChild(d); requestAnimationFrame(() => d.classList.add('on')); }''')
                marks[-1]['captions'].append({'at': round(now(), 2), 'text': 'Stop paying a frontier model for FizzBuzz. We prove it with tests.', 'src': COST})
                turn(0.12, 2.0); snap('closing')
            shot(9, 'closing', closing)

            def card(b0):
                js('''(h) => { const d = document.getElementById('demo-card'); d.classList.remove('on');
                  setTimeout(() => { d.innerHTML = h; d.classList.add('on'); }, 1000); }''', card_html)
                marks[-1]['captions'].append({'at': round(now() + 1, 2), 'text': f'On our own A6000: {A["cut"]}% fewer 763B calls, 0 wrong answers from the cache; '
                                              f'{A["ladder_ok"]} of {A["n"]} coding tasks right vs {A["base_ok"]} for the 763B alone. '
                                              f'A loss: slower on a first pass', 'src': A6})
                turn(-0.24, 6.0); snap('a6000'); turn(0.12, 4.0)
            shot(10, 'a6000', card)

        cdp.send('Page.stopScreencast')
        p.wait_for_timeout(300)
        total = now()
        fps_in = len(stamps) / max(1e-6, stamps[-1] - stamps[0]) if len(stamps) > 1 else 0
        ctx.close()
        b.close()

    for m in marks:
        print(m['n'], m['shot'], m['planned_start'], m['start'], m.get('end'), {k: v for k, v in m.items() if k.endswith(('_s', '_by', '_a_a'))})
    for k, c in calls.items():
        print(k, c.get('tier'), c.get('cache'), c.get('ms'), c.get('tokens_in'), c.get('tokens_out'), c.get('dollars'))
    if full:
        tiers = {k: (c.get('tier'), c.get('cache')) for k, c in calls.items()}
        ok = (tiers['first'] == ('gpu-small', None) and tiers['repeat'][1] == 'shared' and tiers['fizz'][0] == 'gpu-small'
              and tiers['climb'][0] == 'cloud-deepseek')
        if not ok:
            raise SystemExit(f'the calls did not go the way the narration says: {tiers}; use a fresh cache tenant and record again')
        if total > MAX_S:
            raise SystemExit(f'the take ran {total:.1f} s, over 2:59; record again')
    lines = [{'shot': m['n'], 'start': m['start'], 'at': round(m['start'] + LEAD, 2), 'dur': round(dur[m['n']], 2), 'text': say[m['n']],
              'clip': VDIR / f"{m['n']:02d}.mp3"} for m in marks]
    for x, m in zip(lines, marks):
        if x['at'] + x['dur'] > m['end'] + 0.05:
            raise SystemExit(f"shot {m['n']}: the line runs past the shot end")
    silent = TMP / ('video.mp4' if full else 'video_rehearse.mp4')
    n = encode(stamps, frames, t_zero, total, silent)
    mp4 = OUT / 'demo_v3.mp4' if full else TMP / 'rehearse.mp4'
    mux(silent, lines, mp4)
    check = gaps(mp4)
    print(json.dumps(check))
    if not full:
        print(mp4)
        return
    (OUT / 'demo_v3.srt').write_text('\n'.join(f"{k + 1}\n{srt_time(x['at'])} --> {srt_time(x['at'] + x['dur'])}\n{x['text']}\n"
                                               for k, x in enumerate(lines)))
    keepk = ('ts', 'prompt', 'tier', 'model', 'cache', 'score', 'tokens_in', 'tokens_out', 'ms', 'dollars', 'dollars_saved', 'steps', 'asked_at', 'answered_at')
    info = {'url': url, 'mode': 'live', 'screencast_frames': n, 'screencast_fps': round(fps_in, 1), 'seconds': round(total, 2),
            'video': probe(mp4), 'voice': VOICE, 'characters': sum(map(len, say.values())), 'a6000': A, 'gaps': check,
            'lines': [{k: v for k, v in x.items() if k != 'clip'} for x in lines],
            'calls': {k: {x: v[x] for x in keepk if x in v} for k, v in calls.items()}, 'shots': marks}
    (OUT / 'demo_v3.json').write_text(json.dumps(info, indent=1) + '\n')
    print(mp4, mp4.stat().st_size // 1024, 'KB')


if __name__ == '__main__':
    main()
