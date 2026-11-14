"""Generate the walk-through clips for the painted game with an image-to-video model on GMI (keys from .env only).

  gen_video.py probe                       one cheap 4 s 480p test, to see which image input the API accepts
  gen_video.py run [clip ...]              generate clips from site/game/clips.json (skips clips already made)
  gen_video.py list                        show the clip plan and what exists

Each clip starts from a keyframe image. When a clip has "from": "<other clip>", its first frame is the LAST
frame of that clip, so the walk joins without a cut. Every call is appended to bench/.scratch/video/calls.jsonl
(model, seconds, resolution, price) so a restart resumes and site/art/README.md can list the spend.
"""
import base64, io, json, os, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "site" / "game" / "clips.json"
OUT = ROOT / "site" / "game" / "clips"
LOG = ROOT / "bench" / ".scratch" / "video"
QUEUE = "https://console.gmicloud.ai/api/v1/ie/requestqueue/apikey/requests"
PRICE = {"480p": 0.07, "720p": 0.152, "1080p": 0.374}  # seedance-2-0 per second (docs.gmicloud.ai)


def key(name):
    k = os.environ.get(name)
    env = ROOT / ".env"
    if not k and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith(name + "="):
                k = line.split("=", 1)[1].strip().strip("'\"")
    if not k:
        sys.exit(f"{name} missing (env or .env)")
    return k


def http(url, body=None, timeout=120):
    h = {"User-Agent": "tremor-video/1.0", "Authorization": f"Bearer {key('GMI_API_KEY')}", "Content-Type": "application/json"}
    req = urllib.request.Request(url, json.dumps(body).encode() if body is not None else None, h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:  # show the API's reason, never the request headers
        raise RuntimeError(f"HTTP {e.code}: {e.read()[:400].decode(errors='replace')}") from None


def data_url(path, width=1280):
    im = Image.open(path).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def last_frame(mp4, out_png):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.08", "-i", str(mp4), "-frames:v", "1", "-update", "1", str(out_png)], check=True)
    return out_png


def log(row):
    LOG.mkdir(parents=True, exist_ok=True)
    with open(LOG / "calls.jsonl", "a") as f:
        f.write(json.dumps(row) + "\n")


def submit(payload, model):
    r = http(QUEUE, {"model": model, "payload": payload})
    rid = r.get("request_id") or r.get("id")
    if not rid:
        raise RuntimeError(f"no request id: {str(r)[:300]}")
    return rid


def wait(rid, limit_s=1500):
    t0 = time.time()
    while time.time() - t0 < limit_s:
        time.sleep(8)
        s = http(f"{QUEUE}/{rid}")
        st = s.get("status")
        if st == "success":
            o = s.get("outcome") or {}
            if o.get("video_url"):
                return o["video_url"]
            media = o.get("media_urls") or o.get("video_urls") or []
            if not media:
                raise RuntimeError(f"success without a video url: keys {sorted(o)}")
            m = media[0]
            return m["url"] if isinstance(m, dict) else m
        if st in ("failed", "cancelled", "error"):
            raise RuntimeError(f"request {st}: {str(s.get('outcome') or s)[:400]}")
    raise RuntimeError("timeout")


def generate(name, spec, plan):
    out = OUT / f"{name}.mp4"
    if out.exists():
        print(name, "exists"); return out
    OUT.mkdir(parents=True, exist_ok=True)
    if "from" in spec:
        prev = generate(spec["from"], plan[spec["from"]], plan)
        first = last_frame(prev, LOG / f"{name}-first.png")
    else:
        first = ROOT / spec["first"]
    payload = {"prompt": spec["prompt"], "first_frame": data_url(first), "duration": spec.get("seconds", 5),
               "resolution": spec.get("resolution", "720p"), "ratio": "16:9", "generate_audio": False, "watermark": False}
    if spec.get("last"):
        payload["last_frame"] = data_url(ROOT / spec["last"])
    model = spec.get("model", "seedance-2-0-260128")
    t0 = time.time()
    pend = LOG / f"{name}.request"
    if pend.exists():  # a run that died after submitting: collect that request, do not pay again
        rid = pend.read_text().strip()
        print(name, "resuming", rid)
    else:
        rid = submit(payload, model)
        LOG.mkdir(parents=True, exist_ok=True); pend.write_text(rid)
        print(name, "submitted", rid)
    url = wait(rid)
    with urllib.request.urlopen(url, timeout=300) as r:
        raw = r.read()
    tmp = LOG / f"{name}.raw.mp4"; tmp.write_bytes(raw)
    # re-encode for scrubbing: every frame a keyframe so seeking backwards is instant
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-an", "-vf", "scale=1280:-2", "-c:v", "libx264", "-preset", "slow", "-crf", "22",
                    "-g", "6", "-bf", "0", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], check=True)
    pend.unlink(missing_ok=True)
    secs, res = payload["duration"], payload["resolution"]
    log({"ts": time.strftime("%F %T"), "clip": name, "model": model, "seconds": secs, "resolution": res,
         "usd": round(secs * PRICE.get(res, 0), 3), "wall_s": round(time.time() - t0), "bytes": out.stat().st_size})
    print(name, "done", out.stat().st_size // 1024, "KB")
    return out


def main():
    a = sys.argv[1:] or ["list"]
    plan = json.loads(PLAN.read_text())
    if a[0] == "list":
        for k, v in plan.items():
            print(("done " if (OUT / f"{k}.mp4").exists() else "todo ") + k, v.get("from", v.get("first")))
        return
    if a[0] == "probe":
        spec = {"prompt": "Slow cinematic push-in toward the castle, bats flying, fog drifting.", "first": "site/art/gate-1024.webp",
                "seconds": 4, "resolution": "480p"}
        generate("_probe", spec, {"_probe": spec}); return
    if a[0] == "run":
        for k in (a[1:] or list(plan)):
            generate(k, plan[k], plan)


if __name__ == "__main__":
    main()
