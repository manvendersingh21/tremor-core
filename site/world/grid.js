/* Pure tile-grid helpers (no DOM): solidity and A* pathfinding. Also loads in node for tests. */
(function (root) {
  'use strict';
  // '#' wall, 't' torch wall, 'w' window wall, 'b' bookshelf, 'f' furniture, '~' fountain, 'c' candle stand, 'D' door, ' ' void
  const SOLID = new Set(['#', 't', 'w', 'b', 'f', '~', 'c', 'D', ' ']);

  function tileAt(rows, x, y) {
    if (y < 0 || y >= rows.length || x < 0 || x >= rows[y].length) return ' ';
    return rows[y][x];
  }
  const solid = (rows, x, y) => SOLID.has(tileAt(rows, x, y));

  /* A* on the tile grid, 8 neighbours, no corner cutting. Returns [{x,y}...] from start (excluded) to goal, or null. */
  function findPath(rows, sx, sy, gx, gy, opts) {
    const allow = (opts && opts.allow) || null; // tiles that count as walkable even if solid, e.g. the goal door
    const ok = (x, y) => !solid(rows, x, y) || (allow && allow(x, y));
    if (!ok(gx, gy) || (sx === gx && sy === gy)) return sx === gx && sy === gy ? [] : null;
    const W = rows[0].length, key = (x, y) => y * W + x;
    const g = new Map([[key(sx, sy), 0]]), from = new Map(), open = [[sx, sy, 0]], done = new Set();
    const h = (x, y) => { const dx = Math.abs(x - gx), dy = Math.abs(y - gy); return dx + dy + (Math.SQRT2 - 2) * Math.min(dx, dy); };
    while (open.length) {
      let bi = 0;
      for (let i = 1; i < open.length; i++) if (open[i][2] < open[bi][2]) bi = i;
      const [x, y] = open.splice(bi, 1)[0];
      const k = key(x, y);
      if (done.has(k)) continue;
      done.add(k);
      if (x === gx && y === gy) {
        const out = [];
        for (let c = k; c !== key(sx, sy); c = from.get(c)) out.push({ x: c % W, y: (c / W) | 0 });
        return out.reverse();
      }
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        if (!dx && !dy) continue;
        const nx = x + dx, ny = y + dy;
        if (!ok(nx, ny)) continue;
        if (dx && dy && (solid(rows, x + dx, y) || solid(rows, x, y + dy))) continue;
        const ng = g.get(k) + (dx && dy ? Math.SQRT2 : 1), nk = key(nx, ny);
        if (ng < (g.has(nk) ? g.get(nk) : Infinity)) { g.set(nk, ng); from.set(nk, k); open.push([nx, ny, ng + h(nx, ny)]); }
      }
    }
    return null;
  }

  const api = { SOLID, tileAt, solid, findPath };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.CastleGrid = api;
})(typeof window !== 'undefined' ? window : globalThis);
