"""Cut the great door painting (site/art/great-door.webp) into an opening door, offline (Pillow + numpy, no network).

  door-frame.webp     the painting with the two door leaves cut out (alpha 0 there)
  door-leaf-l.webp    the left leaf, cropped to its box
  door-leaf-r.webp    the right leaf
  door.json           {"size": [w, h], "leaf_l": [x0, y0, x1, y1], "leaf_r": [...]} as fractions of the painting
Shape: a pointed arch read off the painting by eye. shortcut: hand-placed; redo it if great-door.webp is repainted.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "site" / "art" / "great-door.webp"
OUT = ROOT / "site" / "game" / "layers"
X0, XC, X1 = 0.312, 0.5, 0.688       # inner edge of the gold rim, the seam
APEX, SPRING, BOTTOM = 0.112, 0.30, 0.905
POW = 1.9                            # arch curve: top(x) = APEX + (SPRING - APEX) * d ** POW, d = |x - XC| / half width


def leaf_mask(w: int, h: int) -> np.ndarray:
    """True inside the doorway (both leaves)."""
    xs = (np.arange(w) + 0.5) / w
    ys = (np.arange(h) + 0.5) / h
    d = np.clip(np.abs(xs - XC) / (XC - X0), 0, 1)
    top = APEX + (SPRING - APEX) * d ** POW
    inside_x = (xs >= X0) & (xs <= X1)
    return inside_x[None, :] & (ys[:, None] >= top[None, :]) & (ys[:, None] <= BOTTOM)


def main() -> None:
    im = Image.open(SRC).convert("RGB")
    w, h = im.size
    m = leaf_mask(w, h)
    soft = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.0)), np.float32) / 255
    rgb = np.asarray(im)
    frame = np.dstack([rgb, ((1 - soft) * 255).astype(np.uint8)])
    OUT.mkdir(parents=True, exist_ok=True)
    Image.fromarray(frame, "RGBA").save(OUT / "door-frame.webp", "WEBP", quality=84, method=6)
    boxes = {}
    for name, (a, b) in (("leaf_l", (X0, XC)), ("leaf_r", (XC, X1))):
        px0, px1, py0, py1 = int(a * w), int(np.ceil(b * w)), int(APEX * h), int(np.ceil(BOTTOM * h))
        alpha = (soft[py0:py1, px0:px1] * 255).astype(np.uint8)
        leaf = np.dstack([rgb[py0:py1, px0:px1], alpha])
        Image.fromarray(leaf, "RGBA").save(OUT / f"door-{name[-1]}.webp".replace("door-", "door-leaf-"), "WEBP", quality=86, method=6)
        boxes[name] = [round(px0 / w, 5), round(py0 / h, 5), round(px1 / w, 5), round(py1 / h, 5)]
    (OUT / "door.json").write_text(json.dumps({"size": [w, h], **boxes}, indent=1) + "\n")
    print("wrote door-frame.webp, door-leaf-l.webp, door-leaf-r.webp", boxes)


if __name__ == "__main__":
    main()
