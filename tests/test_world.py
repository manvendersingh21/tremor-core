"""Walkable castle (site/world): map schema, reachability with a Python A* port, and grid.js itself via node if present."""
import heapq
import json
import math
import pathlib
import shutil
import subprocess

import pytest

WORLD = pathlib.Path(__file__).resolve().parent.parent / "site" / "world"
MAP = json.loads((WORLD / "map.json").read_text())
SOLID = set("#twbf~cD ")  # same set as grid.js
WALK = set(".,=Ud")


def solid(rows, x, y):
    return not (0 <= y < len(rows) and 0 <= x < len(rows[y])) or rows[y][x] in SOLID


def find_path(rows, s, g):
    """Port of CastleGrid.findPath: 8-neighbour A*, no corner cutting."""
    if solid(rows, *g):
        return None
    dist, todo, seen = {s: 0.0}, [(0.0, s)], set()
    while todo:
        _, (x, y) = heapq.heappop(todo)
        if (x, y) == g:
            return dist[g]
        if (x, y) in seen:
            continue
        seen.add((x, y))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                n = (x + dx, y + dy)
                if (dx, dy) == (0, 0) or solid(rows, *n) or (dx and dy and (solid(rows, x + dx, y) or solid(rows, x, y + dy))):
                    continue
                nd = dist[(x, y)] + (math.sqrt(2) if dx and dy else 1)
                if nd < dist.get(n, math.inf):
                    dist[n] = nd
                    heapq.heappush(todo, (nd + abs(n[0] - g[0]) + abs(n[1] - g[1]), n))
    return None


def test_schema():
    assert MAP["version"] == 1 and MAP["floors"]
    ids = [f["id"] for f in MAP["floors"]]
    assert ids == list(range(len(ids)))
    for f in MAP["floors"]:
        assert f["name"] and f["bg"] and 0 <= f["light"] <= 1
        assert len({len(r) for r in f["rows"]}) == 1, f"floor {f['id']} rows differ in width"
        assert set("".join(f["rows"])) <= SOLID | WALK, f"floor {f['id']} has unknown tiles"
    for d in MAP["doors"]:
        assert d["room"] in MAP["rooms"]
        assert MAP["floors"][d["floor"]]["rows"][d["y"]][d["x"]] == "D"
        assert MAP["rooms"][d["room"]]["floor"] == d["floor"]
    kinds = {r["kind"] for r in MAP["rooms"].values()}
    assert {"posters", "dashboard", "chat"} <= kinds
    assert any(n["kind"] == "bat" and n.get("room") == "agent" for n in MAP["npcs"])


def test_art_exists():
    site = WORLD.parent
    for f in MAP["floors"]:
        assert (site / f["bg"]).is_file(), f["bg"]
    for r in MAP["rooms"].values():
        assert (site / "art" / f"{r['art']}-1024.webp").is_file(), r["art"]


def test_every_door_npc_and_stair_is_reachable():
    floors = MAP["floors"]
    for f in floors:
        rows = f["rows"]
        start = tuple(f["arrive"].get("spawn") or next(iter(f["arrive"].values())))
        targets = [tuple(d["stand"]) for d in MAP["doors"] if d["floor"] == f["id"]]
        targets += [tuple(v) for v in f["arrive"].values()]
        targets += [tuple(r["stand"]) for r in MAP["rooms"].values() if r["floor"] == f["id"] and "stand" in r]
        for y, row in enumerate(rows):
            targets += [(x, y) for x, c in enumerate(row) if c in "Ud"]
        for t in targets:
            assert find_path(rows, start, t) is not None, f"floor {f['id']}: {t} not reachable from {start}"
        for n in (n for n in MAP["npcs"] if n["floor"] == f["id"]):
            near = [(n["x"] + a, n["y"] + b) for a, b in ((0, 1), (0, -1), (1, 0), (-1, 0))]
            assert any(not solid(rows, *p) and find_path(rows, start, p) is not None for p in near), n["id"]
    for f in floors:  # stairs up and down land on walkable tiles of the next floor
        if any("U" in r for r in f["rows"]) and f["id"] + 1 < len(floors):
            a = floors[f["id"] + 1]["arrive"]["fromBelow"]
            assert not solid(floors[f["id"] + 1]["rows"], *a)
        if any("d" in r for r in f["rows"]):
            a = floors[f["id"] - 1]["arrive"]["fromAbove"]
            assert not solid(floors[f["id"] - 1]["rows"], *a)


def test_python_port_basics():
    rows = ["#####", "#...#", "#.#.#", "#...#", "#####"]
    assert find_path(rows, (1, 1), (3, 3)) == pytest.approx(4.0)  # no corner cutting around the pillar
    assert find_path(rows, (1, 1), (2, 2)) is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_grid_js_matches_python():
    f = MAP["floors"][0]
    s, g = f["arrive"]["spawn"], MAP["doors"][0]["stand"]
    js = (f"const G=require({json.dumps(str(WORLD / 'grid.js'))});const r={json.dumps(f['rows'])};"
          f"const p=G.findPath(r,{s[0]},{s[1]},{g[0]},{g[1]});let c=0,x={s[0]},y={s[1]};"
          "for(const n of p){c+=(n.x!==x&&n.y!==y)?Math.SQRT2:1;x=n.x;y=n.y}"
          "console.log(JSON.stringify({c,end:p[p.length-1],blocked:G.findPath(r,1,1,0,0)}))")
    out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert out["end"] == {"x": g[0], "y": g[1]} and out["blocked"] is None
    assert out["c"] == pytest.approx(find_path(f["rows"], tuple(s), tuple(g)))
