"""Write the no-JS fallback (doors and rooms) into index.html from rooms.js.

Usage: python3 site/build.py          rewrite index.html and results.json (numbers from bench/*.md)
       python3 site/build.py --check  exit 1 if index.html is out of date
"""
import json
import pathlib
import re
import sys
from html import escape as e

HERE = pathlib.Path(__file__).parent
BASE = "https://github.com/manvendersingh21/tremor-core/blob/dev/"


def load():
    raw = (HERE / "rooms.js").read_text(encoding="utf-8")
    return json.loads(raw.split("=", 1)[1].strip().rstrip(";"))


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


def build():
    rooms = load()
    html = (HERE / "index.html").read_text(encoding="utf-8")
    for name, val in (("doors", doors(rooms)), ("rooms", sections(rooms))):
        html = re.sub(rf"(<!-- BUILD:{name} -->).*?(<!-- /BUILD:{name} -->)",
                      lambda m: m.group(1) + val + m.group(2), html, flags=re.S)
    return html


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    import results
    out, path = build(), HERE / "index.html"
    res, rpath = results.build(), HERE / "results.json"   # numbers read from bench/*.md, never typed
    if "--check" in sys.argv:
        ok = out == path.read_text(encoding="utf-8") and rpath.is_file() and res == rpath.read_text(encoding="utf-8")
        sys.exit(0 if ok else 1)
    path.write_text(out, encoding="utf-8")
    rpath.write_text(res, encoding="utf-8")
