/* The castle in real 3D (three.js r170, vendored). walk.js drives it; this file only builds and draws the world.
   You are the camera on one rail: the road outside the iron gates -> the gates -> the lantern drive -> the great door
   -> the Great Hall. Every object is built here from primitives, lit like the paintings, and textured with the
   painted art in site/art/ (Seedream on GMI, prompts by MiniMax-M3; site/art/README.md):
     sky        art/pano-night.webp, a 2:1 painted panorama, wrapped all the way round (you can look anywhere)
     stone      art/tex-wall-out.webp (outside), art/tex-stone.webp (hall), art/tex-vault.webp, art/tex-floor.webp
     the road   art/tex-path.webp
     doors      game/layers/door-leaf-l/r.webp (cut from art/great-door.webp), glass art/glass-rose|lancet.webp
     the Count  game/layers/count-full.webp, a cut-out standing on the ground with a shadow and fog at his feet
   Gates and doors are real hinged objects: closed at the start, they swing open when you reach them and close
   again when you press E behind you. All candle flames, lantern glows, fireflies and dust are one shader each
   (a few draw calls). Never paused. Coordinates: metres, -z is forward (towards the castle), y is up. */
import * as THREE from '../vendor/three.module.min.js';

const V = (x, y, z) => new THREE.Vector3(x, y, z);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const rnd = (() => { let s = 11; return () => ((s = (s * 16807) % 2147483647) / 2147483647); })();

/* ---------- the plan (the minimap draws the same numbers) ---------- */
export const PLAN = {
  start: 10, gateZ: 0, gateHalf: 2.2, doorZ: -28, doorHalf: 2.6, hallZ0: -30, hallZ1: -76, hallHalf: 9, end: -70,
  fenceHalf: 46, facadeHalf: 15,
};
/* The hall's doors, in the order the tour and the map use. side: -1 left wall, 1 right wall, 0 the far wall. */
export const SLOTS = [
  { room: 'observatory', side: -1, z: -37 },
  { room: 'crypt', side: -1, z: -43 },
  { room: 'ladder', side: -1, z: -49 },
  { room: 'familiar', side: -1, z: -55 },
  { room: 'workshop', side: -1, z: -61 },
  { room: 'tower', side: 0, z: -75.7 },
  { room: 'gpus', side: 1, z: -61 },
  { room: 'guild', side: 1, z: -55 },
  { room: 'gate', side: 1, z: -49 },
  { room: 'ledger', side: 1, z: -43 },
];
/* The rail: walking seconds -> z. 1.45 s to the gates, 1.8 s more to the great door, inside the hall by 3.6 s.
   Shift doubles the pace. Past 3.6 s you walk on down the hall at 6 m/s. */
const KNOTS = [[0, PLAN.start], [1.45, 0.4], [3.25, -27.4], [3.6, -31.5], [3.6 + 38.5 / 6, PLAN.end]];
export const S_HALL = 3.6, S_END = KNOTS[KNOTS.length - 1][0];
const TANG = KNOTS.map((k, i) => {                    // monotone cubic (Fritsch-Carlson): smooth speed, never backwards
  const d = (a, b) => (KNOTS[b][1] - KNOTS[a][1]) / (KNOTS[b][0] - KNOTS[a][0]);
  if (i === 0) return d(0, 1); if (i === KNOTS.length - 1) return d(i - 1, i);
  const a = d(i - 1, i), b = d(i, i + 1); return a * b <= 0 ? 0 : 2 / (1 / a + 1 / b);
});
export function railZ(s) {
  s = clamp(s, 0, S_END);
  let i = 0; while (i < KNOTS.length - 2 && s > KNOTS[i + 1][0]) i++;
  const [s0, z0] = KNOTS[i], [s1, z1] = KNOTS[i + 1], h = s1 - s0, t = (s - s0) / h, t2 = t * t, t3 = t2 * t;
  return (2 * t3 - 3 * t2 + 1) * z0 + (t3 - 2 * t2 + t) * h * TANG[i] + (-2 * t3 + 3 * t2) * z1 + (t3 - t2) * h * TANG[i + 1];
}
export function railS(z) {                            // inverse, by bisection (railZ falls as s grows)
  let a = 0, b = S_END; for (let k = 0; k < 40; k++) { const m = (a + b) / 2; if (railZ(m) > z) a = m; else b = m; } return (a + b) / 2;
}

/* ---------- geometry helpers ---------- */
function place(g, x, y, z, rx = 0, ry = 0, rz = 0, sx = 1, sy = 1, sz = 1) {
  g.applyMatrix4(new THREE.Matrix4().compose(V(x, y, z), new THREE.Quaternion().setFromEuler(new THREE.Euler(rx, ry, rz)), V(sx, sy, sz)));
  return g;
}
function merge(list) {                                // one draw call per material: positions, normals, uvs, uv1
  const parts = list.map((g) => (g.index ? g.toNonIndexed() : g));
  const n = parts.reduce((a, g) => a + g.attributes.position.count, 0), out = new THREE.BufferGeometry();
  for (const [name, size] of [['position', 3], ['normal', 3], ['uv', 2], ['uv1', 2]]) {
    if (name === 'uv1' && !parts.some((g) => g.attributes.uv1)) continue;
    const arr = new Float32Array(n * size); let o = 0;
    for (const g of parts) { const a = g.attributes[name] || (name === 'uv1' ? g.attributes.uv : null), c = g.attributes.position.count; if (a) arr.set(a.array.subarray(0, c * size), o); o += c * size; }
    out.setAttribute(name, new THREE.BufferAttribute(arr, size));
  }
  return out;
}
function uvScale(g, su, sv, name = 'uv') {            // texture tiles keep their size on any surface
  const src = g.attributes.uv, a = new Float32Array(src.array.length);
  for (let i = 0; i < src.count; i++) { a[i * 2] = src.array[i * 2] * su; a[i * 2 + 1] = src.array[i * 2 + 1] * sv; }
  g.setAttribute(name, new THREE.BufferAttribute(a, 2)); return g;
}
function box(w, h, d, tile = 4) {                     // a box whose stone tiles are `tile` metres everywhere
  const g = new THREE.BoxGeometry(w, h, d), uv = g.attributes.uv;
  const faces = [[d, h], [d, h], [w, d], [w, d], [w, h], [w, h]];
  for (let f = 0; f < 6; f++) for (let k = 0; k < 4; k++) { const i = f * 4 + k; uv.setXY(i, uv.getX(i) * faces[f][0] / tile, uv.getY(i) * faces[f][1] / tile); }
  return g;
}
function canvasTex(w, h, draw, srgb = true) {
  const c = document.createElement('canvas'); c.width = w; c.height = h; draw(c.getContext('2d'), w, h);
  const t = new THREE.CanvasTexture(c); if (srgb) t.colorSpace = THREE.SRGBColorSpace; t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 4; return t;
}
function radial(stops, size = 128) {
  return canvasTex(size, size, (x, w) => { const r = x.createRadialGradient(w / 2, w / 2, 0, w / 2, w / 2, w / 2); stops.forEach(([o, c]) => r.addColorStop(o, c)); x.fillStyle = r; x.fillRect(0, 0, w, w); });
}
/* A pointed (gothic) arch outline, springing at y0 with half-width r, as points from left foot to right foot. */
function archPts(r, y0, n = 18) {                    // the apex is 1.5 r above y0
  const c = r * 0.62, R = r + c, aEnd = Math.acos(-c / R), left = [];   // each arc is centred inside the opposite jamb
  for (let i = 0; i <= n; i++) { const a = Math.PI - (Math.PI - aEnd) * i / n; left.push(V(c + R * Math.cos(a), y0 + R * Math.sin(a), 0)); }
  return [V(-r, 0, 0), ...left, ...left.slice(0, -1).reverse().map((p) => V(-p.x, p.y, 0)), V(r, 0, 0)];
}

