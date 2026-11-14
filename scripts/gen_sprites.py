"""Draw the walkable-castle sprites with Pillow into site/world/ (no network, no keys).

player.png: 4 columns (walk frames) x 3 rows (down, up, side-right; left is a mirror). Frame 48x64.
count.png:  2 frames (idle breathing), 48x64.
"""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "site" / "world"
S = 4  # draw at 4x then shrink
W, H = 48, 64


def cloak_frame(d: ImageDraw.ImageDraw, ox: int, oy: int, view: str, f: int) -> None:
    k = lambda v: int(v * S)
    bob = [0, -1, 0, -1][f]
    sway = [0, 2, 0, -2][f]
    cx = ox + 24
    top = oy + 10 + bob
    shadow = (0, 0, 0, 90)
    d.ellipse([k(cx - 13), k(oy + 54), k(cx + 13), k(oy + 61)], fill=shadow)
    # feet
    step = [(-3, 3), (0, 0), (3, -3), (0, 0)][f]
    if view == "side":
        step = (step[0] * 2, step[1] * 2)
    for dx, dy in ((-5, step[0]), (5, step[1])):
        if view == "side":
            dx = dx // 2
        d.ellipse([k(cx + dx - 4), k(oy + 54 + min(dy, 0)), k(cx + dx + 4), k(oy + 59)], fill=(18, 8, 24, 255))
    # cloak body (trapezoid, hem sways)
    wide = 15 if view != "side" else 11
    body = [(cx - 8, top + 14), (cx + 8, top + 14), (cx + wide + sway, oy + 56), (cx - wide + sway, oy + 56)]
    d.polygon([(k(x), k(y)) for x, y in body], fill=(46, 20, 66, 255), outline=(14, 5, 22, 255))
    if view == "down":  # wine lining opening and clasp
        inner = [(cx - 3, top + 14), (cx + 3, top + 14), (cx + 6 + sway, oy + 56), (cx - 6 + sway, oy + 56)]
        d.polygon([(k(x), k(y)) for x, y in inner], fill=(122, 20, 42, 255))
        d.ellipse([k(cx - 2), k(top + 15), k(cx + 2), k(top + 19)], fill=(236, 180, 70, 255))
    # hood
    d.ellipse([k(cx - 11), k(top - 4), k(cx + 11), k(top + 20)], fill=(38, 16, 56, 255), outline=(14, 5, 22, 255))
    if view == "down":
        d.ellipse([k(cx - 7), k(top + 2), k(cx + 7), k(top + 17)], fill=(14, 5, 22, 255))
        d.ellipse([k(cx - 5), k(top + 5), k(cx + 5), k(top + 16)], fill=(222, 206, 210, 255))
        for ex in (-3, 3):
            d.ellipse([k(cx + ex - 1.3), k(top + 9), k(cx + ex + 1.3), k(top + 12)], fill=(220, 30, 50, 255))
    elif view == "side":
        d.ellipse([k(cx - 1), k(top + 3), k(cx + 9), k(top + 17)], fill=(14, 5, 22, 255))
        d.ellipse([k(cx + 2), k(top + 6), k(cx + 9), k(top + 16)], fill=(222, 206, 210, 255))
        d.ellipse([k(cx + 5.5), k(top + 9), k(cx + 8), k(top + 12)], fill=(220, 30, 50, 255))
    else:  # back: hood seam
        d.line([k(cx), k(top), k(cx), k(oy + 54)], fill=(24, 9, 36, 255), width=k(1))


def sheet() -> Image.Image:
    img = Image.new("RGBA", (W * 4 * S, H * 3 * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for r, view in enumerate(("down", "up", "side")):
        for f in range(4):
            cloak_frame(d, f * W, r * H, view, f)
    return img.resize((W * 4, H * 3), Image.LANCZOS)


def count() -> Image.Image:
    img = Image.new("RGBA", (W * 2 * S, H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = lambda v: int(v * S)
    for f in range(2):
        ox, b = f * W, f  # breathing: collar rises one pixel
        cx = ox + 24
        d.ellipse([k(cx - 13), k(54), k(cx + 13), k(61)], fill=(0, 0, 0, 90))
        d.polygon([(k(cx - 9), k(26 - b)), (k(cx + 9), k(26 - b)), (k(cx + 17), k(57)), (k(cx - 17), k(57))], fill=(16, 8, 22, 255))
        d.polygon([(k(cx - 4), k(26)), (k(cx + 4), k(26)), (k(cx + 7), k(57)), (k(cx - 7), k(57))], fill=(140, 18, 40, 255))
        d.polygon([(k(cx - 9), k(26 - b)), (k(cx - 15), k(15 - b)), (k(cx - 4), k(24))], fill=(16, 8, 22, 255))  # collar
        d.polygon([(k(cx + 9), k(26 - b)), (k(cx + 15), k(15 - b)), (k(cx + 4), k(24))], fill=(16, 8, 22, 255))
        d.ellipse([k(cx - 7), k(8 - b), k(cx + 7), k(26 - b)], fill=(228, 216, 218, 255))
        d.pieslice([k(cx - 8), k(5 - b), k(cx + 8), k(21 - b)], 180, 360, fill=(10, 6, 14, 255))  # hair
        for ex in (-3, 3):
            d.ellipse([k(cx + ex - 1.3), k(15 - b), k(cx + ex + 1.3), k(18 - b)], fill=(220, 30, 50, 255))
        d.polygon([(k(cx - 1.5), k(21 - b)), (k(cx - 0.5), k(23 - b)), (k(cx + 0.5), k(21 - b))], fill=(255, 255, 255, 255))
        d.polygon([(k(cx + 1.5), k(21 - b)), (k(cx + 0.5), k(23 - b)), (k(cx - 0.5), k(21 - b))], fill=(255, 255, 255, 255))
        d.ellipse([k(cx - 2), k(27), k(cx + 2), k(31)], fill=(236, 180, 70, 255))
    return img.resize((W * 2, H), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    sheet().save(OUT / "player.png", optimize=True)
    count().save(OUT / "count.png", optimize=True)
    print("wrote", OUT / "player.png", OUT / "count.png")
