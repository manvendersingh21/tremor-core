"""Cut the painted landing (site/art/gate.webp) into game layers, offline (Pillow + numpy, no network).

  plate.webp   the scene with the iron-gate leaves and gate posts filled in (fog-like fill)
  leaf-l.png, leaf-r.png, post-l.png, post-r.png   cut-outs with alpha, drawn on top so they can move
Boxes are fractions of the image (x0, y0, x1, y1), read off the painting by eye.
"""
from pathlib import Path
import json
import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "site" / "art" / "gate.webp"
OUT = ROOT / "site" / "game" / "layers"
BOXES = {  # shortcut: hand-placed boxes; redo them if gate.webp is regenerated
    "leaf-l": (0.152, 0.495, 0.330, 0.912),
    "leaf-r": (0.698, 0.480, 0.862, 0.893),
    "post-l": (0.080, 0.440, 0.162, 0.915),
    "post-r": (0.850, 0.440, 0.932, 0.900),
}


def fill(rgb, mask):
    """Fill masked pixels by normalized convolution at falling blur radii (soft fog-like fill)."""
    valid = (~mask).astype(np.float32)
    est = np.broadcast_to(rgb[~mask].mean(0), rgb.shape).astype(np.float32)  # coarsest guess: the mean colour
    src = Image.fromarray((rgb * valid[..., None]).clip(0, 255).astype(np.uint8))
    w = Image.fromarray((valid * 255).astype(np.uint8))
    for r in (256, 128, 64, 32, 16, 8, 4):  # coarse to fine: each level fills what it can reach
        num = np.asarray(src.filter(ImageFilter.GaussianBlur(r)), np.float32)
        den = np.asarray(w.filter(ImageFilter.GaussianBlur(r)), np.float32)[..., None] / 255
        lvl = num / np.maximum(den, 1e-4)
        k = np.clip(den * 6, 0, 1)
        est = k * lvl + (1 - k) * est
    out = np.where(mask[..., None], est, rgb)
    rng = np.random.default_rng(3)
    out = np.where(mask[..., None], out + rng.normal(0, 3, out.shape), out)
    return out


def main():
    im = Image.open(SRC).convert("RGB")
    W, H = im.size
    rgb = np.asarray(im, np.float32)
    mask = np.zeros((H, W), bool)
    px = {k: (int(a * W), int(b * H), int(c * W), int(d * H)) for k, (a, b, c, d) in BOXES.items()}
    for x0, y0, x1, y1 in px.values():
        mask[y0:y1, x0:x1] = True
    plate = fill(rgb, mask)
    OUT.mkdir(parents=True, exist_ok=True)
    Image.fromarray(plate.clip(0, 255).astype(np.uint8)).save(OUT / "plate.webp", quality=84, method=6)
    lum = rgb.mean(2)
    plum = plate.mean(2)
    for k, (x0, y0, x1, y1) in px.items():
        # opaque where the painting differs from the fill: dark iron bars, stone, bright candles
        d = np.abs(lum[y0:y1, x0:x1] - plum[y0:y1, x0:x1])
        a = np.clip((d - 6) * 14, 0, 255)
        if k.startswith("post"):
            a = np.maximum(a, 200)  # posts are solid stone
        a = np.asarray(Image.fromarray(a.astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8)))
        rgba = np.dstack([rgb[y0:y1, x0:x1], a]).astype(np.uint8)
        Image.fromarray(rgba, "RGBA").save(OUT / f"{k}.png", optimize=True)
    (OUT / "boxes.json").write_text(json.dumps({"size": [W, H], "boxes": BOXES}, indent=1))
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