/* ---------- the shader for every flame, glow, firefly and mote (one draw call each) ---------- */
function points(list, map, opts = {}) {
  const n = list.length, pos = new Float32Array(n * 3), sz = new Float32Array(n), ph = new Float32Array(n), col = new Float32Array(n * 3);
  list.forEach((p, i) => { pos.set([p[0], p[1], p[2]], i * 3); sz[i] = p[3]; ph[i] = rnd() * 50; const c = new THREE.Color(p[4] || opts.color || 0xffffff); col.set([c.r, c.g, c.b], i * 3); });
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3)); g.setAttribute('sz', new THREE.BufferAttribute(sz, 1));
  g.setAttribute('ph', new THREE.BufferAttribute(ph, 1)); g.setAttribute('col', new THREE.BufferAttribute(col, 3));
  const m = new THREE.ShaderMaterial({
    uniforms: { map: { value: map }, t: { value: 0 }, px: { value: 600 }, flick: { value: opts.flicker ?? 1 }, drift: { value: opts.drift ?? 0 }, fade: { value: opts.fade ?? 0.012 }, gain: { value: opts.gain ?? 1 } },
    vertexShader: `attribute float sz; attribute float ph; attribute vec3 col; uniform float t, px, flick, drift, fade; varying float a; varying vec3 c;
      void main() { vec3 p = position + drift * vec3(sin(t * .31 + ph) * 1.6, sin(t * .53 + ph * 1.3) * .7, cos(t * .27 + ph) * 1.6);
        vec4 mv = modelViewMatrix * vec4(p, 1.); float f = mix(1., .78 + .16 * sin(t * 13. + ph) + .1 * sin(t * 29. + ph * 1.7), flick);
        if (drift > 0.) f *= .25 + .75 * max(0., sin(t * 1.7 + ph * 2.));
        a = f * exp(-(-mv.z) * fade); c = col; gl_PointSize = min(380., sz * f * px / max(.1, -mv.z)); gl_Position = projectionMatrix * mv; }`,
    fragmentShader: `uniform sampler2D map; uniform float gain; varying float a; varying vec3 c; void main() { vec4 s = texture2D(map, gl_PointCoord); gl_FragColor = vec4(s.rgb * c * a * gain, s.a * a); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const o = new THREE.Points(g, m); o.frustumCulled = false; return o;
}

export function create(canvas, opts = {}) {
  const site = opts.site || '', phone = !!opts.phone, small = phone ? '-1024' : '';
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: !phone, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, phone ? 1.6 : 1.5));
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.25;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(phone ? 72 : 64, 1, 0.08, 900);
  camera.rotation.order = 'YXZ';
  const FOG_OUT = new THREE.Color(0x2f2445), FOG_IN = new THREE.Color(0x1a0f1c);
  scene.fog = new THREE.FogExp2(FOG_OUT, 0.012);
  const loader = new THREE.TextureLoader();
  const T = (f, rep, srgb = true) => { const t = loader.load(site + f); if (srgb) t.colorSpace = THREE.SRGBColorSpace; t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 8; if (rep) t.repeat.set(rep[0], rep[1]); return t; };
  const tex = {
    wall: T('art/tex-wall-out.webp'), stone: T('art/tex-stone.webp'), vault: T('art/tex-vault.webp'), floor: T('art/tex-floor.webp'),
    path: T('art/tex-path.webp', [1, 7]), rose: T('art/glass-rose.webp'), lancet: T('art/glass-lancet.webp'), banner: T('art/banner.webp'),
    leafL: T('game/layers/door-leaf-l.webp'), leafR: T('game/layers/door-leaf-r.webp'), count: T('game/layers/count-full.webp'),
  };
  [tex.leafL, tex.leafR, tex.count, tex.rose, tex.lancet, tex.banner].forEach((t) => { t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping; });
  const flameTex = radial([[0, 'rgba(255,248,220,1)'], [0.18, 'rgba(255,214,140,.95)'], [0.45, 'rgba(255,150,60,.35)'], [1, 'rgba(255,110,30,0)']]);
  const glowTex = radial([[0, 'rgba(255,220,160,.9)'], [0.35, 'rgba(255,170,90,.32)'], [1, 'rgba(255,120,40,0)']]);
  const moteTex = radial([[0, 'rgba(255,255,255,1)'], [0.4, 'rgba(255,255,255,.35)'], [1, 'rgba(255,255,255,0)']], 32);
  const shadowTex = radial([[0, 'rgba(0,0,0,.75)'], [0.6, 'rgba(0,0,0,.35)'], [1, 'rgba(0,0,0,0)']], 64);
  const hazeTex = radial([[0, 'rgba(205,180,235,.30)'], [1, 'rgba(205,180,235,0)']], 128);
  /* lit windows for every tower: arched panes, most lit warm, some dark (the emissive map) */
  const winTex = canvasTex(512, 512, (x, w) => {
    x.fillStyle = '#000'; x.fillRect(0, 0, w, w);
    for (let j = 0; j < 4; j++) for (let i = 0; i < 4; i++) {
      if (rnd() < 0.3) continue;
      const cx = i * 128 + 64 + (j % 2 ? 22 : -22), cy = j * 128 + 74, ww = 22, hh = 52, on = 0.55 + rnd() * 0.45;
      const g = x.createLinearGradient(0, cy - hh / 2, 0, cy + hh / 2); g.addColorStop(0, `rgba(255,190,100,${on})`); g.addColorStop(1, `rgba(255,120,40,${on})`);
      x.fillStyle = g; x.beginPath(); x.moveTo(cx - ww / 2, cy + hh / 2); x.lineTo(cx - ww / 2, cy - hh / 4); x.quadraticCurveTo(cx - ww / 2, cy - hh / 2, cx, cy - hh / 2 - 6);
      x.quadraticCurveTo(cx + ww / 2, cy - hh / 2, cx + ww / 2, cy - hh / 4); x.lineTo(cx + ww / 2, cy + hh / 2); x.fill();
      x.fillStyle = 'rgba(0,0,0,.6)'; x.fillRect(cx - 1, cy - hh / 2, 2, hh); x.fillRect(cx - ww / 2, cy, ww, 2);
    }
  });
  const grassTex = canvasTex(256, 256, (x, w) => {
    x.fillStyle = '#2a2232'; x.fillRect(0, 0, w, w);
    for (let i = 0; i < 2600; i++) { const v = 20 + rnd() * 40 | 0; x.fillStyle = `rgba(${v + 14},${v + 8},${v + 30},${0.35 + rnd() * 0.4})`; x.fillRect(rnd() * w, rnd() * w, 1 + rnd() * 3, 1 + rnd() * 5); }
  });
  grassTex.repeat.set(80, 80);
  const carpetTex = canvasTex(256, 512, (x, w, h) => {
    const g = x.createLinearGradient(0, 0, w, 0); g.addColorStop(0, '#4a0918'); g.addColorStop(0.5, '#7d1027'); g.addColorStop(1, '#4a0918');
    x.fillStyle = g; x.fillRect(0, 0, w, h);
    x.fillStyle = '#c8962e'; x.fillRect(14, 0, 9, h); x.fillRect(w - 23, 0, 9, h); x.fillRect(30, 0, 3, h); x.fillRect(w - 33, 0, 3, h);
    x.strokeStyle = '#d9a640'; x.lineWidth = 4; x.beginPath(); x.ellipse(w / 2, h / 2, 46, 70, 0, 0, 7); x.stroke();
    x.beginPath(); x.moveTo(w / 2, h / 2 - 96); x.lineTo(w / 2 + 30, h / 2); x.lineTo(w / 2, h / 2 + 96); x.lineTo(w / 2 - 30, h / 2); x.closePath(); x.stroke();
    x.fillStyle = '#d9a640'; for (const y of [40, h - 40]) { x.beginPath(); x.moveTo(w / 2, y - 14); x.lineTo(w / 2 + 12, y); x.lineTo(w / 2, y + 14); x.lineTo(w / 2 - 12, y); x.fill(); }
  });

  /* ---------- materials ---------- */
  const mat = {
    iron: new THREE.MeshStandardMaterial({ color: 0x1a1420, roughness: 0.42, metalness: 0.85, side: THREE.DoubleSide }),
    gold: new THREE.MeshStandardMaterial({ color: 0xd9a640, roughness: 0.28, metalness: 1, emissive: 0x5a3a08, emissiveIntensity: 0.8 }),
    rim: new THREE.MeshStandardMaterial({ color: 0xe9b45a, roughness: 0.3, metalness: 1, emissive: 0xc8862a, emissiveIntensity: 0.75 }),
    wall: new THREE.MeshLambertMaterial({ map: tex.wall, color: 0x9a8aa8 }),
    tower: new THREE.MeshLambertMaterial({ map: tex.wall, color: 0x8f7fa0, emissiveMap: winTex, emissive: 0xffa050, emissiveIntensity: 1.5 }),
    roof: new THREE.MeshLambertMaterial({ color: 0x2a2440, emissive: 0x0c0814 }),
    ground: new THREE.MeshLambertMaterial({ map: grassTex, color: 0x9a8aa8 }),
    path: new THREE.MeshStandardMaterial({ map: tex.path, color: 0xa898b8, roughness: 0.62, metalness: 0.1 }),
    pine: new THREE.MeshLambertMaterial({ color: 0x1a1426, emissive: 0x05030a }),
    hallWall: new THREE.MeshStandardMaterial({ map: tex.stone, color: 0x9d8db0, roughness: 0.8 }),
    vault: new THREE.MeshStandardMaterial({ map: tex.vault, color: 0x8a7a9e, roughness: 0.85, side: THREE.BackSide }),
    floor: new THREE.MeshStandardMaterial({ map: tex.floor, color: 0xa898b8, roughness: 0.22, metalness: 0.25 }),
    carpet: new THREE.MeshStandardMaterial({ map: carpetTex, roughness: 0.95, color: 0xb8a0a8 }),
    column: new THREE.MeshStandardMaterial({ map: tex.stone, color: 0xb0a0c0, roughness: 0.6 }),
    leafL: new THREE.MeshStandardMaterial({ map: tex.leafL, alphaTest: 0.5, side: THREE.DoubleSide, roughness: 0.55, emissive: 0x2a1006, emissiveMap: tex.leafL, emissiveIntensity: 0.6 }),
    leafR: new THREE.MeshStandardMaterial({ map: tex.leafR, alphaTest: 0.5, side: THREE.DoubleSide, roughness: 0.55, emissive: 0x2a1006, emissiveMap: tex.leafR, emissiveIntensity: 0.6 }),
    rose: new THREE.MeshBasicMaterial({ map: tex.rose, color: 0xffffff }),
    lancet: new THREE.MeshBasicMaterial({ map: tex.lancet, color: 0xd8c8f0 }),
    banner: new THREE.MeshStandardMaterial({ map: tex.banner, roughness: 0.9, side: THREE.DoubleSide }),
    lantern: new THREE.MeshBasicMaterial({ color: 0xd86a1e }),
  };
  winTex.repeat.set(1, 1); tex.wall.repeat.set(1, 1);
  tex.banner.repeat.set(0.46, 0.86); tex.banner.offset.set(0.27, 0.06);

  /* ---------- light: moonlight from behind the castle, a violet fill, warm lanterns and candles ---------- */
  scene.add(new THREE.HemisphereLight(0x9484c8, 0x22142e, 1.25));
  const moonDir = V(0.22, 0.42, -1).normalize();
  const moon = new THREE.DirectionalLight(0xffb880, 1.3); moon.position.copy(moonDir.clone().multiplyScalar(100)); scene.add(moon);
  const fill = new THREE.DirectionalLight(0xa898e0, 1.5); fill.position.set(-30, 25, 60); scene.add(fill);
  const lamp = (x, y, z, c, i, d) => { const l = new THREE.PointLight(c, i, d, 1.6); l.position.set(x, y, z); scene.add(l); return l; };
  const gateLamps = [lamp(-3.3, 3.4, 0.9, 0xffa050, 9, 12), lamp(3.3, 3.4, 0.9, 0xffa050, 9, 12)];
  const doorLamps = [lamp(-4.2, 4.6, PLAN.doorZ + 1.4, 0xffa050, 16, 16), lamp(4.2, 4.6, PLAN.doorZ + 1.4, 0xffa050, 16, 16)];
  const driveLamp = lamp(0, 3, -13, 0xff9a50, 5, 14);
  const CHAND = [-37, -50, -63], hallLamps = CHAND.map((z) => lamp(0, 8.2, z, 0xffb060, 60, 30));
  const doorGlow = lamp(0, 3, PLAN.hallZ0 - 1.5, 0xffc070, 0, 14);   // the hall's light spills out when the great door opens
  const flames = [], glows = [];

  /* ---------- sky: the painted panorama all around you ---------- */
  const skyTex = loader.load(site + `art/pano-night${small}.webp`); skyTex.colorSpace = THREE.NoColorSpace; skyTex.wrapS = THREE.RepeatWrapping;
  const sky = new THREE.Mesh(new THREE.SphereGeometry(600, 48, 24), new THREE.ShaderMaterial({
    uniforms: { map: { value: skyTex }, top: { value: new THREE.Color(0x1b1030) } }, depthWrite: false, side: THREE.BackSide, fog: false,
    vertexShader: 'varying vec3 d; void main() { d = position; vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.); gl_Position = p.xyww; }',
    fragmentShader: `uniform sampler2D map; uniform vec3 top; varying vec3 d;
      void main() { vec3 n = normalize(d); float phi = atan(n.x, -n.z), th = asin(clamp(n.y, -1., 1.));
        float u = fract(.5 + phi / 6.2831853 - .09), v = .62 - th / radians(74.);
        vec3 c = texture2D(map, vec2(u, 1. - clamp(v, .002, .998))).rgb;
        c = mix(c, top, smoothstep(.03, -.25, v)); gl_FragColor = vec4(c * 1.05, 1.); }`,
  }));
  sky.renderOrder = -1; scene.add(sky);
  const moonAt = (() => { const phi = 0.09 * 2 * Math.PI, th = (0.62 - 0.31) * (74 * Math.PI / 180); return V(Math.sin(phi) * Math.cos(th), Math.sin(th), -Math.cos(phi) * Math.cos(th)); })();
  const moonGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color: 0xffa860, blending: THREE.AdditiveBlending, depthWrite: false, fog: false, opacity: 0.55 }));
  moonGlow.scale.set(260, 260, 1); scene.add(moonGlow);

  /* ---------- the ground, the road, the forecourt ---------- */
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(700, 700), mat.ground); ground.rotation.x = -Math.PI / 2; scene.add(ground);
  const road = new THREE.Mesh(uvScale(new THREE.PlaneGeometry(4.6, 14 - PLAN.doorZ), 1, (14 - PLAN.doorZ) / 34), mat.path); road.rotation.x = -Math.PI / 2; road.position.set(0, 0.012, (14 + PLAN.doorZ) / 2); scene.add(road);
  const court = new THREE.Mesh(uvScale(new THREE.PlaneGeometry(16, 7), 3.4, 1), mat.path); court.rotation.x = -Math.PI / 2; court.position.set(0, 0.014, PLAN.doorZ + 3.4); scene.add(court);
  const outer = new THREE.Mesh(uvScale(new THREE.PlaneGeometry(6, 90), 1.3, 19), mat.path); outer.rotation.x = -Math.PI / 2; outer.position.set(0, 0.01, 57);   // the road you came on runs on into the fog scene.add(outer);

  /* ---------- the iron gates: stone posts, lanterns, two hinged leaves with gold scrollwork ---------- */
  const GW = PLAN.gateHalf;
  function leafGeom() {                                // a leaf from its hinge (x = 0) to the middle (x = GW)
    const iron = [], gold = [], top = (x) => 3.25 + 0.55 * Math.pow(x / GW, 1.6);
    iron.push(place(new THREE.BoxGeometry(0.09, 3.4, 0.09), 0.045, 1.7 + 0.05, 0), place(new THREE.BoxGeometry(0.08, top(GW) + 0.1, 0.08), GW - 0.04, (top(GW) + 0.1) / 2, 0));
    for (const y of [0.22, 1.05, 2.15]) iron.push(place(new THREE.BoxGeometry(GW, 0.07, 0.07), GW / 2, y, 0));
    for (let x = 0.2; x < GW - 0.05; x += 0.17) {
      const h = top(x); iron.push(place(new THREE.CylinderGeometry(0.017, 0.017, h - 0.1, 6), x, 0.1 + (h - 0.1) / 2, 0));
      gold.push(place(new THREE.ConeGeometry(0.04, 0.2, 6), x, h + 0.08, 0));
    }
    const crv = new THREE.CatmullRomCurve3([0, 0.25, 0.5, 0.75, 1].map((t) => V(t * GW, top(t * GW) - 0.06, 0)));
    gold.push(new THREE.TubeGeometry(crv, 24, 0.04, 6, false));
    for (let x = 0.24; x < GW - 0.2; x += 0.36) {        // a band of C-scrolls between the low rails
      iron.push(place(new THREE.TorusGeometry(0.15, 0.014, 5, 16, Math.PI * 1.5), x + 0.06, 0.62, 0, 0, 0, Math.PI * 0.75));
      iron.push(place(new THREE.TorusGeometry(0.1, 0.012, 5, 14, Math.PI * 1.5), x + 0.12, 1.68, 0, 0, 0, -Math.PI * 0.25));
    }
    gold.push(place(new THREE.TorusGeometry(0.3, 0.026, 6, 32), GW * 0.58, 2.72, 0), place(new THREE.TorusGeometry(0.13, 0.02, 6, 20), GW * 0.58, 2.72, 0));
    for (let a = 0; a < 4; a++) iron.push(place(new THREE.BoxGeometry(0.6, 0.02, 0.02), GW * 0.58, 2.72, 0, 0, 0, a * Math.PI / 4));
    gold.push(place(new THREE.TorusGeometry(0.3, 0.022, 6, 20, Math.PI), GW * 0.58, 3.1, 0));
    return { iron: merge(iron), gold: merge(gold) };
  }
  const LG = leafGeom();
  const gates = [-1, 1].map((side) => {
    const hinge = new THREE.Group(); hinge.position.set(side * GW, 0, PLAN.gateZ);
    const inner = new THREE.Group(); inner.scale.x = -side;   // the left leaf runs +x from its hinge, the right one -x
    inner.add(new THREE.Mesh(LG.iron, mat.iron), new THREE.Mesh(LG.gold, mat.rim));
    hinge.add(inner); scene.add(hinge); return hinge;
  });
  const stoneParts = [], goldParts = [];
  for (const side of [-1, 1]) {
    const x = side * (GW + 0.5);
    stoneParts.push(place(box(0.95, 5.0, 0.95, 1.6), x, 2.5, 0), place(box(1.25, 0.3, 1.25, 1.6), x, 5.15, 0), place(box(1.05, 0.5, 1.05, 1.6), x, 0.25, 0));
    goldParts.push(place(new THREE.ConeGeometry(0.42, 1.1, 4), x, 5.85, 0, 0, Math.PI / 4), place(new THREE.SphereGeometry(0.16, 12, 8), x, 6.5, 0));
    goldParts.push(place(new THREE.BoxGeometry(0.06, 0.6, 0.06), x - side * 0.62 * 0, 3.05, 0.62));
    glows.push([x, 3.35, 0.78, 2.6], [x, 3.35, 0.78, 6]); flames.push([x, 3.35, 0.78, 0.4]);
    for (let k = 0; k < 3; k++) flames.push([x + (k - 1) * 0.22, 5.42 + (k === 1 ? 0.08 : 0), 0.3, 0.22]);
  }
  /* the fence: a stone plinth and iron bars out to both sides, so the castle grounds have an edge all round */
  const FX0 = GW + 1.0, FX1 = PLAN.fenceHalf;
  for (const side of [-1, 1]) {
    stoneParts.push(place(box(FX1 - FX0, 0.7, 0.6, 2), side * (FX0 + FX1) / 2, 0.35, 0));
    for (let x = FX0 + 4; x < FX1; x += 6) stoneParts.push(place(box(0.7, 2.9, 0.7, 1.6), side * x, 1.45, 0), place(box(0.85, 0.22, 0.85, 1.6), side * x, 2.95, 0));
  }
  const nBars = Math.floor((FX1 - FX0) / 0.16) * 2, bars = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.016, 0.016, 2.2, 5), mat.iron, nBars),
    tips = new THREE.InstancedMesh(new THREE.ConeGeometry(0.035, 0.16, 5), mat.gold, nBars);
  { const m = new THREE.Matrix4(); let k = 0; for (const side of [-1, 1]) for (let x = FX0; x < FX1 - 0.08 && k < nBars; x += 0.16, k++) { m.makeTranslation(side * x, 1.8, 0); bars.setMatrixAt(k, m); m.makeTranslation(side * x, 2.97, 0); tips.setMatrixAt(k, m); } bars.count = tips.count = k; }
  scene.add(bars, tips);
  for (const side of [-1, 1]) [0.5, 2.1].forEach((y) => goldParts.push(place(new THREE.BoxGeometry(FX1 - FX0, 0.05, 0.05), side * (FX0 + FX1) / 2, y + 0.6, 0)));

  /* ---------- the lantern drive ---------- */
  const posts = [];
  for (const z of [-3, -8, -13, -18, -23]) for (const side of [-1, 1]) {
    posts.push(place(new THREE.CylinderGeometry(0.06, 0.09, 2.7, 8), side * 2.9, 1.35, z), place(new THREE.BoxGeometry(0.34, 0.08, 0.34), side * 2.9, 2.74, z), place(new THREE.ConeGeometry(0.26, 0.3, 4), side * 2.9, 3.18, z, 0, Math.PI / 4));
    glows.push([side * 2.9, 2.93, z, 3.4]); flames.push([side * 2.9, 2.93, z, 0.5]);
  }
  for (const z of [5.5, 14, 22]) for (const side of [-1, 1]) {            // and two lanterns on the road outside
    posts.push(place(new THREE.CylinderGeometry(0.06, 0.09, 2.7, 8), side * 3.3, 1.35, z), place(new THREE.BoxGeometry(0.34, 0.08, 0.34), side * 3.3, 2.74, z), place(new THREE.ConeGeometry(0.26, 0.3, 4), side * 3.3, 3.18, z, 0, Math.PI / 4));
    glows.push([side * 3.3, 2.93, z, 3.4]); flames.push([side * 3.3, 2.93, z, 0.5]);
  }
  scene.add(new THREE.Mesh(merge(posts), mat.iron));
  const lanternGlass = [];
  for (const g of glows.slice()) if (g[3] === 3.4) lanternGlass.push(place(new THREE.BoxGeometry(0.16, 0.24, 0.16), g[0], g[1], g[2]));
  scene.add(new THREE.Mesh(merge(lanternGlass), mat.lantern));

  /* ---------- the forest: dark pines all round, thick enough to read as a silhouette in the fog ---------- */
  const pineG = merge([place(new THREE.ConeGeometry(1.0, 2.2, 7), 0, 1.9, 0), place(new THREE.ConeGeometry(0.8, 1.9, 7), 0, 3.0, 0), place(new THREE.ConeGeometry(0.55, 1.6, 7), 0, 4.0, 0), place(new THREE.CylinderGeometry(0.1, 0.14, 1.2, 5), 0, 0.6, 0)]);
  const spots = [];
  for (let i = 0; i < 2600 && spots.length < (phone ? 260 : 420); i++) {
    const x = (rnd() - 0.5) * 220, z = 60 - rnd() * 170;
    if (Math.abs(x) < 6.5 && z > PLAN.doorZ + 2) continue;                      // the road and the drive stay clear
    if (Math.abs(z) < 2.2) continue;                                  // and the fence line
    if (Math.abs(x) < 26 && z < PLAN.doorZ + 6 && z > -94) continue;             // the castle
    if (Math.hypot(x, z) < 9) continue;
    spots.push([x, z, 1.6 + rnd() * 2.8]);
  }
  const pines = new THREE.InstancedMesh(pineG, mat.pine, spots.length);
  { const m = new THREE.Matrix4(); spots.forEach(([x, z, s], k) => { m.compose(V(x, 0, z), new THREE.Quaternion().setFromEuler(new THREE.Euler(0, rnd() * 6, 0)), V(s, s * (0.9 + rnd() * 0.5), s)); pines.setMatrixAt(k, m); }); }
  scene.add(pines);

  /* ---------- the castle: a gothic front with the great door, towers with lit windows, spires behind ---------- */
  const DZ = PLAN.doorZ, DW = PLAN.doorHalf, LEAF_H = DW * 914 / 386;   // the leaf paintings set the door's height
  const arch = archPts(DW, LEAF_H - 1.5 * DW);
  const frameShape = new THREE.Shape(); frameShape.moveTo(-DW - 1.6, -0.05); frameShape.lineTo(DW + 1.6, -0.05); frameShape.lineTo(DW + 1.6, LEAF_H + 2.2); frameShape.lineTo(-DW - 1.6, LEAF_H + 2.2); frameShape.lineTo(-DW - 1.6, -0.05);
  frameShape.holes.push(new THREE.Path(arch.map((p) => new THREE.Vector2(p.x, p.y))));
  const frameG = new THREE.ExtrudeGeometry(frameShape, { depth: 2.2, bevelEnabled: false, curveSegments: 2 }); uvScale(frameG, 0.25, 0.25);
  place(frameG, 0, 0, DZ - 2.2);
  const FW = PLAN.facadeHalf, FH = 21, fT = 2.2;
  stoneParts.push(frameG,
    place(box(FW - DW - 1.6, FH, fT), -(FW + DW + 1.6) / 2, FH / 2, DZ - fT / 2), place(box(FW - DW - 1.6, FH, fT), (FW + DW + 1.6) / 2, FH / 2, DZ - fT / 2),
    place(box((DW + 1.6) * 2, FH - LEAF_H - 2.2, fT), 0, (FH + LEAF_H + 2.2) / 2, DZ - fT / 2));
  for (let x = -FW + 0.6; x <= FW - 0.5; x += 1.6) stoneParts.push(place(box(0.8, 1.1, fT + 0.3, 1.6), x, FH + 0.55, DZ - fT / 2));   // battlements
  const gable = new THREE.Shape(); gable.moveTo(-7, 0); gable.lineTo(7, 0); gable.lineTo(0, 8.5); gable.closePath();
  stoneParts.push(place(uvScale(new THREE.ExtrudeGeometry(gable, { depth: 1.6, bevelEnabled: false }), 0.25, 0.25), 0, FH, DZ - 1.9));
  // the gold rim round the door, and the rose window above it
  const rimParts = [new THREE.TubeGeometry(new THREE.CatmullRomCurve3(arch.map((p) => V(p.x * 1.05, p.y * 1.015, DZ + 0.08))), 90, 0.12, 8, false),
    new THREE.TubeGeometry(new THREE.CatmullRomCurve3(arch.map((p) => V(p.x * 1.2, p.y * 1.06, DZ + 0.08))), 90, 0.07, 6, false)];
  const roseOut = new THREE.Mesh(new THREE.CircleGeometry(2.3, 40), new THREE.MeshBasicMaterial({ map: tex.rose, color: 0xffd0a0 })); roseOut.position.set(0, FH - 4.3, DZ + 0.02); scene.add(roseOut);
  goldParts.push(place(new THREE.TorusGeometry(2.38, 0.12, 8, 48), 0, FH - 4.3, DZ + 0.05));
  for (const side of [-1, 1]) {                      // torches either side of the door
    goldParts.push(place(new THREE.CylinderGeometry(0.05, 0.1, 0.8, 8), side * (DW + 0.9), 4.3, DZ + 0.3, side * 0.3, 0, 0));
    flames.push([side * (DW + 0.9), 4.85, DZ + 0.42, 0.75]); glows.push([side * (DW + 0.9), 4.85, DZ + 0.42, 7]);
  }
  // towers: [x, z, radius, height, roof height, base y]
  const TOWERS = [[-6.4, DZ + 0.4, 2.2, 26, 9, 0], [6.4, DZ + 0.4, 2.2, 26, 9, 0], [-FW, DZ - 1, 3.1, 30, 12, 0], [FW, DZ - 1, 3.1, 30, 12, 0],
    [-12, -44, 2.6, 36, 13, 0], [12, -44, 2.6, 36, 13, 0], [-7.5, -38, 1.5, 15, 8, 20], [7.5, -38, 1.5, 15, 8, 20], [0, -50, 4, 30, 16, 20],
    [-12.5, -62, 3.2, 42, 15, 0], [12.5, -62, 3.2, 42, 15, 0], [-6, -68, 1.8, 18, 9, 20], [6, -68, 1.8, 18, 9, 20], [0, -84, 5, 46, 20, 0],
    [-19, -40, 2.4, 24, 10, 0], [19, -40, 2.4, 24, 10, 0], [-17, -70, 2.8, 32, 12, 0], [17, -70, 2.8, 32, 12, 0], [-22, -56, 2.2, 20, 9, 0], [22, -56, 2.2, 20, 9, 0]];
  const towerParts = [], roofParts = [];
  for (const [x, z, r, h, rh, y0] of TOWERS) {
    const g = new THREE.CylinderGeometry(r, r * 1.04, h, 16, 1, true); uvScale(g, Math.max(1, Math.round(2 * Math.PI * r / 14)), h / 18, 'uv1'); uvScale(g, 2 * Math.PI * r / 4, h / 4);   // windows (uv1) about 1 m wide, stone (uv) 4 m tiles
    towerParts.push(place(g, x, y0 + h / 2, z));
    stoneParts.push(place(box(r * 2.5, 0.5, r * 2.5, 1.6), x, y0 + h + 0.2, z));
    roofParts.push(place(new THREE.ConeGeometry(r * 1.22, rh, 16, 1, true), x, y0 + h + 0.45 + rh / 2, z));
    goldParts.push(place(new THREE.CylinderGeometry(0.04, 0.06, 2.2, 6), x, y0 + h + rh + 1.4, z), place(new THREE.SphereGeometry(0.16, 10, 8), x, y0 + h + rh + 0.55, z));
  }
  // the hall's roof, seen over the front, and its long walls from outside
  const roofShape = new THREE.Shape(); roofShape.moveTo(-10.4, 0); roofShape.lineTo(10.4, 0); roofShape.lineTo(0, 9.5); roofShape.closePath();
  roofParts.push(place(new THREE.ExtrudeGeometry(roofShape, { depth: 46, bevelEnabled: false }), 0, FH - 1.2, DZ - 48));
  stoneParts.push(place(box(1.6, FH, 48), -PLAN.hallHalf - 0.8, FH / 2, (PLAN.hallZ0 + PLAN.hallZ1) / 2), place(box(1.6, FH, 48), PLAN.hallHalf + 0.8, FH / 2, (PLAN.hallZ0 + PLAN.hallZ1) / 2), place(box(20, FH, 1.6), 0, FH / 2, PLAN.hallZ1 - 0.8));
  const towerMesh = new THREE.Mesh(merge(towerParts), mat.tower); towerMesh.geometry.attributes.uv1 = towerMesh.geometry.attributes.uv1 || towerMesh.geometry.attributes.uv;
  winTex.channel = 1; scene.add(towerMesh);
  scene.add(new THREE.Mesh(merge(roofParts), mat.roof));
  // the great door: two hinged leaves painted with the door art
  const leafPlane = (w, h, flip) => { const g = new THREE.PlaneGeometry(w, h); g.translate(flip ? -w / 2 : w / 2, h / 2, 0); return g; };
  const doorLeaves = [-1, 1].map((side) => {
    const hinge = new THREE.Group(); hinge.position.set(side * DW, 0, DZ - 0.25);
    const m = new THREE.Mesh(leafPlane(DW, LEAF_H, side > 0), side < 0 ? mat.leafL : mat.leafR); hinge.add(m); scene.add(hinge); return hinge;
  });
  const doorBack = new THREE.Mesh(new THREE.PlaneGeometry(DW * 2, LEAF_H), new THREE.MeshBasicMaterial({ color: 0xffc070, transparent: true, opacity: 0 }));
  doorBack.position.set(0, LEAF_H / 2, DZ - 0.6); scene.add(doorBack);

  /* ---------- the Great Hall: 46 m long, 18 m wide, a ribbed vault 18 m up, columns, ten gold doors ---------- */
  const HZ0 = PLAN.hallZ0, HZ1 = PLAN.hallZ1, HW = PLAN.hallHalf, HL = HZ0 - HZ1, HC = (HZ0 + HZ1) / 2, SPRING = 11;
  const hall = new THREE.Group(); scene.add(hall);
  const floor = new THREE.Mesh(uvScale(new THREE.PlaneGeometry(HW * 2, HL), HW * 2 / 4, HL / 4), mat.floor); floor.rotation.x = -Math.PI / 2; floor.position.set(0, 0.006, HC); hall.add(floor);
  const carpet = new THREE.Mesh(uvScale(new THREE.PlaneGeometry(3.4, HL - 1), 1, (HL - 1) / 6.8), mat.carpet); carpet.rotation.x = -Math.PI / 2; carpet.position.set(0, 0.02, HC - 0.5); hall.add(carpet);
  const hallParts = [];
  for (const side of [-1, 1]) { const g = uvScale(new THREE.PlaneGeometry(HL, SPRING), HL / 4, SPRING / 4); hallParts.push(place(g, side * (HW - 0.02), SPRING / 2, HC, 0, -side * Math.PI / 2)); }
  hallParts.push(place(uvScale(new THREE.PlaneGeometry(HW * 2, 19), HW / 2, 19 / 4), 0, 9.5, HZ1 + 0.02));
  const inner = new THREE.Shape(); inner.moveTo(-HW, -0.05); inner.lineTo(HW, -0.05); inner.lineTo(HW, 19); inner.lineTo(-HW, 19); inner.lineTo(-HW, -0.05);
  inner.holes.push(new THREE.Path(arch.map((p) => new THREE.Vector2(p.x, p.y))));
  hallParts.push(place(uvScale(new THREE.ShapeGeometry(inner), 0.25, 0.25), 0, 0, HZ0 - 0.21, 0, Math.PI, 0));
  hall.add(new THREE.Mesh(merge(hallParts), mat.hallWall));
  const vaultG = new THREE.CylinderGeometry(HW, HW, HL, 28, 1, true, -Math.PI / 2, Math.PI); uvScale(vaultG, 7, HL / 5);
  place(vaultG, 0, SPRING, HC, -Math.PI / 2, 0, 0, 1, 1, 0.75);   // the upper half, squashed to a 6.75 m rise
  hall.add(new THREE.Mesh(vaultG, mat.vault));
  // columns, their gold capitals, the vault ribs, banners
  const colParts = [], capParts = [], ribParts = [], bannerParts = [];
  for (let z = HZ0 - 4; z > HZ1 + 2; z -= 6) {
    for (const side of [-1, 1]) {
      const x = side * 6.2, c = new THREE.CylinderGeometry(0.58, 0.66, SPRING - 1, 18); uvScale(c, 1, 3);
      colParts.push(place(c, x, (SPRING - 1) / 2 + 0.5, z), place(box(1.6, 0.6, 1.6, 1.2), x, 0.3, z), place(box(1.45, 0.25, 1.45, 1.2), x, 0.72, z));
      capParts.push(place(new THREE.CylinderGeometry(0.95, 0.62, 0.7, 18), x, SPRING - 0.15, z), place(new THREE.TorusGeometry(0.66, 0.07, 6, 20), x, 1.1, z, Math.PI / 2));
      bannerParts.push(place(new THREE.PlaneGeometry(1.25, 3.4), x - side * 0.68, 6.6, z, 0, -side * Math.PI / 2));
    }
    ribParts.push(place(new THREE.TorusGeometry(HW - 0.1, 0.16, 6, 36, Math.PI), 0, SPRING, z, 0, 0, 0, 1, 0.75, 1));
  }
  hall.add(new THREE.Mesh(merge(colParts), mat.column), new THREE.Mesh(merge(capParts), mat.gold), new THREE.Mesh(merge(ribParts), mat.gold), new THREE.Mesh(merge(bannerParts), mat.banner));
  // windows: lancets high on both walls, the rose window over the far door (moonlight comes through it)
  const lancets = [];
  for (let z = HZ0 - 7; z > HZ1 + 2; z -= 6) for (const side of [-1, 1]) lancets.push(place(new THREE.PlaneGeometry(1.5, 3.8), side * (HW - 0.03), 8.3, z, 0, -side * Math.PI / 2));
  hall.add(new THREE.Mesh(merge(lancets), mat.lancet));
  const roseIn = new THREE.Mesh(new THREE.CircleGeometry(3.4, 48), mat.rose); roseIn.position.set(0, 12.6, HZ1 + 0.05); hall.add(roseIn);
  capParts.length = 0; const ringParts = [place(new THREE.TorusGeometry(3.5, 0.16, 8, 60), 0, 12.6, HZ1 + 0.08)];
  const beam = new THREE.Mesh(new THREE.PlaneGeometry(5.5, 22), new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide, uniforms: { t: { value: 0 } },
    vertexShader: 'varying vec2 v; void main() { v = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }',
    fragmentShader: 'uniform float t; varying vec2 v; void main() { float e = smoothstep(0., .35, v.x) * smoothstep(1., .65, v.x); float a = e * pow(v.y, 1.4) * (.16 + .04 * sin(t * .7)); gl_FragColor = vec4(vec3(.78, .7, 1.) * a, a); }',
  }));
  beam.position.set(0, 7, HZ1 + 9); beam.rotation.x = -0.72; hall.add(beam);
  const beam2 = beam.clone(); beam2.rotation.set(-0.72, Math.PI / 2, 0, 'YXZ'); hall.add(beam2);
  // chandeliers
  const chParts = [];
  CHAND.forEach((z) => {
    chParts.push(place(new THREE.TorusGeometry(1.5, 0.06, 6, 32), 0, 8.2, z, Math.PI / 2), place(new THREE.TorusGeometry(0.9, 0.05, 6, 24), 0, 8.6, z, Math.PI / 2), place(new THREE.CylinderGeometry(0.03, 0.03, 9.2, 4), 0, 12.8, z));
    for (let k = 0; k < 14; k++) { const a = k / 14 * Math.PI * 2; chParts.push(place(new THREE.CylinderGeometry(0.04, 0.04, 0.28, 5), Math.cos(a) * 1.5, 8.38, z + Math.sin(a) * 1.5)); flames.push([Math.cos(a) * 1.5, 8.62, z + Math.sin(a) * 1.5, 0.3]); }
    for (let k = 0; k < 8; k++) { const a = k / 8 * Math.PI * 2 + 0.2; flames.push([Math.cos(a) * 0.9, 9.0, z + Math.sin(a) * 0.9, 0.26]); }
    glows.push([0, 8.6, z, 9]);
  });
  hall.add(new THREE.Mesh(merge(chParts), mat.iron));
  // candle stands along the carpet
  const standParts = [];
  for (let z = HZ0 - 3; z > HZ1 + 3; z -= 4) for (const side of [-1, 1]) {
    const x = side * 2.35; standParts.push(place(new THREE.CylinderGeometry(0.035, 0.12, 1.5, 8), x, 0.75, z), place(new THREE.TorusGeometry(0.22, 0.025, 5, 16), x, 1.5, z, Math.PI / 2));
    for (let k = -1; k <= 1; k++) flames.push([x + k * 0.2, 1.68 + (k ? 0 : 0.08), z, 0.3]);
    glows.push([x, 1.7, z, 1.6]);
  }
  hall.add(new THREE.Mesh(merge(standParts), mat.gold));
  // the ten room doors: small great doors with a gold rim, a lamp each; the chosen one glows
  const RD = 1.35, RH = RD * 914 / 386, rArch = archPts(RD, RH - 1.5 * RD, 12);
  const rShape = new THREE.Shape(rArch.map((p) => new THREE.Vector2(p.x, p.y)));
  const roomDoors = SLOTS.map((s) => {
    const big = s.side === 0, k = big ? 1.5 : 1, g = new THREE.Group();
    const x = s.side * (HW - 0.06), ry = s.side === 0 ? 0 : -s.side * Math.PI / 2;
    g.position.set(x, 0, s.z); g.rotation.y = ry; g.scale.setScalar(k);
    const leaves = [-1, 1].map((side) => { const h = new THREE.Group(); h.position.set(side * RD, 0, 0.02); h.add(new THREE.Mesh(leafPlane(RD, RH, side > 0), side < 0 ? mat.leafL : mat.leafR)); g.add(h); return h; });
    const rimM = mat.rim.clone(); rimM.emissiveIntensity = 0.7;
    const rim = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(rArch.map((p) => V(p.x * 1.08, p.y * 1.03, 0.05))), 60, 0.07, 6, false), rimM); g.add(rim);
    const back = new THREE.Mesh(new THREE.ShapeGeometry(rShape), new THREE.MeshBasicMaterial({ color: 0x3a1a10 })); back.position.set(0, 0, -0.04); g.add(back);
    hall.add(g);
    const lp = V(x, RH * k + 0.9, s.z).add(s.side === 0 ? V(0, 0, 0.4) : V(-s.side * 0.4, 0, 0));
    return { slot: s, g, leaves, rim: rimM, back: back.material, open: 0, want: 0, sel: 0, sign: lp, at: V(x, 1.6, s.z) };
  });
  // the savings board's place on the right wall, and the Count, who waits for you by the far door
  const countMat = new THREE.MeshStandardMaterial({ map: tex.count, alphaTest: 0.45, side: THREE.DoubleSide, roughness: 0.9, color: 0xd8cce4 });
  const counts = [V(-1.9, 0, 5.2), V(2.6, 0, PLAN.end - 0.5)].map((p) => {
    const g = new THREE.Group(), h = 1.95, m = new THREE.Mesh(new THREE.PlaneGeometry(h * 449 / 959, h), countMat); m.position.y = h / 2; g.add(m);
    const sh = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 0.7), new THREE.MeshBasicMaterial({ map: shadowTex, transparent: true, depthWrite: false })); sh.rotation.x = -Math.PI / 2; sh.position.y = 0.03; g.add(sh);
    g.position.copy(p); scene.add(g); return g;
  });
  scene.add(new THREE.Mesh(merge(stoneParts), mat.wall), new THREE.Mesh(merge(goldParts), mat.gold), new THREE.Mesh(merge(ringParts), mat.gold), new THREE.Mesh(merge(rimParts), mat.rim));

  /* ---------- flames, glows, fireflies, dust, haze ---------- */
  const flameP = points(flames, flameTex, { color: 0xffd6a0, fade: 0.004, gain: 1.6 });
  const glowP = points(glows, glowTex, { color: 0xffb070, fade: 0.01, flicker: 0.6 });
  const flies = []; for (let i = 0; i < (phone ? 50 : 90); i++) { const x = (rnd() - 0.5) * 30, z = 14 - rnd() * 32; if (Math.abs(x) < 1.2) continue; flies.push([x, 0.4 + rnd() * 2.6, z, 0.07, rnd() < 0.5 ? 0xffd27a : 0xc8f0a0]); }
  const flyP = points(flies, moteTex, { drift: 1, flicker: 0, fade: 0.03, gain: 1.4 });
  const dust = []; for (let i = 0; i < 160; i++) { const t = rnd(); dust.push([(rnd() - 0.5) * 4, 0.6 + t * 11, HZ1 + 2 + t * 13 + (rnd() - 0.5) * 3, 0.035, 0xe8dcff]); }
  const dustP = points(dust, moteTex, { drift: 0.4, flicker: 0, fade: 0.02, gain: 0.9 });
  scene.add(flameP, glowP, flyP, dustP);
  const hazes = [];
  for (let i = 0; i < (phone ? 10 : 18); i++) {
    const outside = i < (phone ? 7 : 12), s = new THREE.Sprite(new THREE.SpriteMaterial({ map: hazeTex, transparent: true, depthWrite: false, opacity: outside ? 0.55 : 0.35, color: outside ? 0xb8a0d8 : 0x9a80b0 }));
    const x = (rnd() - 0.5) * (outside ? 40 : 14), z = outside ? 16 - rnd() * 32 : HZ0 - 4 - rnd() * 40;
    s.position.set(x, outside ? 0.7 : 0.5, z); s.scale.set(outside ? 16 : 10, outside ? 3.5 : 2, 1); s.userData = { x, sp: (rnd() - 0.5) * 0.5 }; scene.add(s); hazes.push(s);
  }
  for (const c of counts) { const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: hazeTex, transparent: true, depthWrite: false, opacity: 0.8, color: 0xa890c8 })); s.scale.set(2.6, 0.7, 1); s.position.set(0, 0.25, 0.1); c.add(s); }

  /* ---------- state the walk sets, drawn every frame ---------- */
  const state = { gates: 0, door: 0 };                  // 0 closed .. 1 open
  const ease = (x) => x * x * (3 - 2 * x);
  function setOpen(gate, door) { state.gates = gate; state.door = door; }
  function render(cam, time) {
    const z = cam.z, inside = z < HZ0 + 0.2;
    camera.position.set(cam.x || 0, cam.y, z); camera.rotation.set(cam.pitch, cam.yaw, 0);
    // gates swing in, away from you; the great door's leaves swing into the hall
    const ga = ease(state.gates) * 1.62; gates[0].rotation.y = ga; gates[1].rotation.y = -ga;
    const da = ease(state.door) * 1.45; doorLeaves[0].rotation.y = da; doorLeaves[1].rotation.y = -da;
    doorGlow.intensity = state.door * 60; doorBack.material.opacity = 0;
    for (const d of roomDoors) {                        // a room door opens away from you; the chosen one glows
      d.open += (d.want - d.open) * 0.12; const a = ease(clamp(d.open, 0, 1)) * 1.4; d.leaves[0].rotation.y = a; d.leaves[1].rotation.y = -a;
      d.rim.emissiveIntensity = 0.7 + d.sel * (2.2 + 0.4 * Math.sin(time * 5)); d.back.color.setRGB(0.23 + d.open * 0.77, 0.1 + d.open * 0.68, 0.06 + d.open * 0.4);
    }
    // fog: violet night outside, warm dark inside
    scene.fog.color.copy(inside ? FOG_IN : FOG_OUT); scene.fog.density = inside ? 0.011 : 0.012;
    scene.background = null;
    const u = time;
    for (const m of [flameP, glowP, flyP, dustP]) { m.material.uniforms.t.value = u; m.material.uniforms.px.value = renderer.domElement.height / (2 * Math.tan(camera.fov * Math.PI / 360)); }
    beam.material.uniforms.t.value = u;
    hallLamps.forEach((l, i) => { l.intensity = 56 + 7 * Math.sin(u * 7 + i * 2) + 4 * Math.sin(u * 17 + i); });
    [...gateLamps, ...doorLamps].forEach((l, i) => { l.intensity = (i < 2 ? 9 : 16) * (0.86 + 0.1 * Math.sin(u * 9 + i * 1.7) + 0.05 * Math.sin(u * 23 + i)); });
    driveLamp.intensity = 5 * (0.9 + 0.1 * Math.sin(u * 8));
    mat.tower.emissiveIntensity = 1.5 + 0.2 * Math.sin(u * 1.3);
    for (const h of hazes) { h.position.x = h.userData.x + Math.sin(u * 0.06 + h.userData.sp * 9) * 4; }
    for (const c of counts) { c.rotation.y = Math.atan2(camera.position.x - c.position.x, camera.position.z - c.position.z); c.children[0].scale.y = 1 + 0.006 * Math.sin(u * 1.4); }
    moonGlow.position.copy(camera.position).addScaledVector(moonAt, 500); moonGlow.visible = !inside;
    sky.position.copy(camera.position);
    renderer.render(scene, camera);
  }
  function resize(w, h) { renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
  const tmp = V(0, 0, 0);
  function project(v) {                                 // world point -> CSS pixels on the canvas, and whether it is in front
    tmp.copy(v).project(camera); const r = canvas.getBoundingClientRect();
    return { x: r.left + (tmp.x + 1) / 2 * r.width, y: r.top + (1 - tmp.y) / 2 * r.height, front: tmp.z < 1 && tmp.z > -1, dist: camera.position.distanceTo(v) };
  }
  function moonScreen() { return project(camera.position.clone().addScaledVector(moonAt, 400)); }
  return {
    render, resize, project, moonScreen, setOpen, renderer, camera,
    roomDoors, counts: counts.map((c) => c.position.clone().add(V(0, 2.05, 0))),
    anchors: { gates: V(0, 2, PLAN.gateZ), door: V(0, 3.4, DZ) },
    plan: { ...PLAN, towers: TOWERS.map(([x, z, r]) => [x, z, r]), lanterns: [-3, -8, -13, -18, -23, 5.5] },
  };
}
