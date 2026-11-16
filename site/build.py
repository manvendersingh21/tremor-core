"""Write the no-JS fallback (doors and rooms) into index.html from rooms.js, and the saved results.

Usage: python3 site/build.py          rewrite index.html, results.json, demo.json and docs/tour_script.md
       python3 site/build.py --check  exit 1 if any of them is out of date
results.json: headline numbers from bench/*.md (results.py). demo.json: what the page shows with no backend (demo.py).
"""
import json
import pathlib
import re
import sys
from html import escape as e

HERE = pathlib.Path(__file__).parent
BASE = "https://github.com/manvendersingh21/tremor-core/blob/dev/"


def load(kiro_posters=None):
    raw = (HERE / "rooms.js").read_text(encoding="utf-8")
    rooms = json.loads(raw.split("=", 1)[1].strip().rstrip(";"))
    for r in rooms:
        if r.get("generated") == "kiro" and kiro_posters is not None:
            r["posters"] = kiro_posters   # counted from .kiro/ and tests/ at build time (demo.py kiro())
    return rooms


def poster(p):
    body = ""
    if p.get("big"):
        body += f'<p class="big">{e(p["big"])}</p>'
    if p.get("steps"):
        body += '<ol class="steps">' + "".join(f"<li>{e(s)}</li>" for s in p["steps"]) + "</ol>"
    body += "".join(f"<p>{e(t)}</p>" for t in p["lines"])
    label, path = p["src"]
    return (f'<article class="poster"><h3>{e(p["title"])}</h3>{body}'
            f'<p class="fn"><a href="{BASE}{e(path)}">{e(label)}</a></p></article>')


def doors(rooms):
    return "".join(
        f'<a class="door" href="#r-{r["id"]}"><span class="plaque"><strong>{e(r["title"])}</strong>'
        f'<span>{e(r["door"])}</span></span></a>' for r in rooms)


def sections(rooms):
    return "".join(
        f'<section class="room-static" id="r-{r["id"]}"><h2>{e(r["title"])}</h2>'
        f'<p class="section-lead">{e(" ".join(r["say"]))}</p>'
        f'<div class="poster-grid">{"".join(poster(p) for p in r["posters"])}</div>'
        '<p><a href="#hall">Back to the hall</a></p></section>' for r in rooms)


def build(kiro_posters=None):
    rooms = load(kiro_posters)
    html = (HERE / "index.html").read_text(encoding="utf-8")
    for name, val in (("doors", doors(rooms)), ("rooms", sections(rooms))):
        html = re.sub(rf"(<!-- BUILD:{name} -->).*?(<!-- /BUILD:{name} -->)",
                      lambda m: m.group(1) + val + m.group(2), html, flags=re.S)
    return html


def outputs():
    """{path: text} of every file this build writes. Numbers are read from bench/, .kiro/ and tests/, never typed."""
    sys.path.insert(0, str(HERE))
    import demo
    import results
    d = demo.build_dict()
    return {HERE / "index.html": build(d["kiro"]["posters"]), HERE / "results.json": results.build(),
            HERE / "demo.json": json.dumps(d, indent=1, ensure_ascii=False) + "\n", HERE / "docs" / "tour_script.md": demo.tour_script(d)}


if __name__ == "__main__":
    out = outputs()
    if "--check" in sys.argv:
        stale = [str(p.relative_to(HERE)) for p, t in out.items() if not p.is_file() or p.read_text(encoding="utf-8") != t]
        if stale:
            print("out of date (run python3 site/build.py):", ", ".join(stale), file=sys.stderr)
        sys.exit(1 if stale else 0)
    for p, t in out.items():
        p.write_text(t, encoding="utf-8")
