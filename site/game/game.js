/* CHIMERA, the painted game. Scene 1: outside the castle.
   The painted landing (site/art/gate.webp) is cut into depth layers (scripts/cut_layers.py): the plate, the gate
   posts and the two iron-gate leaves. Walking forward (W) scales each layer by its own depth, so the castle grows
   slowly while the gates rush past. E opens the gates. One canvas, one requestAnimationFrame loop, never paused. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const img = (src) => new Promise((ok) => { const i = new Image(); i.onload = () => ok(i); i.onerror = () => ok(null); i.src = src; });
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const rnd = (() => { let s = 9; return () => ((s = (s * 16807) % 2147483647) / 2147483647); })();

  async function start(root, opts = {}) {
    const base = opts.base || 'game/';
    const art = opts.art || 'art/';
    const [plate, leafL, leafR, postL, postR, player, count] = await Promise.all([
      img(base + 'layers/plate.webp'), img(base + 'layers/leaf-l.png'), img(base + 'layers/leaf-r.png'),
      img(base + 'layers/post-l.png'), img(base + 'layers/post-r.png'), img((opts.site || '') + 'world/player.png'), img(base + 'layers/count.png')]);
    const boxes = await (await fetch(base + 'layers/boxes.json')).json();
    if (!plate) throw new Error('plate missing');

    root.innerHTML = `<canvas id="g-cv" tabindex="0" aria-label="The castle game. W walks forward, A and D step sideways, E opens doors and gates, M shows the map."></canvas>
      <div class="g-bar"><span id="g-where">Outside the castle</span><span id="g-fps" class="g-fps"></span></div>
      <div class="g-prompt" id="g-prompt"></div>
      <div class="g-say" id="g-say"><b>Count Cuspid</b><span id="g-saytext">Good evening. Walk up with W. Press E at the gates.</span></div>
      <canvas id="g-mini" width="170" height="130" aria-hidden="true"></canvas>
      <div class="g-help"><kbd>W</kbd> walk in · <kbd>A</kbd><kbd>D</kbd> step aside · <kbd>Shift</kbd> run · <kbd>E</kbd> open · <kbd>Enter</kbd> walk on · <kbd>M</kbd> map</div>`;
    const cv = $('g-cv'), g = cv.getContext('2d');
    const mini = $('g-mini').getContext('2d');
    const IW = plate.naturalWidth, IH = plate.naturalHeight;

    /* ---------- state ---------- */
    const GATE_Z = 0.16, END_Z = 0.92;
    const S = { z: 0, x: 0, keys: new Set(), gate: 0, gateOpen: false, auto: false, t: 0, walk: 0, moving: false, fps: [] };
    let W = 0, H = 0, cover = 1;
    function resize() {
      const k = Math.min(window.devicePixelRatio || 1, opts.maxDpr || 1);
      W = cv.width = Math.round(root.clientWidth * k); H = cv.height = Math.round(root.clientHeight * k);
      cover = Math.max(W / IW, H / IH) * 1.04;
    }
    addEventListener('resize', resize); resize();

    /* ---------- the camera: one focus point on the castle, each layer has its own depth ---------- */
    const F = { u: 0.45, v: 0.56 };              // where you walk to: the castle under the cliff
    const C0 = () => ({ x: W / 2 + (F.u - 0.5) * IW * cover, y: H / 2 + (F.v - 0.5) * IH * cover });
    const scaleOf = (k) => 1 + S.z * k;          // k: how fast this layer grows as you walk in
    function toScreen(u, v, k, par) {           // image fraction -> screen pixel for a layer
      const c = C0(), s = scaleOf(k);
      return { x: c.x + (u - F.u) * IW * cover * s - S.x * W * par, y: c.y + (v - F.v) * IH * cover * s, s };
    }
    function drawLayer(im, u0, v0, k, par, alpha = 1) {
      const p = toScreen(u0, v0, k, par), w = im.naturalWidth * cover * p.s, h = im.naturalHeight * cover * p.s;
      if (alpha < 1) g.globalAlpha = alpha;
      g.drawImage(im, p.x, p.y, w, h); g.globalAlpha = 1;
      return { x: p.x, y: p.y, w, h };
    }

    /* ---------- bats: a real flock in three depths ---------- */
    const moonUV = { u: 0.622, v: 0.238 };
    const bats = [];
    for (let i = 0; i < 110; i++) {
      const depth = i < 70 ? 0 : i < 98 ? 1 : 2;                    // far, mid, near
      bats.push({
        depth, size: [5 + rnd() * 4, 11 + rnd() * 7, 26 + rnd() * 22][depth],
        r: [0.05 + rnd() * 0.22, 0.12 + rnd() * 0.3, 0.2 + rnd() * 0.4][depth], a: rnd() * 6.3,
        w: (rnd() > 0.5 ? 1 : -1) * [0.18 + rnd() * 0.25, 0.12 + rnd() * 0.18, 0.08 + rnd() * 0.1][depth],
        e: 0.35 + rnd() * 0.5, wob: rnd() * 6.3, flap: 9 + rnd() * 7, ph: rnd() * 6.3,
        cx: (rnd() - 0.5) * [0.3, 0.7, 1.2][depth], cy: (rnd() - 0.5) * [0.18, 0.3, 0.4][depth],
      });
    }
    function drawBat(x, y, s, flap, alpha, tilt) {
      const f = Math.sin(flap), up = f * 0.9;
      g.save(); g.translate(x, y); g.rotate(tilt); g.scale(s / 30, s / 30);
      g.globalAlpha = alpha; g.fillStyle = '#0c0410';
      g.beginPath();
      g.moveTo(0, -2);
      g.quadraticCurveTo(-8, -10 - up * 12, -30, -6 - up * 16);       // left wing tip
      g.quadraticCurveTo(-22, -1, -20, 4); g.quadraticCurveTo(-14, 0, -11, 6); g.quadraticCurveTo(-6, 2, -3, 7);
      g.lineTo(3, 7); g.quadraticCurveTo(6, 2, 11, 6); g.quadraticCurveTo(14, 0, 20, 4);
      g.quadraticCurveTo(22, -1, 30, -6 - up * 16);
      g.quadraticCurveTo(8, -10 - up * 12, 0, -2);
      g.fill();
      g.beginPath(); g.ellipse(0, 1, 3.4, 6, 0, 0, 7); g.fill();
      g.beginPath(); g.moveTo(-2.6, -3.5); g.lineTo(-1.8, -8); g.lineTo(-0.4, -4); g.lineTo(0.4, -4); g.lineTo(1.8, -8); g.lineTo(2.6, -3.5); g.fill();
      g.restore(); g.globalAlpha = 1;
    }
    function drawBats(layer) {
      const m = toScreen(moonUV.u, moonUV.v, 0.35, 0.15), R = Math.min(W, H);
      for (const b of bats) {
        if (b.depth !== layer) continue;
        const a = b.a + S.t * b.w, wob = Math.sin(S.t * 0.7 + b.wob);
        const x = m.x + (b.cx + Math.cos(a) * b.r * (1 + 0.25 * wob)) * R * 1.1 - S.x * W * [0.1, 0.3, 0.8][b.depth];
        const y = m.y + (b.cy + Math.sin(a) * b.r * b.e + Math.sin(S.t * 1.3 + b.ph) * 0.02) * R;
        const sz = b.size * (R / 900) * (1 + S.z * [0.3, 0.8, 1.6][b.depth]);
        drawBat(x, y, sz, S.t * b.flap + b.ph, [0.55, 0.8, 0.95][b.depth], Math.cos(a) * 0.3 * Math.sign(b.w));
      }
    }

    /* ---------- fog, fireflies, candles ---------- */
    const fogSprite = (() => { const c = document.createElement('canvas'); c.width = c.height = 256; const x = c.getContext('2d'); const r = x.createRadialGradient(128, 128, 0, 128, 128, 128); r.addColorStop(0, 'rgba(190,160,220,.32)'); r.addColorStop(1, 'rgba(190,160,220,0)'); x.fillStyle = r; x.fillRect(0, 0, 256, 256); return c; })();
    const glowSprite = (() => { const c = document.createElement('canvas'); c.width = c.height = 128; const x = c.getContext('2d'); const r = x.createRadialGradient(64, 64, 0, 64, 64, 64); r.addColorStop(0, 'rgba(255,214,140,1)'); r.addColorStop(0.25, 'rgba(255,160,70,.55)'); r.addColorStop(1, 'rgba(255,120,40,0)'); x.fillStyle = r; x.fillRect(0, 0, 128, 128); return c; })();
    const fogs = Array.from({ length: 9 }, (_, i) => ({ u: rnd(), v: 0.62 + rnd() * 0.26, s: 0.5 + rnd() * 0.7, sp: (0.004 + rnd() * 0.01) * (i % 2 ? 1 : -1), k: 1.2 + rnd() * 2.5 }));
    const flies = Array.from({ length: 46 }, () => ({ u: 0.15 + rnd() * 0.7, v: 0.6 + rnd() * 0.3, ph: rnd() * 6.3, sp: 0.4 + rnd() }));
    const candles = [ // image fractions of the painted candles; the posts' candles ride on the post layer
      { u: 0.107, v: 0.674, post: 'l' }, { u: 0.124, v: 0.682, post: 'l' }, { u: 0.33, v: 0.766 }, { u: 0.352, v: 0.83 },
      { u: 0.728, v: 0.764 }, { u: 0.783, v: 0.752 }, { u: 0.9, v: 0.736, post: 'r' }, { u: 0.935, v: 0.703, post: 'r' }];

    /* ---------- the drive: lanterns on posts along a stone path, past the gates ---------- */
    const lanterns = [];
    for (let i = 0; i < 9; i++) for (const side of [-1, 1]) lanterns.push({ d: 0.26 + i * 0.085, side });
    function drawDrive() {
      if (S.z < GATE_Z - 0.06) return;
      const c = C0(), horizon = c.y - H * 0.02, foot = H * 1.02;
      // path: a soft stone strip into the distance
      const near = W * 0.3, far = W * 0.012 * scaleOf(1.2);
      const grd = g.createLinearGradient(0, horizon, 0, foot); grd.addColorStop(0, 'rgba(70,58,80,.0)'); grd.addColorStop(0.4, 'rgba(60,48,70,.18)'); grd.addColorStop(1, 'rgba(40,30,46,.4)');
      g.fillStyle = grd; g.beginPath(); g.moveTo(c.x - far - S.x * W * 0.2, horizon); g.lineTo(c.x + far - S.x * W * 0.2, horizon); g.lineTo(W / 2 + near - S.x * W, foot); g.lineTo(W / 2 - near - S.x * W, foot); g.fill();
      // lanterns, far ones first
      const list = lanterns.map((L) => ({ L, rel: L.d - S.z })).filter((o) => o.rel > 0.012).sort((a, b) => b.rel - a.rel);
      for (const { L, rel } of list) {
        const p = 0.05 / rel;                                   // perspective size
        const x = c.x + L.side * W * 0.11 * p - S.x * W * Math.min(1, p * 0.6), y = horizon + (foot - horizon) * Math.min(1.4, p * 0.33);
        const h = H * 0.11 * p, w = Math.max(1.5, h * 0.05);
        if (y - h > H || x < -h || x > W + h) continue;
        g.fillStyle = '#0a0410'; g.fillRect(x - w / 2, y - h, w, h); g.fillRect(x - w * 2, y - h - w * 3, w * 4, w * 3.2);
        const fl = 0.75 + 0.18 * Math.sin(S.t * 9 + L.d * 40) + 0.07 * Math.sin(S.t * 23 + L.d * 9);
        g.globalCompositeOperation = 'lighter'; const r = h * 0.55 * fl; g.drawImage(glowSprite, x - r, y - h - w * 1.5 - r, r * 2, r * 2); g.globalCompositeOperation = 'source-over';
      }
    }

    /* ---------- the gates ---------- */
    function drawPost(im, key) {
      const b = boxes.boxes[key];
      return drawLayer(im, b[0], b[1], 5.5, 1);
    }
    function drawLeaf(im, key, side) {
      const b = boxes.boxes[key], p = toScreen(b[0], b[1], 5.5, 1), w = im.naturalWidth * cover * p.s, h = im.naturalHeight * cover * p.s;
      const t = S.gate, hingeX = side < 0 ? p.x : p.x + w;
      const sx = Math.max(0.12, Math.cos(t * 1.35));             // the leaf turns on its hinge toward you
      g.save(); g.translate(hingeX, p.y + h); g.scale(sx, 1 + t * 0.12);
      g.drawImage(im, side < 0 ? 0 : -w, -h, w, h); g.restore();
    }

    /* ---------- the player: a small cloaked figure seen from behind ---------- */
    function drawPlayer() {
      const h = H * 0.2, w = h * 0.75, x = W / 2 - w / 2, y = H - h * 1.02 + Math.abs(Math.sin(S.walk * 2)) * (S.moving ? h * 0.02 : 0);
      g.fillStyle = 'rgba(0,0,0,.35)'; g.beginPath(); g.ellipse(W / 2, H - h * 0.06, w * 0.38, h * 0.05, 0, 0, 7); g.fill();
      if (player) { const fr = S.moving ? Math.floor(S.walk * 4) % 4 : 1; g.filter = 'brightness(.75) saturate(1.2)'; g.drawImage(player, fr * 48, 64, 48, 64, x, y, w, h); g.filter = 'none'; }
      g.globalCompositeOperation = 'lighter'; g.globalAlpha = 0.25; g.drawImage(glowSprite, W / 2 - w * 0.6, y - h * 0.2, w * 1.2, w * 1.2); g.globalAlpha = 1; g.globalCompositeOperation = 'source-over';
    }

    /* ---------- the Count walks a little ahead of you on the left ---------- */
    function drawCount() {
      if (!count) return;
      const h = H * 0.36, w = h * 0.75, x = W * 0.04 - S.x * W * 0.3, y = H - h + Math.sin(S.t * 1.6) * h * 0.006;
      g.save(); g.globalAlpha = 0.97; g.drawImage(count, x, y, w, h); g.restore();
    }

    /* ---------- sound ---------- */
    let ac = null;
    function creak() {
      try {
        ac = ac || new (window.AudioContext || window.webkitAudioContext)();
        const o = ac.createOscillator(), f = ac.createBiquadFilter(), v = ac.createGain();
        o.type = 'sawtooth'; o.frequency.setValueAtTime(70, ac.currentTime); o.frequency.linearRampToValueAtTime(140, ac.currentTime + 0.6); o.frequency.linearRampToValueAtTime(55, ac.currentTime + 1.6);
        f.type = 'bandpass'; f.frequency.value = 600; f.Q.value = 8;
        v.gain.setValueAtTime(0.0001, ac.currentTime); v.gain.exponentialRampToValueAtTime(0.12, ac.currentTime + 0.2); v.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + 1.8);
        o.connect(f); f.connect(v); v.connect(ac.destination); o.start(); o.stop(ac.currentTime + 1.9);
      } catch (e) { /* sound waits for a key press */ }
    }

    /* ---------- input ---------- */
    addEventListener('keydown', (e) => {
      const k = e.key.toLowerCase();
      if ('wasd'.includes(k) || k.startsWith('arrow') || k === 'shift') { S.keys.add(k); e.preventDefault(); S.auto = false; }
      if ((k === 'e' || k === 'enter') && !e.repeat) { e.preventDefault(); use(k === 'enter'); }
    });
    addEventListener('keyup', (e) => S.keys.delete(e.key.toLowerCase()));
    addEventListener('blur', () => S.keys.clear());
    function nearGate() { return !S.gateOpen && S.z > GATE_Z - 0.09; }
    function use(enter) {
      if (nearGate()) { S.gateOpen = true; creak(); say('The gates know me. Follow the lanterns up the drive.'); return; }
      if (enter && S.gateOpen) { S.auto = true; return; }
      if (enter && !S.gateOpen) { S.auto = true; }
    }
    function say(t) { $('g-saytext').textContent = t; }

    /* ---------- minimap ---------- */
    function drawMini() {
      const m = mini, w = 170, h = 130;
      m.clearRect(0, 0, w, h); m.fillStyle = 'rgba(11,5,16,.86)'; m.fillRect(0, 0, w, h);
      m.fillStyle = '#e9c46a'; m.font = '600 10px Inter, sans-serif'; m.fillText('Outside the castle', 8, 14);
      const x = w / 2, y0 = h - 16, y1 = 30;
      m.strokeStyle = '#6a5a78'; m.lineWidth = 10; m.beginPath(); m.moveTo(x, y0); m.lineTo(x, y1); m.stroke();
      const gy = y0 - (y0 - y1) * (GATE_Z / END_Z);
      m.fillStyle = S.gateOpen ? '#6a5a78' : '#c08a3a'; m.fillRect(x - 16, gy - 2, 32, 4);
      m.fillStyle = '#ffd27a'; m.fillRect(x - 9, y1 - 8, 18, 8);
      m.fillStyle = '#d9c9e0'; m.font = '9px Inter, sans-serif'; m.textAlign = 'left';
      m.fillText('gates', x + 20, gy + 3); m.fillText('door', x + 14, y1 - 2); m.fillText('drive', x + 10, (gy + y1) / 2);
      const py = y0 - (y0 - y1) * (S.z / END_Z);
      m.fillStyle = '#6ee7a0'; m.beginPath(); m.arc(x + S.x * 60, py, 4 + Math.sin(S.t * 6) * 0.8, 0, 7); m.fill(); m.textAlign = 'start';
    }

    /* ---------- the loop ---------- */
    let last = performance.now(), fN = 0, fT = 0;
    function frame(now) {
      const dt = Math.min(0.05, (now - last) / 1000); last = now; S.t += dt;
      const k = S.keys, run = k.has('shift') ? 1.9 : 1;
      let f = (k.has('w') || k.has('arrowup') ? 1 : 0) - (k.has('s') || k.has('arrowdown') ? 1 : 0);
      if (S.auto) f = 1;
      const side = (k.has('d') || k.has('arrowright') ? 1 : 0) - (k.has('a') || k.has('arrowleft') ? 1 : 0);
      const limit = S.gateOpen ? END_Z : GATE_Z - 0.05;
      const nz = clamp(S.z + f * dt * 0.075 * run, 0, limit);
      S.moving = nz !== S.z || side !== 0; S.z = nz; if (S.z >= END_Z - 0.001) S.auto = false;
      if (!S.gateOpen && S.auto && S.z >= limit - 0.001) { S.auto = false; }
      S.x = clamp(S.x + side * dt * 0.15, -0.12, 0.12); if (S.moving) S.walk += dt * 2.2 * run;
      if (S.gateOpen) S.gate = Math.min(1, S.gate + dt * 0.55);

      g.fillStyle = '#12061c'; g.fillRect(0, 0, W, H);
      drawLayer(plate, 0, 0, 1.25, 0.25);                     // sky, moon, castle, cliff, trees, ground
      drawBats(0); drawBats(1);
      for (const c of candles) if (!c.post) candle(c, 1.25, 0.25);
      fogs.forEach((o) => { o.u = (o.u + o.sp * dt + 1.4) % 1.4 - 0.2; const p = toScreen(o.u, o.v, o.k, 0.6), r = W * 0.35 * o.s * p.s; g.drawImage(fogSprite, p.x - r, p.y - r * 0.4, r * 2, r * 0.8); });
      drawDrive();
      if (S.z < GATE_Z + 0.2) { drawLeaf(leafL, 'leaf-l', -1); drawLeaf(leafR, 'leaf-r', 1); drawPost(postL, 'post-l'); drawPost(postR, 'post-r'); for (const c of candles) if (c.post) candle(c, 5.5, 1); }
      g.globalCompositeOperation = 'lighter';
      flies.forEach((o) => { const p = toScreen(o.u + Math.sin(S.t * 0.3 * o.sp + o.ph) * 0.03, o.v + Math.cos(S.t * 0.4 * o.sp + o.ph) * 0.02, 2.2, 0.8); const a = 0.4 + 0.6 * Math.max(0, Math.sin(S.t * 2 * o.sp + o.ph)), r = 6 * p.s * (H / 900); g.globalAlpha = a; g.drawImage(glowSprite, p.x - r, p.y - r, r * 2, r * 2); });
      g.globalAlpha = 1; g.globalCompositeOperation = 'source-over';
      drawBats(2);
      drawCount(); drawPlayer();
      // vignette
      const vg = g.createRadialGradient(W / 2, H / 2, H * 0.35, W / 2, H / 2, H * 0.95); vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, 'rgba(6,2,12,.55)'); g.fillStyle = vg; g.fillRect(0, 0, W, H);

      const pr = $('g-prompt');
      if (nearGate()) { pr.innerHTML = '<kbd>E</kbd> Open the iron gates'; pr.classList.add('on'); }
      else if (S.gateOpen && S.z < END_Z - 0.01 && !S.moving) { pr.innerHTML = '<kbd>W</kbd> walk up the drive · <kbd>Enter</kbd> walk on by itself'; pr.classList.add('on'); }
      else if (S.z >= END_Z - 0.01) { pr.innerHTML = 'The great door: the hall is next'; pr.classList.add('on'); }
      else pr.classList.remove('on');
      $('g-where').textContent = S.z < GATE_Z ? 'Before the iron gates' : S.z < END_Z - 0.01 ? 'The lantern drive' : 'Before the great door';
      drawMini();
      fN++; fT += dt; if (fT >= 1) { S.fps.push(fN / fT); if (S.fps.length > 120) S.fps.shift(); $('g-fps').textContent = Math.round(fN / fT) + ' fps'; fN = 0; fT = 0; }
      requestAnimationFrame(frame);
    }
    function candle(c, k, par) {
      const p = toScreen(c.u, c.v, k, par), fl = 0.7 + 0.2 * Math.sin(S.t * 11 + c.u * 50) + 0.1 * Math.sin(S.t * 27 + c.v * 30), r = H * 0.035 * p.s * fl;
      g.globalCompositeOperation = 'lighter'; g.globalAlpha = 0.75; g.drawImage(glowSprite, p.x - r, p.y - r, r * 2, r * 2); g.globalAlpha = 1; g.globalCompositeOperation = 'source-over';
    }
    requestAnimationFrame(frame);
    cv.focus();
    const api = { state: S, use, fps: () => S.fps.slice() };
    window.CastleGame = api;
    return api;
  }
  window.CastleGameStart = start;
})();
