"""Copy chosen round screenshots into site/docs/rounds/ (JPEG, phone shots at half size, so the Pages build stays small).
Usage: .venv/bin/python scripts/ui_round_shots.py <round> <config> <shot> [<shot> ...]   e.g. r3 chromium_desktop_demo 03_hall"""
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
rnd, cfg, *shots = sys.argv[1:]
out = ROOT / "site/docs/rounds"
out.mkdir(parents=True, exist_ok=True)
for s in shots:
    im = Image.open(ROOT / "bench/.scratch/ui/rounds" / rnd / cfg / f"{s}.jpg")
    if im.height > im.width:   # phone shots are 3x and portrait: keep half
        im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
    f = out / f"{rnd}_{cfg}_{s}.jpg"
    im.convert("RGB").save(f, quality=74)
    print(f.relative_to(ROOT), f.stat().st_size // 1024, "KB")
