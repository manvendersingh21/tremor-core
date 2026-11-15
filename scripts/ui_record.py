"""Record the walk-in from page load to the Great Hall doors in headless Chrome (DevTools screencast), holding W.
Frames keep their real timestamps, so the MP4 plays at the walk's true speed.

  scripts/ui_record.py out.mp4 [out.gif]   (the page must be up on 127.0.0.1:8765; needs ffmpeg)"""
import asyncio, base64, json, shutil, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from cdp import Page  # noqa: E402

B = 'http://127.0.0.1:8765/'


class Rec(Page):
    """Page that also keeps screencast frames (cdp.Page drops events)."""
    frames: list

    async def _reader(self):
        import aiohttp
        async for msg in self.ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                break
            m = json.loads(msg.data)
            if m.get('method') == 'Page.screencastFrame':
                pr = m['params']
                self.frames.append((pr['metadata']['timestamp'], base64.b64decode(pr['data'])))
                asyncio.ensure_future(self.ws.send_json({'id': 10 ** 6 + len(self.frames), 'method': 'Page.screencastFrameAck', 'params': {'sessionId': pr['sessionId']}}))
                continue
            f = self.waiting.pop(m.get('id'), None)
            if f and not f.done():
                f.set_exception(RuntimeError(m['error'])) if 'error' in m else f.set_result(m.get('result', {}))


async def main(out, gif):
    p = await Rec.open(B, 1280, 720, extra=['--use-angle=metal'])
    p.frames = []
    await asyncio.sleep(6)
    await p.send('Page.startScreencast', format='jpeg', quality=85, maxWidth=1280, maxHeight=720, everyNthFrame=1)
    await asyncio.sleep(0.8)                                   # a moment at the closed gates
    await p.key('w'); t0 = time.time()
    for _ in range(200):
        await asyncio.sleep(0.05)
        if await p.js('MovieGame.state.hall'):
            break
    await asyncio.sleep(1.0)
    await p.key('w', False)
    await p.send('Page.stopScreencast')
    took = time.time() - t0
    frames = sorted(p.frames)
    await p.close()
    tmp = Path(tempfile.mkdtemp(prefix='rec-', dir=ROOT / 'bench/.scratch/ui'))
    lines = []
    for k, (ts, data) in enumerate(frames):
        (tmp / f'{k:05d}.jpg').write_bytes(data)
        nxt = frames[k + 1][0] if k + 1 < len(frames) else ts + 1 / 30
        lines += [f"file '{k:05d}.jpg'", f'duration {max(0.001, nxt - ts):.4f}']
    lines.append(f"file '{len(frames) - 1:05d}.jpg'")
    (tmp / 'list.txt').write_text('\n'.join(lines) + '\n')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(tmp / 'list.txt'), '-vf', 'fps=30,format=yuv420p',
                    '-c:v', 'libx264', '-crf', '24', '-preset', 'slow', '-movflags', '+faststart', str(out)], check=True)
    if gif:
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(out), '-vf', 'fps=12,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160[p];[b][p]paletteuse=dither=bayer:bayer_scale=4',
                        str(gif)], check=True)
    shutil.rmtree(tmp, ignore_errors=True)
    span = frames[-1][0] - frames[0][0] if frames else 0
    print(json.dumps({'frames': len(frames), 'seconds': round(span, 2), 'fps_captured': round(len(frames) / span, 1) if span else 0, 'w_to_hall_doors_s': round(took - 1.0, 2), 'mp4': str(out), 'gif': str(gif) if gif else None}))


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
