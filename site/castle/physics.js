/* Walking rules for the 3D castle (no DOM, no three.js). Shared by castle.js; tests run it in node.
   Layout comes from layout.json. A move is allowed when the target is inside a zone of the player's level
   (or on the stairs, or through the open gate), outside every wall box, and no more than STEP above or below. */
(function (root) {
  'use strict';
  const R = 0.35, STEP = 0.8;

  const inBox = (b, x, z, pad) => x > b.x0 - pad && x < b.x1 + pad && z > b.z0 - pad && z < b.z1 + pad;

  function make(L) {
    const st = L.stairs, up = L.levels.upper;
    const onStairs = (x, z) => x >= st.x0 && x <= st.x1 && z >= st.z0 && z <= st.z1;
    const inGate = (x, z) => x > L.gate.x0 + R && x < L.gate.x1 - R && z >= L.gate.z0 - 0.6 && z <= L.gate.z1 + 0.6;

    /* floor height under (x, z) for a walker on `level` */
    function floorY(x, z, level) {
      if (onStairs(x, z)) {
        const n = st.steps, t = Math.min(1, Math.max(0, (st.z1 - z) / (st.z1 - st.z0)));
        return Math.min(n, Math.floor(t * n + 0.5)) * (up / n);  // the steps are real steps, half-rounded
      }
      return level === 'upper' ? up : 0;
    }

    function walkable(x, z, level, gateOpen) {
      if (!onStairs(x, z)) {
        const zoneOk = L.zones.some((q) => q.level === level && x > q.x0 + R && x < q.x1 - R && z > q.z0 + R && z < q.z1 - R);
        if (!zoneOk && !(level === 'ground' && gateOpen && inGate(x, z))) return false;
      }
      for (const w of L.walls) {
        if (w.level !== 'both' && w.level !== level && !onStairs(x, z)) continue;
        if (inBox(w, x, z, R)) return false;
      }
      if (!gateOpen && inBox(L.gate, x, z, R)) return false;
      return true;
    }

    /* Try to move from p by (dx, dz). Slides along walls. Returns the new {x, z, y, level}. */
    function move(p, dx, dz, gateOpen) {
      let { x, z, level } = p;
      const y0 = floorY(x, z, level);
      const tryTo = (nx, nz) => {
        if (!walkable(nx, nz, level, gateOpen) && !(onStairs(nx, nz) && walkable(nx, nz, 'upper', gateOpen))) return false;
        return Math.abs(floorY(nx, nz, level) - y0) <= STEP;
      };
      if (tryTo(x + dx, z + dz)) { x += dx; z += dz; }
      else if (tryTo(x + dx, z)) x += dx;
      else if (tryTo(x, z + dz)) z += dz;
      if (onStairs(x, z)) level = floorY(x, z, level) > up / 2 ? 'upper' : 'ground';
      return { x, z, level, y: floorY(x, z, level) };
    }

    function zoneName(x, z, level) {
      if (onStairs(x, z)) return 'The grand staircase';
      const q = L.zones.find((q) => q.level === level && x >= q.x0 && x <= q.x1 && z >= q.z0 && z <= q.z1);
      return q ? q.name : (z > -1.5 ? 'The gate' : 'The Great Hall');
    }

    return { floorY, walkable, move, onStairs, zoneName, R, STEP };
  }

  const api = { make };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.CastlePhysics = api;
})(typeof window !== 'undefined' ? window : globalThis);
