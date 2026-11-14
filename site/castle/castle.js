/* CHIMERA castle in 3D (three.js, vendored). One page on one port.
   Outside the gate -> the Great Hall (guide desk, savings board) -> grand staircase -> gallery with three doors:
   Dashboard, Chat, Evals. Panels are HTML overlays (castle/panels.js). Motion never pauses (user rule).
   All shapes are built here from primitives and canvas textures: no downloaded models, so no asset licences. */
import * as THREE from '../vendor/three.module.min.js';

const $ = (s, r) => (r || document).querySelector(s);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const DEV = new URLSearchParams(location.search).has('dev');

export async function start(root, opts = {}) {
  const base = opts.base || 'castle/';
  const L = await (await fetch(base + 'layout.json')).json();
  const P = window.CastlePhysics.make(L);
  const UP = L.levels.upper;

  /* ---------------- DOM shell ---------------- */
  root.classList.add('c3-root');
  root.innerHTML = `
    <canvas class="c3-canvas" tabindex="0" aria-label="The castle in 3D. Walk with W A S D or the arrow keys, look with the mouse, press M for a list of places."></canvas>
    <div class="c3-bar"><span class="c3-where" id="c3-where"></span>
      <span class="c3-fps" id="c3-fps" ${DEV ? '' : 'hidden'}></span>
      <button class="w-btn" id="c3-mapbtn" type="button" aria-haspopup="dialog">Map and rooms (M)</button></div>
    <canvas class="c3-mini" id="c3-mini" width="200" height="150" aria-hidden="true"></canvas>
    <div class="c3-help" id="c3-help"><kbd>Click</kbd> to look with the mouse · <kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd> walk · <kbd>Shift</kbd> run · <kbd>E</kbd>/<kbd>Enter</kbd> use · <kbd>M</kbd> map · <kbd>Esc</kbd> leave</div>
    <div class="w-prompt" id="c3-prompt" aria-live="polite"></div>
    <div class="c3-cross" aria-hidden="true"></div>
    <div class="w-joy" id="c3-joy"><i></i></div><button class="w-act" id="c3-act" type="button" aria-label="Use">E</button>
    <section class="w-panel" id="c3-panel" role="dialog" aria-modal="true" aria-labelledby="c3-ptitle" hidden>
      <div class="w-ph"><h2 id="c3-ptitle"></h2><button class="w-btn" id="c3-pclose" type="button">Leave (Esc)</button></div>
      <div class="w-pb" id="c3-pbody"></div></section>
    <div class="w-travel" id="c3-map" hidden><div role="dialog" aria-modal="true" aria-labelledby="c3-mtitle">
      <h2 id="c3-mtitle">Map of the castle</h2><canvas id="c3-bigmap" width="560" height="380" aria-hidden="true" style="width:100%;border-radius:8px;background:#0b0510"></canvas>
      <div id="c3-mlist"></div><button class="w-btn" id="c3-mclose" type="button" style="margin-top:.8rem">Close (Esc)</button></div></div>
    <div class="w-fade" id="c3-fade"></div>`;
  const el = (id) => $('#' + id, root);
  const canvas = $('canvas.c3-canvas', root);

  /* ---------------- renderer ---------------- */
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
  const maxDpr = opts.maxDpr || 1.25;  // shortcut: capped for the 4 GB Mac; raise on a desktop GPU
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, maxDpr));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.25;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x8a6f9e, 45, 140);
  const camera = new THREE.PerspectiveCamera(68, 1, 0.1, 400);
  scene.add(camera);

  /* ---------------- textures (drawn on canvas, tiny) ---------------- */
  function tex(w, h, draw, rx = 1, ry = 1) {
    const c = document.createElement('canvas'); c.width = w; c.height = h; draw(c.getContext('2d'), w, h);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(rx, ry); t.anisotropy = 4; return t;
  }
  const rnd = (() => { let s = 7; return () => ((s = (s * 16807) % 2147483647) / 2147483647); })();
  const stoneImg = (g, w, h, base, mortar) => {
    g.fillStyle = mortar; g.fillRect(0, 0, w, h);
    const rows = 8, bh = h / rows;
    for (let r = 0; r < rows; r++) {
      const off = (r % 2) * (w / 8);
      for (let x = -off; x < w; x += w / 4) {
        const k = 0.85 + rnd() * 0.3; const [R, G, B] = base;
        g.fillStyle = `rgb(${R * k | 0},${G * k | 0},${B * k | 0})`;
        g.fillRect(x + 2, r * bh + 2, w / 4 - 4, bh - 4);
        g.fillStyle = 'rgba(255,255,255,.06)'; g.fillRect(x + 2, r * bh + 2, w / 4 - 4, 3);
      }
    }
  };
  const T = {
    stone: tex(256, 256, (g, w, h) => stoneImg(g, w, h, [168, 150, 160], '#5e4f5c')),
    stoneOut: tex(256, 256, (g, w, h) => stoneImg(g, w, h, [150, 138, 150], '#544656')),
    floor: tex(256, 256, (g, w, h) => {
      for (let y = 0; y < 4; y++) for (let x = 0; x < 4; x++) {
        g.fillStyle = (x + y) % 2 ? '#d9cdb8' : '#5b3b48'; g.fillRect(x * 64, y * 64, 64, 64);
        g.strokeStyle = 'rgba(80,50,30,.35)'; g.strokeRect(x * 64 + .5, y * 64 + .5, 63, 63);
      }
    }, 8, 8),
    cobble: tex(256, 256, (g, w, h) => {
      g.fillStyle = '#5c5560'; g.fillRect(0, 0, w, h);
      for (let i = 0; i < 160; i++) { const x = rnd() * w, y = rnd() * h, r = 6 + rnd() * 8, k = 0.8 + rnd() * 0.4; g.fillStyle = `rgb(${130 * k | 0},${122 * k | 0},${132 * k | 0})`; g.beginPath(); g.ellipse(x, y, r, r * 0.8, rnd() * 3, 0, 7); g.fill(); }
    }, 26, 18),
    grass: tex(128, 128, (g, w, h) => { g.fillStyle = '#4c6b3c'; g.fillRect(0, 0, w, h); for (let i = 0; i < 400; i++) { g.fillStyle = rnd() > .5 ? '#5f8048' : '#3f5a32'; g.fillRect(rnd() * w, rnd() * h, 2, 3); } }, 40, 40),
    wood: tex(128, 128, (g, w, h) => { g.fillStyle = '#6b4226'; g.fillRect(0, 0, w, h); for (let i = 0; i < 9; i++) { g.fillStyle = i % 2 ? '#5a361e' : '#7a4c2c'; g.fillRect(0, i * 14.2, w, 12); } g.fillStyle = 'rgba(0,0,0,.25)'; for (let i = 0; i < 30; i++) g.fillRect(rnd() * w, rnd() * h, 18, 1); }),
    carpet: tex(64, 256, (g, w, h) => { g.fillStyle = '#8e1630'; g.fillRect(0, 0, w, h); g.fillStyle = '#d9a441'; g.fillRect(3, 0, 3, h); g.fillRect(w - 6, 0, 3, h); for (let y = 10; y < h; y += 32) { g.beginPath(); g.moveTo(w / 2, y); g.lineTo(w / 2 + 8, y + 8); g.lineTo(w / 2, y + 16); g.lineTo(w / 2 - 8, y + 8); g.fill(); } }, 1, 3),
    banner: tex(128, 256, (g, w, h) => { g.fillStyle = '#7a1028'; g.fillRect(0, 0, w, h); g.fillStyle = '#e2b04a'; g.fillRect(6, 6, w - 12, 4); g.beginPath(); g.arc(w / 2, 100, 30, 0, 7); g.fill(); g.fillStyle = '#7a1028'; g.beginPath(); g.arc(w / 2 + 10, 92, 26, 0, 7); g.fill(); g.fillStyle = '#e2b04a'; g.font = 'bold 26px serif'; g.textAlign = 'center'; g.fillText('C', w / 2, 210); }),
  };
  const mat = {
    stone: new THREE.MeshStandardMaterial({ map: T.stone, roughness: 0.92 }),
    stoneOut: new THREE.MeshStandardMaterial({ map: T.stoneOut, roughness: 0.95 }),
    floor: new THREE.MeshStandardMaterial({ map: T.floor, roughness: 0.55, metalness: 0.05 }),
    cobble: new THREE.MeshStandardMaterial({ map: T.cobble, roughness: 1 }),
    grass: new THREE.MeshStandardMaterial({ map: T.grass, roughness: 1 }),
    wood: new THREE.MeshStandardMaterial({ map: T.wood, roughness: 0.8 }),
    carpet: new THREE.MeshStandardMaterial({ map: T.carpet, roughness: 1 }),
    roof: new THREE.MeshStandardMaterial({ color: 0x3b2a5a, roughness: 0.8, flatShading: true }),
    gold: new THREE.MeshStandardMaterial({ color: 0xd9a441, metalness: 0.7, roughness: 0.35 }),
    iron: new THREE.MeshStandardMaterial({ color: 0x2b2630, metalness: 0.6, roughness: 0.5 }),
    flame: new THREE.MeshBasicMaterial({ color: 0xffb347 }),
    glass: new THREE.MeshBasicMaterial({ color: 0xbcd7ff }),
  };
  function texFor(m, w, h) { // clone a textured material so bricks keep their size on any wall
    const t = m.map.clone(); t.needsUpdate = true; t.repeat.set(Math.max(1, w / 3), Math.max(1, h / 3)); const c = m.clone(); c.map = t; return c;
  }
  function box(w, h, d, m, x, y, z, cast = true) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m); mesh.position.set(x, y, z);
    mesh.castShadow = cast; mesh.receiveShadow = true; scene.add(mesh); return mesh;
  }

  /* ---------------- sky, sun, hills ---------------- */
  const sky = new THREE.Mesh(new THREE.SphereGeometry(300, 32, 16), new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: { top: { value: new THREE.Color(0x3d3a8c) }, mid: { value: new THREE.Color(0xc97aa8) }, low: { value: new THREE.Color(0xffb27a) } },
    vertexShader: 'varying vec3 v; void main(){ v = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.); }',
    fragmentShader: 'uniform vec3 top, mid, low; varying vec3 v; void main(){ float h = v.y; vec3 c = h > .18 ? mix(mid, top, smoothstep(.18,.8,h)) : mix(low, mid, smoothstep(-.05,.18,h)); gl_FragColor = vec4(c,1.); }',
  }));
  scene.add(sky);
  const moon = new THREE.Mesh(new THREE.SphereGeometry(9, 24, 12), new THREE.MeshBasicMaterial({ color: 0xffd9a0, fog: false }));
  moon.position.set(-90, 75, -200); scene.add(moon);
  const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex(64, 64, (g) => { const r = g.createRadialGradient(32, 32, 0, 32, 32, 32); r.addColorStop(0, 'rgba(255,220,170,.7)'); r.addColorStop(1, 'rgba(255,220,170,0)'); g.fillStyle = r; g.fillRect(0, 0, 64, 64); }), fog: false, depthWrite: false, transparent: true }));
  halo.scale.set(70, 70, 1); halo.position.copy(moon.position); scene.add(halo);
  for (let i = 0; i < 24; i++) { // distant hills
    const a = (i / 24) * Math.PI * 2, r = 150 + rnd() * 30, h = 18 + rnd() * 26;
    const hill = new THREE.Mesh(new THREE.ConeGeometry(28 + rnd() * 20, h, 5), new THREE.MeshStandardMaterial({ color: 0x4a3a62, flatShading: true, roughness: 1 }));
    hill.position.set(Math.cos(a) * r, h / 2 - 2, Math.sin(a) * r - 20); scene.add(hill);
  }
  const clouds = [];
  const cloudTex = tex(128, 64, (g) => { for (let i = 0; i < 7; i++) { const r = g.createRadialGradient(20 + i * 14, 34, 0, 20 + i * 14, 34, 26); r.addColorStop(0, 'rgba(255,230,240,.55)'); r.addColorStop(1, 'rgba(255,230,240,0)'); g.fillStyle = r; g.fillRect(0, 0, 128, 64); } });
  for (let i = 0; i < 9; i++) { const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: cloudTex, transparent: true, depthWrite: false, fog: false })); s.scale.set(60, 22, 1); s.position.set(-150 + i * 40, 55 + rnd() * 30, -160 - rnd() * 60); scene.add(s); clouds.push(s); }

  /* ---------------- lights ---------------- */
  scene.add(new THREE.HemisphereLight(0xd8c8ff, 0x6a5040, 1.15));
  const sun = new THREE.DirectionalLight(0xffd2a6, 2.2);
  sun.position.set(-30, 45, 40); sun.castShadow = true; sun.shadow.mapSize.set(1024, 1024);
  Object.assign(sun.shadow.camera, { left: -45, right: 45, top: 45, bottom: -45, near: 1, far: 140 });
  sun.target.position.set(0, 0, -10); scene.add(sun, sun.target);
  scene.add(new THREE.AmbientLight(0xfff0e0, 0.35));

  /* ---------------- ground ---------------- */
  const grass = new THREE.Mesh(new THREE.PlaneGeometry(400, 400), mat.grass); grass.rotation.x = -Math.PI / 2; grass.position.y = -0.02; grass.receiveShadow = true; scene.add(grass);
  const court = new THREE.Mesh(new THREE.PlaneGeometry(62, 42), mat.cobble); court.rotation.x = -Math.PI / 2; court.position.set(0, 0, 20); court.receiveShadow = true; scene.add(court);
  const hallFloor = new THREE.Mesh(new THREE.PlaneGeometry(30, 28), mat.floor); hallFloor.rotation.x = -Math.PI / 2; hallFloor.position.set(0, 0.01, -15.5); hallFloor.receiveShadow = true; scene.add(hallFloor);
  const path = new THREE.Mesh(new THREE.PlaneGeometry(5, 40), mat.carpet.clone()); path.material.map = T.carpet.clone(); path.material.map.repeat.set(1, 10); path.material.map.needsUpdate = true;
  path.rotation.x = -Math.PI / 2; path.position.set(0, 0.02, -2); path.receiveShadow = true; scene.add(path);

  /* ---------------- walls from layout ---------------- */
  for (const w of L.walls) {
    const W = w.x1 - w.x0, D = w.z1 - w.z0, cx = (w.x0 + w.x1) / 2, cz = (w.z0 + w.z1) / 2;
    if (w.kind === 'stone') box(W, w.h, D, texFor(cz > -1 ? mat.stoneOut : mat.stone, Math.max(W, D), w.h), cx, w.h / 2, cz);
    else if (w.kind === 'low') box(W, w.h, D, texFor(mat.stoneOut, Math.max(W, D), w.h), cx, w.h / 2, cz);
    else if (w.kind === 'pillar') {
      const p = new THREE.Mesh(new THREE.CylinderGeometry(0.62, 0.75, w.h, 12), texFor(mat.stone, 4, w.h)); p.position.set(cx, w.h / 2, cz); p.castShadow = p.receiveShadow = true; scene.add(p);
      box(1.7, 0.5, 1.7, mat.stone, cx, 0.25, cz); box(1.7, 0.5, 1.7, mat.stone, cx, w.h - 0.25, cz);
    }
  }
  // crenellations on the front wall, gate lintel and arch
  for (let x = -15.5; x <= 15.5; x += 1.6) box(0.9, 1, 1.6, mat.stoneOut, x, 14, -0.75);
  box(5.2, 7.9, 1.5, texFor(mat.stoneOut, 5, 7.9), 0, 9.55, -0.75);
  const arch = new THREE.Mesh(new THREE.TorusGeometry(2.6, 0.35, 8, 24, Math.PI), mat.stoneOut); arch.position.set(0, 5.6 - 0.1, 0.05); scene.add(arch);
  // side walls and back wall crenellations
  for (let z = -29; z <= -2; z += 1.6) { box(1, 1, 0.9, mat.stoneOut, -15.5, 13.5, z); box(1, 1, 0.9, mat.stoneOut, 15.5, 13.5, z); }
  // towers
  const flags = [];
  function tower(x, z, r, h) {
    const t = new THREE.Mesh(new THREE.CylinderGeometry(r, r * 1.08, h, 16), texFor(mat.stoneOut, r * 6, h)); t.position.set(x, h / 2, z); t.castShadow = t.receiveShadow = true; scene.add(t);
    for (let i = 0; i < 12; i++) { const a = i / 12 * Math.PI * 2; box(0.9, 1.1, 0.9, mat.stoneOut, x + Math.cos(a) * r, h + 0.5, z + Math.sin(a) * r); }
    const roof = new THREE.Mesh(new THREE.ConeGeometry(r * 1.15, r * 2.2, 16), mat.roof); roof.position.set(x, h + 1 + r * 1.1, z); roof.castShadow = true; scene.add(roof);
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 3), mat.iron); pole.position.set(x, h + 1 + r * 2.2 + 1.5, z); scene.add(pole);
    const fg = new THREE.PlaneGeometry(2.4, 1.3, 12, 4); fg.translate(1.2, 0, 0);
    const flag = new THREE.Mesh(fg, new THREE.MeshStandardMaterial({ color: 0x9c1838, side: THREE.DoubleSide, roughness: 1 }));
    flag.position.set(x, h + 1 + r * 2.2 + 2.3, z); scene.add(flag); flags.push({ mesh: flag, base: fg.attributes.position.array.slice() });
    for (let k = 0; k < 3; k++) { const wnd = new THREE.Mesh(new THREE.PlaneGeometry(0.7, 1.4), new THREE.MeshBasicMaterial({ color: 0xffd27a })); wnd.position.set(x, 5 + k * 3.5, z + r + 0.02); scene.add(wnd); }
  }
  tower(-16, 0.5, 3.5, 15); tower(16, 0.5, 3.5, 15); tower(-16, -29.5, 3, 18); tower(16, -29.5, 3, 18);
  // keep (the tall part behind) so the outside reads as a castle
  box(14, 8, 10, texFor(mat.stoneOut, 14, 8), 0, 17, -24);
  const keepRoof = new THREE.Mesh(new THREE.ConeGeometry(9, 7, 4), mat.roof); keepRoof.rotation.y = Math.PI / 4; keepRoof.position.set(0, 24.5, -24); scene.add(keepRoof);
  // roof over the hall
  const hallRoof = box(32, 0.6, 30, mat.wood, 0, 13.3, -15.25); hallRoof.material = new THREE.MeshStandardMaterial({ color: 0x4a2c1c, roughness: 0.9 });
  for (let z = -28; z <= -3; z += 4) box(30, 0.5, 0.5, mat.wood, 0, 12.7, z);

  /* ---------------- the gate ---------------- */
  const gate = { open: false, t: 0 };
  const leafMat = texFor(mat.wood, 2, 5);
  function leaf(side) {
    const pivot = new THREE.Group(); pivot.position.set(side * 2.6, 0, -0.3); scene.add(pivot);
    const m = new THREE.Mesh(new THREE.BoxGeometry(2.6, 5.4, 0.25), leafMat); m.position.set(-side * 1.3, 2.7, 0); m.castShadow = true; pivot.add(m);
    for (const y of [1, 2.7, 4.4]) { const band = new THREE.Mesh(new THREE.BoxGeometry(2.6, 0.18, 0.3), mat.iron); band.position.set(-side * 1.3, y, 0.02); pivot.add(band); }
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.18, 0.04, 6, 12), mat.gold); ring.position.set(-side * 0.35, 2.6, 0.2); pivot.add(ring);
    return pivot;
  }
  const leaves = [leaf(-1), leaf(1)];
  const sign = new THREE.Mesh(new THREE.PlaneGeometry(5, 1.2), new THREE.MeshBasicMaterial({ map: textPlate('CHIMERA', 'press Enter to open the gate', 512, 128) }));
  sign.position.set(0, 7.0, 0.05); sign.scale.set(1.3, 1.3, 1); scene.add(sign);

  function textPlate(title, sub, w = 512, h = 160, theme = 'gold') {
    return tex(w, h, (g) => {
      g.fillStyle = theme === 'gold' ? '#2a0f2f' : '#1d0a22'; g.fillRect(0, 0, w, h);
      g.strokeStyle = '#d9a441'; g.lineWidth = 8; g.strokeRect(6, 6, w - 12, h - 12);
      g.fillStyle = '#f4d58d'; g.textAlign = 'center'; g.font = `700 ${Math.round(h * 0.42)}px Cinzel, Georgia, serif`; g.fillText(title, w / 2, h * (sub ? 0.52 : 0.64));
      if (sub) { g.fillStyle = '#f1e6da'; g.font = `500 ${Math.round(h * 0.2)}px Inter, Arial, sans-serif`; g.fillText(sub, w / 2, h * 0.82); }
    });
  }

  /* ---------------- torches, windows, banners, chandelier ---------------- */
  const fires = [];
  const torchLights = [];
  function torch(x, y, z, face, light) {
    const g = new THREE.Group(); g.position.set(x, y, z); g.rotation.y = face; scene.add(g);
    const stick = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.04, 0.7), mat.wood); stick.rotation.x = 0.5; stick.position.set(0, 0, 0.25); g.add(stick);
    const cup = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.08, 0.18, 8), mat.iron); cup.position.set(0, 0.3, 0.42); g.add(cup);
    const fl = new THREE.Mesh(new THREE.ConeGeometry(0.13, 0.42, 8), mat.flame); fl.position.set(0, 0.6, 0.42); g.add(fl);
    fires.push(fl);
    if (light) { const p = new THREE.PointLight(0xffa04a, 14, 14, 1.6); p.position.set(0, 0.8, 0.7); g.add(p); torchLights.push(p); }
  }
  // outside torches by the gate, inside along the hall, upstairs by the doors
  torch(-3.6, 3.4, 0.05, 0, true); torch(3.6, 3.4, 0.05, 0, true);
  for (const z of [-5, -14, -23]) { torch(-14.95, 3.2, z, Math.PI / 2, z !== -23); torch(14.95, 3.2, z, -Math.PI / 2, z !== -23); }
  for (const x of [-12, -4, 4, 12]) torch(x, UP + 3.0, -28.95, 0, Math.abs(x) === 4);
  // tall windows with daylight on the side walls
  for (const z of [-9, -20]) for (const s of [-1, 1]) {
    const wnd = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 4.2), mat.glass); wnd.position.set(s * 14.95, 7, z); wnd.rotation.y = -s * Math.PI / 2; scene.add(wnd);
    const fr = new THREE.Mesh(new THREE.TorusGeometry(0.8, 0.09, 6, 16, Math.PI), mat.stone); fr.position.set(s * 14.93, 9.1, z); fr.rotation.y = -s * Math.PI / 2; scene.add(fr);
    const shaft = new THREE.Mesh(new THREE.PlaneGeometry(2, 9), new THREE.MeshBasicMaterial({ color: 0xcfe0ff, transparent: true, opacity: 0.08, depthWrite: false, side: THREE.DoubleSide }));
    shaft.position.set(s * 12.5, 4.2, z); shaft.rotation.set(0, -s * Math.PI / 2, s * 0.6); scene.add(shaft);
    const day = new THREE.SpotLight(0xdde8ff, 30, 30, 0.6, 0.7, 1.4); day.position.set(s * 14.2, 9, z); day.target.position.set(s * 6, 0, z); scene.add(day, day.target);
  }
  const banners = [];
  for (const z of [-3.5, -16]) for (const s of [-1, 1]) {
    const bg = new THREE.PlaneGeometry(1.6, 3.6, 4, 12);
    const bm = new THREE.Mesh(bg, new THREE.MeshStandardMaterial({ map: T.banner, side: THREE.DoubleSide, roughness: 1 }));
    bm.position.set(s * 14.9, 9.3, z); bm.rotation.y = -s * Math.PI / 2; scene.add(bm); banners.push({ mesh: bm, base: bg.attributes.position.array.slice() });
  }
  const chand = new THREE.Group(); chand.position.set(0, 10.6, -6); scene.add(chand);
  chand.add(new THREE.Mesh(new THREE.TorusGeometry(1.6, 0.07, 6, 24), mat.gold)).rotation.x = Math.PI / 2;
  for (let i = 0; i < 8; i++) { const a = i / 8 * Math.PI * 2; const c = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.3), new THREE.MeshStandardMaterial({ color: 0xf3e9dc })); c.position.set(Math.cos(a) * 1.6, 0.15, Math.sin(a) * 1.6); chand.add(c); const f = new THREE.Mesh(new THREE.ConeGeometry(0.05, 0.16, 6), mat.flame); f.position.set(Math.cos(a) * 1.6, 0.38, Math.sin(a) * 1.6); chand.add(f); fires.push(f); }
  const chain = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 2.2), mat.iron); chain.position.y = 1.1; chand.add(chain);
  const chLight = new THREE.PointLight(0xffc27a, 40, 22, 1.4); chLight.position.y = -0.3; chand.add(chLight);

  /* ---------------- stairs and gallery ---------------- */
  const st = L.stairs, n = st.steps, stepD = (st.z1 - st.z0) / n, stepH = UP / n;
  for (let i = 0; i < n; i++) {
    const h = (i + 1) * stepH, z = st.z1 - (i + 0.5) * stepD;
    box(st.x1 - st.x0, h, stepD, texFor(mat.stone, 6, h), 0, h / 2, z);
    box(2.6, 0.03, stepD + 0.01, mat.carpet, 0, h + 0.015, z, false);
  }
  for (const s of [-1, 1]) { // balustrades
    const rail = new THREE.Mesh(new THREE.BoxGeometry(0.25, 0.18, Math.hypot(10, UP)), mat.wood); rail.position.set(s * 3.2, UP / 2 + 1.05, (st.z0 + st.z1) / 2); rail.rotation.x = Math.atan2(UP, 10); scene.add(rail);
    for (let i = 0; i <= n; i += 2) { const h = i * stepH; const b = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 1), mat.wood); b.position.set(s * 3.2, h + 0.5, st.z1 - i * stepD); scene.add(b); }
  }
  const mz = L.mezzanine;
  box(mz.x1 - mz.x0, 0.4, mz.z1 - mz.z0, mat.wood, 0, UP - 0.2, (mz.z0 + mz.z1) / 2);
  const gal = new THREE.Mesh(new THREE.PlaneGeometry(mz.x1 - mz.x0, mz.z1 - mz.z0), mat.floor); gal.rotation.x = -Math.PI / 2; gal.position.set(0, UP + 0.01, (mz.z0 + mz.z1) / 2); gal.receiveShadow = true; scene.add(gal);
  for (const s of [-1, 1]) { // gallery railing with balusters
    const x0 = s < 0 ? -15 : 3.4, x1 = s < 0 ? -3.4 : 15;
    box(x1 - x0, 0.15, 0.2, mat.wood, (x0 + x1) / 2, UP + 1.05, -18, false);
    for (let x = x0 + 0.3; x < x1; x += 0.8) box(0.09, 1, 0.09, mat.wood, x, UP + 0.5, -18, false);
  }

  /* ---------------- the three doors ---------------- */
  const doors = [];
  for (const d of L.doors) {
    const g = new THREE.Group(); g.position.set(d.x, UP, d.z + 0.52); scene.add(g);
    const frame = new THREE.Mesh(new THREE.BoxGeometry(3.2, 4.4, 0.3), mat.stone); frame.position.y = 2.2; g.add(frame);
    const dark = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 3.6), new THREE.MeshBasicMaterial({ color: 0x1a0d1e })); dark.position.set(0, 1.8, 0.16); g.add(dark);
    const glow = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 3.6), new THREE.MeshBasicMaterial({ color: 0xffc27a, transparent: true, opacity: 0 })); glow.position.set(0, 1.8, 0.165); g.add(glow);
    const hinge = new THREE.Group(); hinge.position.set(-1.2, 0, 0.2); g.add(hinge);
    const leafM = new THREE.Mesh(new THREE.BoxGeometry(2.4, 3.6, 0.14), texFor(mat.wood, 2, 4)); leafM.position.set(1.2, 1.8, 0); hinge.add(leafM);
    const knob = new THREE.Mesh(new THREE.SphereGeometry(0.08, 8, 6), mat.gold); knob.position.set(2.1, 1.8, 0.1); hinge.add(knob);
    const plate = new THREE.Mesh(new THREE.PlaneGeometry(3.4, 1), new THREE.MeshBasicMaterial({ map: textPlate(d.label, d.sub, 512, 150) })); plate.position.set(0, 4.95, 0.2); g.add(plate);
    doors.push({ d, hinge, glow, open: 0 });
  }

  /* ---------------- guide desk and the guide ---------------- */
  const G = L.guide;
  box(4.8, 1.1, 1.6, texFor(mat.wood, 4, 1), 7, 0.55, -7.4);
  box(5, 0.08, 1.8, mat.gold, 7, 1.14, -7.4, false);
  const deskSign = new THREE.Mesh(new THREE.PlaneGeometry(3, 0.7), new THREE.MeshBasicMaterial({ map: textPlate('Guide', 'press E to ask', 512, 120) })); deskSign.position.set(7, 0.62, -6.58); scene.add(deskSign);
  const book = box(0.8, 0.12, 0.6, new THREE.MeshStandardMaterial({ color: 0x5a1020 }), 6, 1.24, -7.4, false); book.rotation.y = 0.3;
  const candle = box(0.12, 0.35, 0.12, new THREE.MeshStandardMaterial({ color: 0xf3e9dc }), 8.6, 1.35, -7.2, false);
  const cf = new THREE.Mesh(new THREE.ConeGeometry(0.06, 0.18, 6), mat.flame); cf.position.set(8.6, 1.62, -7.2); scene.add(cf); fires.push(cf);
  const deskLight = new THREE.PointLight(0xffb060, 10, 8, 1.5); deskLight.position.set(8.6, 2, -7); scene.add(deskLight); torchLights.push(deskLight);
  const chair = box(1.4, 2.6, 0.3, mat.wood, G.x, 1.3, G.z - 0.7); chair.material = new THREE.MeshStandardMaterial({ color: 0x5a1a2a, roughness: 0.9 });
  const guide = new THREE.Group(); guide.position.set(G.x, 0, G.z); scene.add(guide);
  const robe = new THREE.MeshStandardMaterial({ color: 0x3b2a6a, roughness: 0.85 });
  const skin = new THREE.MeshStandardMaterial({ color: 0xe8c8b0, roughness: 0.7 });
  const torso = new THREE.Mesh(new THREE.CylinderGeometry(0.42, 0.55, 1.2, 10), robe); torso.position.y = 1.45; guide.add(torso);
  const collar = new THREE.Mesh(new THREE.TorusGeometry(0.36, 0.07, 6, 16), mat.gold); collar.rotation.x = Math.PI / 2; collar.position.y = 2.02; guide.add(collar);
  const head = new THREE.Group(); head.position.y = 2.38; guide.add(head);
  head.add(new THREE.Mesh(new THREE.SphereGeometry(0.3, 16, 12), skin));
  const hair = new THREE.Mesh(new THREE.SphereGeometry(0.32, 16, 12, 0, Math.PI * 2, 0, Math.PI / 2.4), new THREE.MeshStandardMaterial({ color: 0x5a4a52 })); hair.position.set(0, 0.06, -0.03); head.add(hair);
  const hat = new THREE.Mesh(new THREE.ConeGeometry(0.36, 0.7, 12), new THREE.MeshStandardMaterial({ color: 0x2a1a50 })); hat.position.y = 0.48; head.add(hat);
  const brim = new THREE.Mesh(new THREE.CylinderGeometry(0.46, 0.46, 0.04, 16), new THREE.MeshStandardMaterial({ color: 0x2a1a50 })); brim.position.y = 0.17; head.add(brim);
  for (const s of [-1, 1]) {
    const white = new THREE.Mesh(new THREE.SphereGeometry(0.06, 8, 6), new THREE.MeshBasicMaterial({ color: 0xffffff })); white.position.set(s * 0.11, 0.03, 0.25); head.add(white);
    const eye = new THREE.Mesh(new THREE.SphereGeometry(0.035, 8, 6), new THREE.MeshBasicMaterial({ color: 0x2a1840 })); eye.position.set(s * 0.11, 0.03, 0.3); head.add(eye);
    const brow = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.025, 0.03), new THREE.MeshBasicMaterial({ color: 0xd0d0d8 })); brow.position.set(s * 0.11, 0.12, 0.27); head.add(brow);
  }
  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.045, 0.14, 6), skin); nose.rotation.x = Math.PI / 2; nose.position.set(0, -0.04, 0.32); head.add(nose);
  const beard = new THREE.Mesh(new THREE.ConeGeometry(0.2, 0.45, 8), new THREE.MeshStandardMaterial({ color: 0xc8c8d0 })); beard.rotation.x = Math.PI; beard.position.set(0, -0.28, 0.17); head.add(beard);
  const arms = [];
  for (const s of [-1, 1]) { const a = new THREE.Group(); a.position.set(s * 0.5, 1.9, 0); guide.add(a); const m = new THREE.Mesh(new THREE.CylinderGeometry(0.11, 0.13, 0.85, 8), robe); m.position.set(0, -0.35, 0.25); m.rotation.x = -1.0; a.add(m); const hand = new THREE.Mesh(new THREE.SphereGeometry(0.1, 8, 6), skin); hand.position.set(0, -0.62, 0.62); a.add(hand); arms.push(a); }
  guide.traverse((o) => { if (o.isMesh) o.castShadow = true; });

  /* ---------------- savings board ---------------- */
  const B = L.board;
  const boardCanvas = document.createElement('canvas'); boardCanvas.width = 1024; boardCanvas.height = 640;
  const boardTex = new THREE.CanvasTexture(boardCanvas); boardTex.colorSpace = THREE.SRGBColorSpace;
  const boardMesh = new THREE.Mesh(new THREE.PlaneGeometry(6.4, 4), new THREE.MeshBasicMaterial({ map: boardTex }));
  boardMesh.position.set(B.x, 3.4, B.z); boardMesh.rotation.y = Math.PI / 2; scene.add(boardMesh);
  box(0.2, 4.4, 6.8, mat.wood, B.x - 0.12, 3.4, B.z, false);
  function drawBoard(s) {
    const g = boardCanvas.getContext('2d'), W = 1024, H = 640;
    g.fillStyle = '#1d0a22'; g.fillRect(0, 0, W, H); g.strokeStyle = '#d9a441'; g.lineWidth = 12; g.strokeRect(10, 10, W - 20, H - 20);
    g.fillStyle = '#f4d58d'; g.textAlign = 'center'; g.font = '700 54px Cinzel, Georgia, serif'; g.fillText('The savings board', W / 2, 92);
    const cells = s ? [
      ['Tokens kept off the big model', fmt(s.tokens_kept_off_big)], ['Dollars saved', '$' + (s.dollars_saved || 0).toFixed(4)],
      ['GPU calls avoided', fmt(s.gpu_calls_avoided)], ['Cache hit rate', Math.round((s.hit_rate || 0) * 100) + '%'],
    ] : [['Loading', '…']];
    cells.forEach(([k, v], i) => {
      const x = 60 + (i % 2) * 470, y = 150 + Math.floor(i / 2) * 210;
      g.fillStyle = '#2c1838'; g.fillRect(x, y, 440, 180); g.strokeStyle = '#5b2a6a'; g.lineWidth = 3; g.strokeRect(x, y, 440, 180);
      g.textAlign = 'left'; g.fillStyle = '#d9c9e0'; g.font = '500 30px Inter, Arial, sans-serif'; g.fillText(k, x + 22, y + 50);
      g.fillStyle = '#ffffff'; g.font = '700 74px Cinzel, Georgia, serif'; g.fillText(v, x + 22, y + 140);
    });
    g.textAlign = 'center'; g.fillStyle = '#cdb8d8'; g.font = '500 24px Inter, Arial, sans-serif';
    g.fillText(s ? `${fmt(s.calls)} calls logged on this machine · /api/stats` : 'reading /api/stats', W / 2, H - 34);
    boardTex.needsUpdate = true;
  }
  const fmt = (v) => (v == null ? '–' : Number(v).toLocaleString());
  drawBoard(null);
  async function refreshStats() {
    try { const r = await fetch('/api/stats', { cache: 'no-store' }); if (r.ok) { const j = await r.json(); S.stats = j; drawBoard(j.global && j.global.calls ? j.global : j.session); } } catch (e) { /* board keeps the last numbers */ }
  }

  /* ---------------- bats outside ---------------- */
  const bats = [];
  const batMat = new THREE.MeshBasicMaterial({ color: 0x120818, side: THREE.DoubleSide });
  for (let i = 0; i < 6; i++) {
    const g = new THREE.Group(); scene.add(g);
    const body = new THREE.Mesh(new THREE.SphereGeometry(0.18, 6, 4), batMat); g.add(body);
    const wl = new THREE.Mesh(new THREE.PlaneGeometry(0.7, 0.3), batMat); wl.position.x = -0.38; g.add(wl);
    const wr = wl.clone(); wr.position.x = 0.38; g.add(wr);
    bats.push({ g, wl, wr, r: 8 + i * 3, h: 16 + (i % 3) * 3, s: 0.35 + i * 0.07, o: i * 1.1, cx: i % 2 ? 16 : -16 });
  }

  /* ---------------- state and input ---------------- */
  const S = { x: L.spawn.x, z: L.spawn.z, level: 'ground', y: 0, yaw: L.spawn.yaw, pitch: -0.02, keys: new Set(), joy: { x: 0, y: 0 }, panel: null, map: false, near: null, time: 0, stats: null, locked: false, bob: 0 };
  const typing = (t) => t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName);
  addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === 'escape') { if (S.map) closeMap(); else if (S.panel) closePanel(); return; }
    if (typing(e.target) || S.panel) return;
    if (S.map) return;
    if (k === 'm') { e.preventDefault(); openMap(); return; }
    if ((k === 'e' || k === 'enter') && !e.repeat && !(k === 'enter' && /^(BUTTON|A)$/.test(e.target.tagName))) { e.preventDefault(); use(); return; }
    if ('wasd'.includes(k) || k.startsWith('arrow') || k === 'shift') { S.keys.add(k); e.preventDefault(); }
  });
  addEventListener('keyup', (e) => S.keys.delete(e.key.toLowerCase()));
  addEventListener('blur', () => S.keys.clear());
  canvas.addEventListener('click', () => { if (!S.panel && !S.map && canvas.requestPointerLock && matchMedia('(pointer:fine)').matches) canvas.requestPointerLock(); });
  document.addEventListener('pointerlockchange', () => { S.locked = document.pointerLockElement === canvas; el('c3-help').classList.toggle('dim', S.locked); });
  addEventListener('mousemove', (e) => { if (!S.locked) return; S.yaw -= e.movementX * 0.0022; S.pitch = Math.max(-1.2, Math.min(1.2, S.pitch - e.movementY * 0.0022)); });
  // drag to look when the pointer is not locked (touch, or before the first click)
  let drag = null;
  canvas.addEventListener('pointerdown', (e) => { if (!S.locked && e.pointerType !== 'mouse') drag = { id: e.pointerId, x: e.clientX, y: e.clientY }; });
  canvas.addEventListener('pointermove', (e) => { if (drag && e.pointerId === drag.id) { S.yaw -= (e.clientX - drag.x) * 0.005; S.pitch = Math.max(-1.2, Math.min(1.2, S.pitch - (e.clientY - drag.y) * 0.005)); drag.x = e.clientX; drag.y = e.clientY; } });
  canvas.addEventListener('pointerup', () => { drag = null; });
  const joy = el('c3-joy'); let joyId = null;
  const joyMove = (e) => { const r = joy.getBoundingClientRect(), dx = e.clientX - (r.left + 60), dy = e.clientY - (r.top + 60), d = Math.min(1, Math.hypot(dx, dy) / 50), a = Math.atan2(dy, dx); S.joy.x = d < 0.2 ? 0 : Math.cos(a) * d; S.joy.y = d < 0.2 ? 0 : Math.sin(a) * d; joy.firstElementChild.style.transform = `translate(${Math.cos(a) * d * 40}px,${Math.sin(a) * d * 40}px)`; };
  joy.addEventListener('pointerdown', (e) => { joyId = e.pointerId; joy.setPointerCapture(joyId); joyMove(e); });
  joy.addEventListener('pointermove', (e) => { if (e.pointerId === joyId) joyMove(e); });
  const joyEnd = () => { joyId = null; S.joy.x = S.joy.y = 0; joy.firstElementChild.style.transform = ''; };
  joy.addEventListener('pointerup', joyEnd); joy.addEventListener('pointercancel', joyEnd);
  el('c3-act').addEventListener('click', use);

  /* ---------------- interaction ---------------- */
  const dist = (u) => Math.hypot(S.x - u.x, S.z - u.z);
  function nearest() {
    if (S.panel || S.map) return null;
    if (S.level === 'ground') {
      if (!gate.open && dist(L.gate.use) < L.gate.use.r) return { kind: 'gate', label: 'Open the gate' };
      if (dist(L.guide.use) < L.guide.use.r) return { kind: 'guide', label: 'Talk to ' + L.guide.name };
      if (dist(L.board.use) < L.board.use.r) return { kind: 'board', label: 'Read the savings board' };
      if (P.onStairs(S.x, S.z) || (Math.abs(S.x) < 3 && S.z < -5.5 && S.z > -8.5)) return { kind: 'hint', label: 'Walk forward to climb the stairs' };
    } else {
      for (const d of L.doors) if (dist(d.use) < d.use.r) return { kind: 'door', id: d.id, label: 'Open the ' + d.label + ' door' };
    }
    return null;
  }
  function use() {
    const n = S.near; if (!n) return;
    if (n.kind === 'gate') openGate();
    else if (n.kind === 'guide') openPanel('guide');
    else if (n.kind === 'board') openPanel('board');
    else if (n.kind === 'door') openPanel(n.id);
  }
  function openGate() { if (gate.open) return; gate.open = true; sound([90, 70, 55], 0.25); }
  let closeHook = null;
  function openPanel(id) {
    if (S.panel) return;
    if (document.pointerLockElement) document.exitPointerLock();
    S.panel = id; S.keys.clear();
    const pb = el('c3-pbody'); pb.className = 'w-pb'; pb.removeAttribute('style'); pb.textContent = '';
    const t = { guide: L.guide.name, board: 'The savings board', dashboard: 'Dashboard', chat: "Chat: the Count's room", evals: 'Evals: tests and benchmarks' }[id] || id;
    el('c3-ptitle').textContent = t; el('c3-panel').hidden = false;
    const door = doors.find((q) => q.d.id === id); if (door) door.target = 1;
    closeHook = window.CastlePanels ? window.CastlePanels.open(id, pb, { stats: S.stats, guideName: L.guide.name }) : null;
    history.replaceState(null, '', '#' + id);
    el('c3-pclose').focus();
  }
  function closePanel() {
    if (!S.panel) return;
    if (typeof closeHook === 'function') closeHook(); closeHook = null;
    const door = doors.find((q) => q.d.id === S.panel); if (door) door.target = 0;
    el('c3-pbody').textContent = ''; el('c3-panel').hidden = true; S.panel = null;
    history.replaceState(null, '', location.pathname + location.search);
    canvas.focus();
  }
  el('c3-pclose').addEventListener('click', closePanel);

  /* ---------------- map (M) and travel ---------------- */
  function openMap() {
    if (S.panel) return;
    if (document.pointerLockElement) document.exitPointerLock();
    const groups = { ground: [], upper: [] };
    L.places.forEach((p) => groups[p.level].push(p));
    el('c3-mlist').innerHTML = [['ground', 'Ground floor: outside and the Great Hall'], ['upper', 'Upper gallery: the three doors']].map(([lv, name]) =>
      `<h3>${esc(name)}</h3><ul aria-label="${esc(name)}">` + groups[lv].map((p) => `<li><button type="button" data-place="${p.id}">${esc(p.name)}${['dashboard', 'chat', 'evals'].includes(p.id) ? '<small>go there and open it</small>' : ''}</button></li>`).join('') + '</ul>').join('');
    drawMap(el('c3-bigmap').getContext('2d'), 560, 380, true);
    el('c3-map').hidden = false; S.map = true; el('c3-mlist').querySelector('button').focus();
  }
  function closeMap() { el('c3-map').hidden = true; S.map = false; canvas.focus(); }
  el('c3-mapbtn').addEventListener('click', openMap); el('c3-mclose').addEventListener('click', closeMap);
  el('c3-mlist').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-place]'); if (!b) return;
    const p = L.places.find((q) => q.id === b.dataset.place); closeMap();
    fade(() => { teleport(p); if (['dashboard', 'chat', 'evals'].includes(p.id)) { gate.open = true; openPanel(p.id); } });
  });
  function teleport(p) { S.x = p.x; S.z = p.z; S.level = p.level; S.yaw = p.yaw || 0; S.pitch = -0.05; S.y = P.floorY(S.x, S.z, S.level); if (p.z < 0) gate.open = true; }
  function fade(fn) { const f = el('c3-fade'); f.classList.add('on'); setTimeout(() => { fn(); setTimeout(() => f.classList.remove('on'), 120); }, 200); }

  /* minimap: top-down, the floor you are on, doors and stairs, the player dot (kept from the 2D castle) */
  const mini = el('c3-mini').getContext('2d');
  function drawMap(g, W, H, big) {
    g.clearRect(0, 0, W, H); g.fillStyle = 'rgba(11,5,16,.9)'; g.fillRect(0, 0, W, H);
    if (!big) { // the corner map follows you (about 40 m across) so the hall stays readable
      const span = 40 * W / H;
      plan(g, 0, 0, W, H, S.level, S.x - span / 2, S.x + span / 2, S.z - 20, S.z + 20, false);
      g.fillStyle = 'rgba(11,5,16,.8)'; g.fillRect(0, 0, W, 18); g.fillStyle = '#e9c46a'; g.textAlign = 'left'; g.font = '600 10px Inter, sans-serif';
      g.fillText(S.level === 'upper' ? 'Upper gallery' : (S.z > 0 ? 'Outside' : 'Ground floor'), 6, 13);
      return;
    }
    // the full map: both floors side by side
    plan(g, 0, 18, W * 0.56, H - 18, 'ground', -32, 32, -31, 41, true);
    plan(g, W * 0.58, 18, W * 0.42, H - 18, 'upper', -16, 16, -31, -1, true);
    g.fillStyle = '#e9c46a'; g.textAlign = 'left'; g.font = '700 12px Inter, sans-serif';
    g.fillText('Ground: outside and the Great Hall', 6, 13); g.fillText('Upper gallery', W * 0.58 + 6, 13);
  }
  function plan(g, ox0, oy0, W, H, lv, x0, x1, z0, z1, big) {
    const s = Math.min(W / (x1 - x0), H / (z1 - z0)), ox = ox0 + (W - (x1 - x0) * s) / 2, oz = oy0 + (H - (z1 - z0) * s) / 2;
    const X = (x) => ox + (x - x0) * s, Z = (z) => oz + (z - z0) * s;
    g.save(); g.beginPath(); g.rect(ox0, oy0, W, H); g.clip();
    L.zones.forEach((q) => { if (q.level !== lv && !(lv === 'upper' && q.id === 'hall')) return; g.fillStyle = q.level === lv ? (q.id === 'courtyard' ? '#3e4a3a' : '#5a4a68') : '#2a2032'; g.fillRect(X(q.x0), Z(q.z0), (q.x1 - q.x0) * s, (q.z1 - q.z0) * s); });
    g.fillStyle = '#e9c46a'; g.fillRect(X(st.x0), Z(st.z0), (st.x1 - st.x0) * s, (st.z1 - st.z0) * s);
    g.fillStyle = '#2a1636';
    L.walls.forEach((w) => { if (w.kind === 'hidden') return; if (w.level !== 'both' && w.level !== lv) return; g.fillRect(X(w.x0), Z(w.z0), Math.max(1.5, (w.x1 - w.x0) * s), Math.max(1.5, (w.z1 - w.z0) * s)); });
    if (lv === 'ground' && !gate.open) { g.fillStyle = '#c08a3a'; g.fillRect(X(L.gate.x0), Z(L.gate.z0), (L.gate.x1 - L.gate.x0) * s, Math.max(3, 1.5 * s)); }
    g.textAlign = 'center'; g.font = `600 ${big ? 11 : 9}px Inter, sans-serif`;
    if (lv === 'upper') L.doors.forEach((d) => { g.fillStyle = '#ff6a8a'; g.fillRect(X(d.x - 1.2), Z(d.z) - 2, 2.4 * s, 5); g.fillStyle = '#ffd0d8'; g.fillText(d.label, X(d.x), Z(d.z) + (big ? 20 : 14)); });
    else {
      g.fillStyle = '#ffffff'; g.beginPath(); g.arc(X(L.guide.x), Z(L.guide.z), big ? 4 : 2.5, 0, 7); g.fill();
      g.fillStyle = '#7ad0ff'; g.fillRect(X(L.board.x) - 1, Z(L.board.z - 3), 3, 6 * s);
      if (big) { g.fillStyle = '#ffd0d8'; g.fillText('Guide', X(L.guide.x), Z(L.guide.z) - 8); g.fillText('Gate', X(0), Z(3.5)); g.textAlign = 'left'; g.fillText('Savings board', X(-14), Z(-11)); g.textAlign = 'center'; }
    }
    if (big) { g.fillStyle = '#1a0d1e'; g.fillText('Stairs', X(0), Z(-12.5)); }
    if (S.level === lv) { // player
      g.save(); g.translate(X(S.x), Z(S.z)); g.rotate(-S.yaw);
      g.fillStyle = '#6ee7a0'; g.beginPath(); g.moveTo(0, -7); g.lineTo(4.5, 4); g.lineTo(-4.5, 4); g.closePath(); g.fill(); g.restore();
    }
    g.restore();
  }

  /* ---------------- sound (tiny WebAudio blips) ---------------- */
  let ac = null;
  function sound(freqs, vol) { try { ac = ac || new (window.AudioContext || window.webkitAudioContext)(); freqs.forEach((f, i) => { const o = ac.createOscillator(), gn = ac.createGain(); o.type = 'sawtooth'; o.frequency.value = f; gn.gain.setValueAtTime(vol * 0.2, ac.currentTime + i * 0.15); gn.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + i * 0.15 + 0.4); o.connect(gn); gn.connect(ac.destination); o.start(ac.currentTime + i * 0.15); o.stop(ac.currentTime + i * 0.15 + 0.45); }); } catch (e) { /* audio waits for a gesture */ } }

  /* ---------------- loop (never paused) ---------------- */
  function resize() { const w = root.clientWidth, h = root.clientHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
  addEventListener('resize', resize); resize();
  let last = performance.now(), fpsN = 0, fpsT = 0;
  const fpsLog = [];
  function step(dt) {
    let f = 0, r = 0; const k = S.keys;
    if (k.has('w') || k.has('arrowup')) f += 1; if (k.has('s') || k.has('arrowdown')) f -= 1;
    if (k.has('d') || k.has('arrowright')) r += 1; if (k.has('a') || k.has('arrowleft')) r -= 1;
    f -= S.joy.y; r += S.joy.x;
    const m = Math.hypot(f, r);
    if (m > 0.05 && !S.panel && !S.map) {
      f /= Math.max(1, m); r /= Math.max(1, m);
      const sp = (k.has('shift') ? 7.5 : 4.2) * dt, sy = Math.sin(S.yaw), cy = Math.cos(S.yaw);
      const dx = (-sy * f + cy * r) * sp, dz = (-cy * f - sy * r) * sp;
      const q = P.move({ x: S.x, z: S.z, level: S.level }, dx, dz, gate.open);
      S.x = q.x; S.z = q.z; S.level = q.level; S.bob += sp * 2.2;
    }
    const fy = P.floorY(S.x, S.z, S.level);
    S.y += (fy - S.y) * Math.min(1, dt * 12);
  }
  function animate(t, dt) {
    for (const f of fires) { const ph = f.userData.ph || 0, s = 0.85 + Math.sin(t * 13 + ph) * 0.1 + Math.sin(t * 29 + ph * 3) * 0.08; f.scale.set(1, s, 1); }
    torchLights.forEach((l, i) => { l.intensity = (l.userData.base || (l.userData.base = l.intensity)) * (0.85 + Math.sin(t * 9 + i * 2) * 0.1 + Math.sin(t * 23 + i) * 0.05); });
    for (const fl of flags) { const a = fl.mesh.geometry.attributes.position; for (let i = 0; i < a.count; i++) { const x = fl.base[i * 3]; a.array[i * 3 + 2] = Math.sin(x * 2.2 - t * 5) * 0.18 * (x / 2.4); } a.needsUpdate = true; }
    for (const b of banners) { const a = b.mesh.geometry.attributes.position; for (let i = 0; i < a.count; i++) { const y = b.base[i * 3 + 1]; a.array[i * 3 + 2] = Math.sin(y * 1.6 + t * 1.3) * 0.05 * (1.8 - y) ; } a.needsUpdate = true; }
    clouds.forEach((c, i) => { c.position.x += dt * (1.5 + i * 0.2); if (c.position.x > 200) c.position.x = -200; });
    bats.forEach((b) => { const a = t * b.s + b.o; b.g.position.set(b.cx + Math.cos(a) * b.r, b.h + Math.sin(a * 2) * 1.5, 0 + Math.sin(a) * b.r); b.g.rotation.y = -a; const fl = Math.sin(t * 16 + b.o) * 0.9; b.wl.rotation.z = fl; b.wr.rotation.z = -fl; });
    chand.rotation.y = Math.sin(t * 0.3) * 0.05;
    // gate leaves swing open, door leaves open while their panel is up
    gate.t += ((gate.open ? 1 : 0) - gate.t) * Math.min(1, dt * 1.6);
    leaves[0].rotation.y = -gate.t * 1.75; leaves[1].rotation.y = gate.t * 1.75;
    doors.forEach((q) => { const near = S.level === 'upper' && Math.hypot(S.x - q.d.use.x, S.z - q.d.use.z) < 3.2; const tg = q.target || (near ? 0.25 : 0); q.open += (tg - q.open) * Math.min(1, dt * 4); q.hinge.rotation.y = -q.open * 1.6; q.glow.material.opacity = q.open * 0.9; });
    // the guide idles: breathing, looks at you when you are close
    torso.scale.y = 1 + Math.sin(t * 2) * 0.015; arms.forEach((a, i) => { a.rotation.x = Math.sin(t * 1.4 + i) * 0.08; });
    const look = S.level === 'ground' && Math.hypot(S.x - G.x, S.z - G.z) < 12 ? Math.atan2(S.x - G.x, S.z - G.z) : Math.sin(t * 0.5) * 0.4;
    head.rotation.y += (Math.max(-1, Math.min(1, look)) - head.rotation.y) * Math.min(1, dt * 3);
    head.rotation.x = Math.sin(t * 0.9) * 0.04;
  }
  fires.forEach((f, i) => { f.userData.ph = i * 1.7; });
  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000); last = now; S.time += dt;
    step(dt); animate(S.time, dt);
    camera.position.set(S.x, S.y + L.eye + Math.sin(S.bob) * 0.04, S.z);
    camera.rotation.set(S.pitch, S.yaw, 0, 'YXZ');
    renderer.render(scene, camera);
    S.near = nearest();
    const pr = el('c3-prompt'); if (S.near) { pr.innerHTML = `<kbd>E</kbd> ${esc(S.near.label)}`; pr.classList.add('on'); } else pr.classList.remove('on');
    el('c3-where').textContent = P.zoneName(S.x, S.z, S.level);
    drawMap(mini, 200, 150, false);
    fpsN++; fpsT += dt; if (fpsT >= 1) { const fps = fpsN / fpsT; fpsLog.push(fps); if (fpsLog.length > 120) fpsLog.shift(); el('c3-fps').textContent = fps.toFixed(0) + ' fps'; fpsN = 0; fpsT = 0; }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
  refreshStats(); setInterval(refreshStats, 10000);

  // deep links (#dashboard, #chat, #evals, #guide, and the old #live, #evals, #walk/<room>)
  const OLD = { live: 'dashboard', observatory: 'dashboard', bench: 'evals', ledger: 'evals', agent: 'chat', how: 'dashboard' };
  const h = location.hash.replace(/^#(walk\/|room\/|r-)?/, ''), want = OLD[h] || h;
  const place = L.places.find((p) => p.id === want);
  if (place) setTimeout(() => { teleport(place); if (['dashboard', 'chat', 'evals'].includes(want)) openPanel(want); else if (want === 'guide') openPanel('guide'); }, 300);

  const api = {
    state: S, layout: L, gate, openGate, openPanel, closePanel, openMap, closeMap, teleport, use,
    hold(k, on) { on ? S.keys.add(k) : S.keys.delete(k); }, look(yaw, pitch) { S.yaw = yaw; if (pitch != null) S.pitch = pitch; },
    fps() { return fpsLog.slice(); }, renderer,
  };
  window.Castle3D = api;
  return api;
}
