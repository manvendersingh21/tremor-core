"""Generate site art. Keys come from env or .env only (never printed).

  gen_art.py [--provider gmi|minimax] [--force] [--enrich] [name ...]
  gen_art.py --critique NAME "what the image looks like"

gmi: Seedream 5.0 Pro on the GMI request-queue API. minimax: image-01 direct.
--enrich: MiniMax-M3 (GMI chat API) rewrites each prompt once, cached in
site/art/prompts.enriched.json, and that version is used for generation.
Skips existing files. Writes .webp (<= ~400 KB) into site/art/.
"""
import base64, io, json, os, sys, time, urllib.request
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "site" / "art"
MAX_BYTES = 400_000
GMI_QUEUE = "https://console.gmicloud.ai/api/v1/ie/requestqueue/apikey/requests"
GMI_CHAT = "https://api.gmi-serving.com/v1/chat/completions"
MINIMAX = "https://api.minimax.io/v1/image_generation"
SEEDREAM = {"16:9": "2688x1512", "3:4": "1800x2400", "4:3": "2400x1800", "1:1": "2048x2048"}  # >= 3.6M px
calls = {"m3": 0, "image": 0}


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


def http(url, body=None, token=None, timeout=300):
    h = {"User-Agent": "tremor-art/1.0", "Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    req = urllib.request.Request(url, json.dumps(body).encode() if body is not None else None, h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def m3(system, user):
    calls["m3"] += 1
    d = http(GMI_CHAT, {"model": "MiniMaxAI/MiniMax-M3", "max_tokens": 1500, "temperature": 0.7,
                        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
             key("GMI_API_KEY"))
    t = d["choices"][0]["message"]["content"]
    return t.split("</think>")[-1].strip()


DIRECTOR = ("You are an art director for a gothic romance website (Dracula, Beauty and the Beast rose, wine red, "
            "candle gold). Target look: cinematic painterly Victorian gothic manor at night with warm glowing windows, "
            "a big glowing orange moon, purple clouds, bats, candles, fog, rich glossy stylized painted quality. "
            "Rewrite the image prompt to be richer and more specific for an image model. Keep the subject, framing and "
            "empty-space requirements. Forbid text, letters, logos, copyrighted characters. Max 1200 characters. "
            "Reply with the prompt only.")


def enriched(name, spec, style):
    f = ART / "prompts.enriched.json"
    cache = json.loads(f.read_text()) if f.exists() else {}
    if name not in cache:
        cache[name] = m3(DIRECTOR, f"{spec['prompt']} Style: {style}")[:1400]
        f.write_text(json.dumps(cache, indent=1))
    return cache[name]


def gen_gmi(prompt, spec):
    calls["image"] += 1
    r = http(GMI_QUEUE, {"model": "seedream-5.0-pro", "payload": {
        "prompt": prompt, "size": SEEDREAM[spec["aspect"]], "output_format": "jpeg", "watermark": False}},
        key("GMI_API_KEY"))
    rid = r.get("request_id") or r.get("id")
    for _ in range(120):
        time.sleep(4)
        s = http(f"{GMI_QUEUE}/{rid}", token=key("GMI_API_KEY"))
        if s.get("status") == "success":
            with urllib.request.urlopen(s["outcome"]["media_urls"][0][
                    "url"] if isinstance(s["outcome"]["media_urls"][0], dict) else s["outcome"]["media_urls"][0]) as u:
                return [u.read()]
        if s.get("status") in ("failed", "cancelled"):
            sys.exit(f"GMI request {s.get('status')}")
    sys.exit("GMI timeout")


def gen_minimax(prompt, spec):
    calls["image"] += 1
    d = http(MINIMAX, {"model": "image-01", "prompt": prompt[:1500], "aspect_ratio": spec["aspect"],
                       "response_format": "base64", "n": spec["n"]}, key("MINIMAX_API_KEY"))
    if d.get("base_resp", {}).get("status_code", 0) != 0:
        sys.exit(f"MiniMax error: {d['base_resp'].get('status_msg')}")
    return [base64.b64decode(b) for b in d["data"]["image_base64"]]


def save(raw, path, width):
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    if im.width != width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    q = 82
    while True:
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=q, method=6)
        if buf.tell() <= MAX_BYTES or q <= 55:
            break
        q -= 4
    path.write_bytes(buf.getvalue())
    print(path.name, buf.tell() // 1024, "KB", im.size)
    if width >= 2048:  # 1024 srcset variant
        im.resize((1024, round(im.height / 2)), Image.LANCZOS).save(path.with_name(path.stem + "-1024.webp"), quality=80)


def main():
    a = sys.argv[1:]
    P = json.loads((ART / "prompts.json").read_text())
    style = P.pop("_style")
    if a and a[0] == "--critique":
        print(m3("You are a strict art director. Given a description of a generated image and its brief, reply "
                 "'OK' or 'REGENERATE: <fix>' in one line. Flag cheap, flat, clip-art, cartoon, blurry, off-style "
                 "or lettered images.", f"Brief: {P[a[1]]['prompt']}\nImage: {a[2]}"))
        return
    prov = a[a.index("--provider") + 1] if "--provider" in a else "gmi"
    names = [x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or a[i - 1] != "--provider")]
    for name, spec in P.items():
        if names and name not in names:
            continue
        outs = [ART / (f"{name}-{i}.webp" if spec["n"] > 1 else f"{name}.webp") for i in range(1, spec["n"] + 1)]
        if "--force" not in a and all(o.exists() for o in outs):
            continue
        prompt = enriched(name, spec, style) if "--enrich" in a else f"{spec['prompt']} {style}"
        for o in outs:  # gmi: one image per request
            raws = gen_gmi(prompt, spec) if prov == "gmi" else None
            if prov != "gmi":
                for o2, r in zip(outs, gen_minimax(prompt, spec)):
                    save(r, o2, spec["width"])
                break
            save(raws[0], o, spec["width"])
    print("calls", calls)


if __name__ == "__main__":
    main()
