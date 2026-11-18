"""Voice the demo cuts with ElevenLabs text-to-speech (the user approved an AI voice). site/docs/demo_live.md

    .venv/bin/python scripts/demo_voice.py live   # site/docs/demo_live.mp4   -> site/docs/demo_voiced.mp4
    .venv/bin/python scripts/demo_voice.py v2     # site/docs/demo_cut_v2.mp4 -> site/docs/demo_cut_v2_voiced.mp4

The lines are read from the docs ("**Shot N (m:ss).** "..."" in demo_live.md or demo_video.md), one request per shot,
and each clip starts when its shot starts (shot times from demo_live.json / demo_cut.json). A clip that runs into the
next shot pushes the next clip later; the run prints the drift. Clips are kept in bench/.scratch/demo_voice/<cut>/
(git-ignored) and never synthesized twice: the free quota is 10,000 characters. ELEVENLABS_API_KEY comes from .env.
The silent cuts stay as they are.
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import conftest  # noqa: E402,F401  registers chimera_core
from chimera_core.config import load_env  # noqa: E402

DOCS = ROOT / 'site/docs'
VOICE = {'name': 'George - Warm, Captivating Storyteller', 'voice_id': 'JBFqnCBsd6RMkjVDRZzb', 'model_id': 'eleven_multilingual_v2',
         'output_format': 'mp3_44100_128',
         'voice_settings': {'stability': 0.5, 'similarity_boost': 0.75, 'style': 0.0, 'use_speaker_boost': True, 'speed': 1.0}}
SAY = [('763B', '763-B'), ('30B', '30-B'), ('A6000', 'A 6000')]   # how the model names are said; the text is otherwise as written
MAX_S = 178.9
LINE = re.compile(r'^\*\*Shot (\d+) \((\d+):(\d+)\)\.\*\* "(.+)"\s*$')


def lines(md: Path, section: str) -> dict[int, str]:
    text = md.read_text().split(section, 1)[1].split('\n## ', 1)[0]
    return {int(m[1]): m[4] for m in map(LINE.match, text.splitlines()) if m}


def script(cut: str) -> list[dict]:
    live = lines(DOCS / 'demo_live.md', '## Narration to read (`demo_live.mp4`)')
    if cut == 'live':
        shots = json.loads((DOCS / 'demo_live.json').read_text())['shots']
        return [{'shot': i + 1, 'start': s['start'], 'text': live[i + 1]} for i, s in enumerate(shots)]
    old = lines(DOCS / 'demo_video.md', '## Narration to read')
    shots = json.loads((DOCS / 'demo_cut.json').read_text())['shots']
    out = [{'shot': i + 1, 'start': s['start'], 'text': old[i + 1]} for i, s in enumerate(shots)]
    h, m, s = re.findall(r'^(\d+):(\d+):([\d,]+) --> ', (DOCS / 'demo_cut_v2.srt').read_text(), re.M)[-1]
    card = int(h) * 3600 + int(m) * 60 + float(s.replace(',', '.'))   # the A6000 card's cue: when it starts to fade in
    return out + [{'shot': 10, 'start': round(card - 0.3, 2), 'text': live[10]}]


def duration(f: Path) -> float:
    return float(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(f)],
                                capture_output=True, text=True, check=True).stdout)


def synth(text: str, out: Path, voice: dict = VOICE, say: list = SAY) -> None:
    for a, b in say:
        text = text.replace(a, b)
    body = json.dumps({'text': text, 'model_id': voice['model_id'], 'voice_settings': voice['voice_settings']}).encode()
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{voice['voice_id']}?output_format={voice['output_format']}",
                                 data=body, headers={'xi-api-key': os.environ['ELEVENLABS_API_KEY'], 'Content-Type': 'application/json',
                                                     'Accept': 'audio/mpeg'})
    with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 (fixed https host)
        data = r.read()
    if len(data) < 1000:
        raise SystemExit(f'{out.name}: the reply is not audio ({len(data)} bytes)')
    out.write_bytes(data)


def main() -> None:
    cut = sys.argv[1] if len(sys.argv) > 1 else 'live'
    src, dst = {'live': ('demo_live.mp4', 'demo_voiced.mp4'), 'v2': ('demo_cut_v2.mp4', 'demo_cut_v2_voiced.mp4')}[cut]
    load_env()
    lines_ = script(cut)
    chars = sum(len(x['text']) for x in lines_)
    if chars > 2500:
        raise SystemExit(f'{chars} characters: over the ~2,400 budget for one cut')
    store = ROOT / 'bench/.scratch/demo_voice' / cut
    store.mkdir(parents=True, exist_ok=True)
    for x in lines_:   # once per line; an existing clip is never paid for again
        f = store / f"{x['shot']:02d}.mp3"
        if not f.exists():
            synth(x['text'], f)
        x['clip'], x['dur'] = f, round(duration(f), 2)
    t_end = 0.0
    for x in lines_:   # start with the shot; never over the clip before it
        x['at'] = round(max(x['start'] + 0.3, t_end + 0.35), 2)
        x['drift'] = round(x['at'] - x['start'] - 0.3, 2)
        t_end = x['at'] + x['dur']
    video = DOCS / src
    vd = duration(video)
    total = min(MAX_S, max(vd, t_end + 1.0))
    if t_end > MAX_S - 0.5:
        raise SystemExit(f'the voice ends at {t_end:.1f} s, over 2:59')
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-i', str(video)] + sum((['-i', str(x['clip'])] for x in lines_), [])
    mix = ''.join(f"[{i + 1}:a]adelay={int(x['at'] * 1000)}:all=1[a{i}];" for i, x in enumerate(lines_))
    mix += ''.join(f'[a{i}]' for i in range(len(lines_))) + f'amix=inputs={len(lines_)}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,' \
        f'aresample=48000,apad,atrim=0:{total:.2f}[voice]'
    if total > vd + 0.05:   # hold the last frame until the voice ends
        mix += f';[0:v]tpad=stop_mode=clone:stop_duration={total - vd + 0.05:.2f}[v]'
        vmap, vcodec = '[v]', ['-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-pix_fmt', 'yuv420p', '-r', '30']
    else:
        vmap, vcodec = '0:v', ['-c:v', 'copy']
    out = DOCS / dst
    subprocess.run(cmd + ['-filter_complex', mix, '-map', vmap, '-map', '[voice]', *vcodec, '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
                          '-t', f'{total:.2f}', '-movflags', '+faststart', str(out)], check=True)
    rec = {'video': dst, 'from': src, 'seconds': round(duration(out), 2), 'characters': chars,
           'voice': {k: v for k, v in VOICE.items()}, 'said_as': SAY,
           'lines': [{k: x[k] for k in ('shot', 'start', 'at', 'drift', 'dur', 'text')} for x in lines_]}
    (DOCS / dst.replace('.mp4', '.json')).write_text(json.dumps(rec, indent=1) + '\n')
    for x in lines_:
        print(x['shot'], x['start'], x['at'], x['dur'], 'drift', x['drift'])
    print(out, rec['seconds'], 's,', chars, 'characters')


if __name__ == '__main__':
    main()
