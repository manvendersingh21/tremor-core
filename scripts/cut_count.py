"""Cut the full-length Count (site/art/count-full.webp, painted on a flat grey ground) into
site/game/layers/count-full.webp with alpha. Offline: Pillow + numpy, no model call.

The ground colour is the median of the border. Only ground that touches the border is removed
(flood fill), so dark cloth inside the figure is kept even when it is close to the ground colour.
"""
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "site" / "art" / "count-full.webp"
OUT = ROOT / "site" / "game" / "layers" / "count-full.webp"


def ground_mask(rgb: np.ndarray, tol: float) -> np.ndarray:
    """True where a pixel is ground: within `tol` of the border median and connected to the border."""
    h, w, _ = rgb.shape
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bg = np.median(border, axis=0)
    near = np.linalg.norm(rgb - bg, axis=2) < tol
    seen = np.zeros((h, w), bool)
    q = deque((y, x) for y in range(h) for x in (0, w - 1) if near[y, x])
    q.extend((y, x) for x in range(w) for y in (0, h - 1) if near[y, x])
    for y, x in q:
        seen[y, x] = True
    while q:
        y, x = q.popleft()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and near[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                q.append((ny, nx))
    return seen


def main(tol: float = 26.0) -> None:
    im = Image.open(SRC).convert("RGB")
    rgb = np.asarray(im, np.float32)
    ground = ground_mask(rgb, tol)
    a = Image.fromarray(np.where(ground, 0, 255).astype(np.uint8))
    a = a.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))  # pull the edge in, then feather it
    box = a.getbbox()
    out = Image.merge("RGBA", (*im.split(), a)).crop(box)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT, "WEBP", quality=86, method=6)  # keeps alpha
    print("wrote", OUT.name, out.size, "bbox", box)


if __name__ == "__main__":
    main()
