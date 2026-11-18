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


def test_page_loads_the_walk_in_game_and_keeps_a_plain_fallback():
    html = (SITE / "index.html").read_text()
    assert "game/walk.js" in html and "game/panels.js" in html and "game/walk.css" in html
    assert 'id="static-rooms"' in html  # if the game cannot start, the plain sections show
    assert "world/world.js" not in html and "castle/castle.js" not in html  # older castles are off the main path
    assert "https://unpkg" not in html and "cdn" not in html.lower()


def test_walk_clip_plan():
    plan = json.loads((SITE / "game" / "clips.json").read_text())
    walk = (SITE / "game" / "walk.js").read_text()
    for k, v in plan.items():
        assert v.get("first") or v.get("from") in plan, k  # each clip starts on a keyframe or on the clip before
        for f in (v.get("first"), v.get("last")):
            assert f is None or (SITE.parent / f).is_file(), f
    for seg in ("a-approach", "b-gates", "c-drive", "d-door", "e-hall"):
        assert seg in plan and f"'{seg}'" in walk


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


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_3d_walk_rail_only_goes_forward_and_reaches_the_hall_in_4_s():
    """The walk-in is one rail (site/game/world3d.js): z falls with every step, so W can never take you back."""
    js = f"""
const m = await import({json.dumps((SITE / 'game' / 'world3d.js').as_uri())});
const zs = []; for (let s = 0; s <= m.S_END; s += 0.01) zs.push(m.railZ(s));
console.log(JSON.stringify({{mono: zs.every((z, i) => i === 0 || z < zs[i - 1]), hall: m.S_HALL, gate: m.railS(m.PLAN.gateZ), door: m.railS(m.PLAN.doorZ),
  inside: m.railZ(m.S_HALL) < m.PLAN.hallZ0, start: m.railZ(0), rooms: m.SLOTS.map((s) => s.room)}}));"""
    o = json.loads(subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert o["mono"]  # never a step back
    assert o["start"] > 0 and 1.2 < o["gate"] < 2.0 < o["door"] < o["hall"] <= 4.0  # gates about 1.5 s, the hall by 4 s
    assert o["inside"] and len(set(o["rooms"])) == 10
    walk = (SITE / "game" / "walk.js").read_text()
    assert "open: { gates: false, door: false }" in walk  # the gates and the door are shut when the page opens
    assert "drag.moved < 6" in walk and "!S.open[t.kind]) arrive(t.kind)" in walk  # a click (not a drag) opens the gate you look at
