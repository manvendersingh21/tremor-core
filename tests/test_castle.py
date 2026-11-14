"""3D castle (site/castle): layout schema, vendored three.js, page wiring, and walking rules via node if present."""
import json
import pathlib
import shutil
import subprocess

import pytest

SITE = pathlib.Path(__file__).resolve().parent.parent / "site"
L = json.loads((SITE / "castle" / "layout.json").read_text())


def test_layout_schema():
    assert L["version"] == 1 and set(L["levels"]) == {"ground", "upper"}
    assert {z["id"] for z in L["zones"]} == {"courtyard", "hall", "gallery"}
    assert [d["id"] for d in L["doors"]] == ["dashboard", "chat", "evals"]  # gate -> guide -> stairs -> three doors
    for w in L["walls"]:
        assert w["x0"] < w["x1"] and w["z0"] < w["z1"] and w["level"] in ("ground", "upper", "both"), w["id"]
    ids = {p["id"] for p in L["places"]}
    assert {"gate", "guide", "board", "stairs", "dashboard", "chat", "evals"} <= ids


def test_three_is_vendored_with_licence():
    js = (SITE / "vendor" / "three.module.min.js").read_text(encoding="utf-8", errors="ignore")
    assert "SPDX-License-Identifier: MIT" in js[:400] and "import " not in js[:2000]  # self-contained, no CDN
    assert "MIT" in (SITE / "vendor" / "three.LICENSE.txt").read_text()


def test_page_loads_the_castle_and_keeps_a_plain_fallback():
    html = (SITE / "index.html").read_text()
    assert "castle/castle.js" in html and "castle/physics.js" in html and "castle/panels.js" in html
    assert "webgl" in html and 'id="static-rooms"' in html  # no WebGL: the plain sections show
    assert "world/world.js" not in html  # the 2D castle is off the main path
    assert "https://unpkg" not in html and "cdn" not in html.lower()


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_walk_gate_stairs_gallery():
    js = f"""
const L=require({json.dumps(str(SITE / 'castle' / 'layout.json'))}), P=require({json.dumps(str(SITE / 'castle' / 'physics.js'))}).make(L);
let p={{x:0,z:30,level:'ground'}}; const walk=(dx,dz,n,open)=>{{for(let i=0;i<n;i++)p=P.move(p,dx,dz,open)}};
const out={{}};
walk(0,-0.1,300,false); out.closed=p.z;
walk(0,-0.1,60,true); out.hall=[p.z,p.level];
p={{x:0,z:-5,level:'ground'}}; walk(0,-0.1,200,true); out.top=[p.z,p.y,p.level];
p={{x:0,z:-25,level:'ground'}}; walk(0,0.1,100,true); out.under=[p.z,p.y];
p={{x:-8,z:-22,level:'upper'}}; walk(0,0.1,100,true); out.rail=p.z;
console.log(JSON.stringify(out));"""
    o = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert o["closed"] > 0  # the closed gate blocks
    assert o["hall"][0] < -2 and o["hall"][1] == "ground"  # the open gate lets you in
    assert o["top"][1] == L["levels"]["upper"] and o["top"][2] == "upper"  # the stairs take you up
    assert o["under"][1] == 0 and o["under"][0] < -17.9  # from under the gallery you cannot step onto the top stair
    assert o["rail"] < -17.7  # the gallery railing stops you
