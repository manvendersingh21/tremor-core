/* Walkable castle engine: canvas 2D, no library. Data in map.json, posters from rooms.js (window.ROOMS).
   Motion never pauses: the loop keeps running behind panels, in hidden tabs' next frame, and with reduced motion. */
(function () {
  'use strict';
  const G = window.CastleGrid;
  const TS = 40;                        // tile size in world px
  const VIEW_ROWS = 15;               // tiles visible vertically
  const $ = (s, r) => (r || document).querySelector(s);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const hash = (x, y, s) => { let h = (x * 374761393 + y * 668265263 + (s || 0) * 2147483647) | 0; h = (h ^ (h >>> 13)) * 1274126177; return ((h ^ (h >>> 16)) >>> 0) / 4294967295; };
  const img = (src) => { const i = new Image(); i.src = src; return i; };
  const BASE = 'https://github.com/manvendersingh21/tremor-core/blob/dev/';

  async function start(root, opts) {
    opts = opts || {};
    const base = opts.base || 'world/';
    const map = await (await fetch(base + 'map.json')).json();
    const art = (n) => (opts.artBase || 'art/') + n;
    const ROOMS = window.ROOMS || [];
    const rooms = map.rooms;
    const floors = map.floors;
    const assets = {
      player: img(base + 'player.png'), count: img(base + 'count.png'),
      door: img(art('door.webp')), bg: floors.map((f) => img((opts.artBase ? opts.artBase.replace(/art\/$/, '') : '') + f.bg)),
      room: {}, hall: img(art('hall-1024.webp')),
    };
    Object.keys(rooms).forEach((id) => { assets.room[id] = img(art(artFor(id) + '-1024.webp')); });
    function artFor(id) { const r = ROOMS.find((x) => x.id === (rooms[id].ref || id)); return (r && r.art) || rooms[id].art; }

    root.classList.add('w-root');
    root.innerHTML = `
      <canvas class="w-main" aria-hidden="true"></canvas>
      <div class="w-bar"><span class="w-floor" id="w-floor"></span>
        <button class="w-btn" id="w-skip" type="button" aria-haspopup="dialog">Skip the walk (M)</button>
        <button class="w-btn" id="w-snd" type="button" aria-pressed="true">Sound on</button></div>
      <canvas class="w-mini" width="168" height="110" aria-hidden="true"></canvas>
      <div class="w-help"><kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd> move &nbsp;<kbd>Shift</kbd> run &nbsp;<kbd>E</kbd> use &nbsp;<kbd>M</kbd> rooms &nbsp;<kbd>Esc</kbd> leave a room</div>
      <div class="w-prompt" id="w-prompt" aria-live="polite"></div>
      <div class="w-say" id="w-say" hidden role="status"></div>
      <div class="w-joy" id="w-joy"><i></i></div><button class="w-act" id="w-act" type="button" aria-label="Use">E</button>
      <section class="w-panel" id="w-panel" role="dialog" aria-modal="true" aria-labelledby="w-ptitle" hidden>
        <div class="w-ph"><h2 id="w-ptitle"></h2><button class="w-btn" id="w-pclose" type="button">Leave the room (Esc)</button></div>
        <div class="w-pb" id="w-pbody"></div></section>
      <div class="w-travel" id="w-travel" hidden><div role="dialog" aria-modal="true" aria-labelledby="w-ttitle"><h2 id="w-ttitle">Go to a room</h2><p style="margin:.2rem 0 .4rem;font:.85rem Inter,sans-serif;color:#d9c9e0">Pick a room to be taken there and have it opened. Same rooms as the walk.</p><div id="w-tlist"></div><button class="w-btn" id="w-tclose" type="button" style="margin-top:.8rem">Close (Esc)</button></div></div>
      <div class="w-fade" id="w-fade"></div>`;
    const cv = $('canvas.w-main', root), ctx = cv.getContext('2d');
    const mini = $('canvas.w-mini', root), mctx = mini.getContext('2d');
    const el = (id) => $('#' + id, root);

    /* ---------- state ---------- */
    const S = {
      floor: 0, p: { x: 0, y: 0, dir: 'down', moving: false, t: 0 }, cam: { x: 0, y: 0 }, keys: new Set(),
      path: null, pending: null, panel: null, cooldown: 0, nearby: null, joy: { x: 0, y: 0 }, travelOpen: false, sound: true,
      say: null, sayI: 0, fading: false, time: 0, stairLock: false,
    };
    const F = () => floors[S.floor];
    const rowsOf = () => F().rows;
    const npcsOn = () => map.npcs.filter((n) => n.floor === S.floor);
    const doorsOn = () => map.doors.filter((d) => d.floor === S.floor);
    S.p.x = floors[0].arrive.spawn[0] + .5; S.p.y = floors[0].arrive.spawn[1] + .5;

    /* ---------- static layers ---------- */
    const layers = floors.map((f) => prerender(f));
    function prerender(f) {
      const W = f.rows[0].length, H = f.rows.length;
      const c = document.createElement('canvas'); c.width = W * TS; c.height = H * TS;
      const g = c.getContext('2d');
      const at = (x, y) => G.tileAt(f.rows, x, y);
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) drawFloor(g, f, x, y, at);
      // painted room art as a faint floor wash over the walkable area
      g.save(); g.globalAlpha = 0.2; g.globalCompositeOperation = 'soft-light';
      const wash = f.id === 0 ? assets.hall : assets.bg[f.id];
      if (wash.complete && wash.naturalWidth) g.drawImage(wash, 0, f.id === 0 ? 13 * TS : 0, W * TS, f.id === 0 ? 12 * TS : H * TS);
      g.restore();
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) drawWall(g, f, x, y, at);
      map.doors.filter((d) => d.floor === f.id && d.banner).forEach((d) => banner(g, d));
      return c;
    }
    function drawFloor(g, f, x, y, at) {
      const t = at(x, y), px = x * TS, py = y * TS, r = hash(x, y, 1);
      if (t === ' ') return;
      if (G.SOLID.has(t) && !'f~c'.includes(t)) return;
      const out = f.outdoor && y >= f.outdoor[0] && y <= f.outdoor[1];
      let base = out ? [58, 60, 74] : [92, 70, 96];
      if (t === '=') base = [118, 22, 44];
      if (t === 'U' || t === 'd') base = [92, 70, 100];
      const k = 0.88 + r * 0.24;
      g.fillStyle = `rgb(${base[0] * k | 0},${base[1] * k | 0},${base[2] * k | 0})`; g.fillRect(px, py, TS, TS);
      g.strokeStyle = 'rgba(8,2,14,.55)'; g.lineWidth = 1.2;
      if (out) { // cobbles
        g.strokeStyle = 'rgba(8,2,14,.4)'; const o = (y % 2) * 20; g.strokeRect(px + .5, py + .5, TS - 1, 20); g.beginPath(); g.moveTo(px + o, py + 20); g.lineTo(px + o, py + TS); g.stroke(); if (r > 0.82) { g.fillStyle = 'rgba(60,90,60,.35)'; g.fillRect(px + r * 20, py + 22, 10, 4); }
      } else if (t === '=') {
        g.strokeStyle = 'rgba(233,196,106,.85)'; g.lineWidth = 2;
        if (at(x - 1, y) !== '=') { g.beginPath(); g.moveTo(px + 3, py); g.lineTo(px + 3, py + TS); g.stroke(); }
        if (at(x + 1, y) !== '=') { g.beginPath(); g.moveTo(px + TS - 3, py); g.lineTo(px + TS - 3, py + TS); g.stroke(); }
        g.fillStyle = 'rgba(0,0,0,.12)'; if ((x + y) % 2) g.fillRect(px + 8, py + 8, TS - 16, TS - 16);
      } else if (t === 'U' || t === 'd') {
        for (let i = 0; i < 5; i++) { g.fillStyle = `rgba(${t === 'U' ? '255,240,220' : '0,0,0'},${0.08 + i * 0.07})`; g.fillRect(px, py + i * 8, TS, 6); g.fillStyle = 'rgba(0,0,0,.35)'; g.fillRect(px, py + i * 8 + 6, TS, 2); }
      } else { if ((x + y) % 2) { g.fillStyle = 'rgba(20,6,26,.28)'; g.fillRect(px, py, TS, TS); } g.strokeStyle = 'rgba(201,154,58,.18)'; g.strokeRect(px + .5, py + .5, TS - 1, TS - 1); g.strokeStyle = 'rgba(255,255,255,.06)'; if (r > 0.6) { g.beginPath(); g.moveTo(px + r * 30, py); g.lineTo(px + r * 30 + 6, py + 12); g.stroke(); } }
      if (t === '~') { g.fillStyle = '#31526e'; g.fillRect(px + 3, py + 3, TS - 6, TS - 6); g.strokeStyle = '#8aa0b8'; g.lineWidth = 3; g.strokeRect(px + 3, py + 3, TS - 6, TS - 6); }
      if (t === 'f') { g.fillStyle = '#6a5a70'; g.fillRect(px + 8, py + 4, TS - 16, TS - 8); g.fillStyle = '#8a7a90'; g.fillRect(px + 8, py + 4, 5, TS - 8); g.fillStyle = '#3a2d40'; g.fillRect(px + 5, py + TS - 8, TS - 10, 6); g.fillRect(px + 5, py + 2, TS - 10, 5); }
    }
    function drawWall(g, f, x, y, at) {
      const t = at(x, y); if (!'#twbD'.includes(t)) return;
      const px = x * TS, py = y * TS, below = at(x, y + 1);
      const face = !G.SOLID.has(below) || 'f~c'.includes(below);
      if (t === 'D') return doorTile(g, px, py);
      if (face || t === 'b') {
        const gr = g.createLinearGradient(0, py, 0, py + TS); gr.addColorStop(0, '#3a2440'); gr.addColorStop(1, '#241230');
        g.fillStyle = gr; g.fillRect(px, py, TS, TS);
        g.strokeStyle = 'rgba(10,3,16,.7)'; g.lineWidth = 1.2;
        for (let r = 0; r < 4; r++) { const yy = py + r * 10; g.beginPath(); g.moveTo(px, yy); g.lineTo(px + TS, yy); g.stroke(); const off = (r + x) % 2 ? 0 : 10; for (let c = off; c < TS; c += 20) { g.beginPath(); g.moveTo(px + c, yy); g.lineTo(px + c, yy + 10); g.stroke(); } }
        g.fillStyle = 'rgba(0,0,0,.35)'; g.fillRect(px, py + TS - 5, TS, 5);
        if (t === 'b') { g.fillStyle = '#4a2c1c'; g.fillRect(px + 1, py + 1, TS - 2, TS - 2); for (let r = 0; r < 3; r++) { g.fillStyle = '#2a170e'; g.fillRect(px + 1, py + 11 + r * 12, TS - 2, 2); for (let b = 0; b < 7; b++) { g.fillStyle = ['#8a1a3a', '#2c5a7a', '#c99a3a', '#4a7a4a', '#6a3a8a'][(b + r + x) % 5]; g.fillRect(px + 3 + b * 5, py + 2 + r * 12 + (b % 2), 4, 9 - (b % 2)); } } }
        if (t === 'w') { g.fillStyle = '#0a1a3a'; g.beginPath(); g.moveTo(px + 9, py + TS - 6); g.lineTo(px + 9, py + 14); g.arc(px + TS / 2, py + 14, 11, Math.PI, 0); g.lineTo(px + TS - 9, py + TS - 6); g.fill(); g.strokeStyle = '#7a6a88'; g.lineWidth = 2.5; g.stroke(); g.fillStyle = '#e9e2c0'; g.beginPath(); g.arc(px + 25, py + 15, 4, 0, 7); g.fill(); }
        if (t === 't') { g.fillStyle = '#5a4a30'; g.fillRect(px + 17, py + 18, 6, 14); g.fillStyle = '#2a1e14'; g.fillRect(px + 14, py + 16, 12, 4); }
      } else { // wall top
        g.fillStyle = '#160a1c'; g.fillRect(px, py, TS, TS);
        g.strokeStyle = '#2a1636'; g.lineWidth = 1; g.strokeRect(px + .5, py + .5, TS - 1, TS - 1);
        if (at(x, y - 1) === ' ') { g.fillStyle = '#2a1636'; for (let m = 0; m < 2; m++) g.fillRect(px + 3 + m * 20, py - 6, 14, 8); }
      }
    }
    function doorTile(g, px, py) {
      g.fillStyle = '#1a0d1e'; g.fillRect(px - 2, py - 8, TS + 4, TS + 8);
      g.fillStyle = '#4a2a1a'; g.beginPath(); g.moveTo(px + 3, py + TS); g.lineTo(px + 3, py + 12); g.arc(px + TS / 2, py + 12, 17, Math.PI, 0); g.lineTo(px + TS - 3, py + TS); g.fill();
      g.strokeStyle = '#c99a3a'; g.lineWidth = 2.5; g.stroke();
      g.strokeStyle = 'rgba(0,0,0,.4)'; g.lineWidth = 1.5; for (let i = 1; i < 4; i++) { g.beginPath(); g.moveTo(px + 3 + i * 8.5, py + 6); g.lineTo(px + 3 + i * 8.5, py + TS); g.stroke(); }
      g.fillStyle = '#e9c46a'; g.beginPath(); g.arc(px + TS - 11, py + 26, 2.6, 0, 7); g.fill();
    }
    function banner(g, d) {
      const im = assets.room[d.room]; if (!im || !im.naturalWidth) return;
      const bw = 6 * TS, bh = 3.6 * TS, bx = d.x * TS + TS / 2 - bw / 2, by = (d.y - 4.4) * TS;
      g.save(); g.fillStyle = '#c99a3a'; g.fillRect(bx - 5, by - 5, bw + 10, bh + 10); g.fillStyle = '#1a0d1e'; g.fillRect(bx - 2, by - 2, bw + 4, bh + 4);
      g.drawImage(im, bx, by, bw, bh);
      const gr = g.createLinearGradient(0, by, 0, by + bh); gr.addColorStop(0.6, 'rgba(10,3,16,0)'); gr.addColorStop(1, 'rgba(10,3,16,.45)'); g.fillStyle = gr; g.fillRect(bx, by, bw, bh);
      g.restore();
    }

    /* ---------- sound (WebAudio, tiny) ---------- */
    let ac = null;
    function blip(freq, dur, vol, type) {
      if (!S.sound) return;
      try {
        ac = ac || new (window.AudioContext || window.webkitAudioContext)();
        const o = ac.createOscillator(), gn = ac.createGain(); o.type = type || 'triangle'; o.frequency.value = freq;
        gn.gain.setValueAtTime(vol, ac.currentTime); gn.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + dur);
        o.connect(gn); gn.connect(ac.destination); o.start(); o.stop(ac.currentTime + dur);
      } catch (e) { /* audio blocked until a gesture */ }
    }
    const stepSound = () => blip(90 + Math.random() * 30, 0.08, 0.05, 'square');
    const stairSound = () => [0, 1, 2, 3].forEach((i) => setTimeout(() => blip(120 + i * 22, 0.09, 0.06, 'square'), i * 90));
    el('w-snd').addEventListener('click', (e) => { S.sound = !S.sound; e.currentTarget.textContent = S.sound ? 'Sound on' : 'Sound off'; e.currentTarget.setAttribute('aria-pressed', S.sound); });

    /* ---------- movement and collision ---------- */
    const HW = 0.2, HH = 0.12;
    function blockedAt(x, y, dyn) {
      const rows = rowsOf();
      for (const [cx, cy] of [[x - HW, y - HH], [x + HW, y - HH], [x - HW, y + HH], [x + HW, y + HH]]) {
        const tx = Math.floor(cx), ty = Math.floor(cy);
        if (G.solid(rows, tx, ty)) return { tile: G.tileAt(rows, tx, ty), tx, ty };
        if (npcsOn().some((n) => n.x === tx && n.y === ty)) return { tile: 'N', tx, ty };
      }
      return null;
    }
    function step(dt) {
      const p = S.p;
      if (S.panel || S.travelOpen || S.fading) { p.moving = false; return; }
      let vx = 0, vy = 0; const k = S.keys;
      if (k.has('a') || k.has('arrowleft')) vx -= 1; if (k.has('d') || k.has('arrowright')) vx += 1;
      if (k.has('w') || k.has('arrowup')) vy -= 1; if (k.has('s') || k.has('arrowdown')) vy += 1;
      vx += S.joy.x; vy += S.joy.y;
      if (vx || vy) S.path = null;
      else if (S.path && S.path.length) { // follow click-to-walk path
        const n = S.path[0], dx = n.x + .5 - p.x, dy = n.y + .5 - p.y, d = Math.hypot(dx, dy);
        if (d < 0.12) S.path.shift(); else { vx = dx / d; vy = dy / d; }
        if (!S.path.length) { S.path = null; if (S.pending) { const q = S.pending; S.pending = null; q(); } }
      }
      const m = Math.hypot(vx, vy);
      p.moving = m > 0.05;
      if (!p.moving) return;
      vx /= Math.max(m, 1); vy /= Math.max(m, 1);
      const sp = (k.has('shift') ? 6.4 : 3.9) * dt;
      if (Math.abs(vx) > Math.abs(vy)) p.dir = vx < 0 ? 'left' : 'right'; else p.dir = vy < 0 ? 'up' : 'down';
      const nx = p.x + vx * sp, ny = p.y + vy * sp;
      let hit = blockedAt(nx, p.y); if (!hit) p.x = nx; else if (hit.tile === 'D') pushDoor(hit);
      hit = blockedAt(p.x, ny); if (!hit) p.y = ny; else if (hit.tile === 'D') pushDoor(hit);
      p.t += dt * (k.has('shift') ? 11 : 7.5);
      if (Math.floor(p.t) !== Math.floor(p.t - dt * 8)) stepSound();
    }
    function pushDoor(h) { const d = doorsOn().find((q) => q.x === h.tx && q.y === h.ty); if (d && S.cooldown <= 0) openRoom(d.room, d); }

    function stairsCheck() {
      const rows = rowsOf(), t = G.tileAt(rows, Math.floor(S.p.x), Math.floor(S.p.y));
      if (t !== 'U' && t !== 'd') { S.stairLock = false; return; }
      if (!S.stairLock && !S.fading) goFloor(t === 'U' ? S.floor + 1 : S.floor - 1, t === 'U');
    }
    function goFloor(n, up) {
      const f = floors[n]; if (!f) return;
      const a = up ? f.arrive.fromBelow : f.arrive.fromAbove; if (!a) return;
      S.fading = true; S.stairLock = true; stairSound(); el('w-fade').classList.add('on');
      setTimeout(() => {
        S.floor = n; S.p.x = a[0] + .5; S.p.y = a[1] + .5; S.path = null; snapCam(); updateFloorLabel();
        setTimeout(() => { el('w-fade').classList.remove('on'); S.fading = false; }, 120);
      }, 200);
    }
    function updateFloorLabel() { el('w-floor').textContent = F().name; document.title = F().name + ' | CHIMERA'; }

    /* ---------- interaction ---------- */
    function findInteract() {
      const p = S.p, best = { d: 1.5, o: null };
      doorsOn().forEach((d) => { const dd = Math.hypot(d.x + .5 - p.x, d.y + .5 - p.y); if (dd < best.d) { best.d = dd; best.o = { type: 'door', d, label: 'Enter ' + rooms[d.room].title }; } });
      npcsOn().forEach((n) => { const dd = Math.hypot(n.x + .5 - p.x, n.y + .5 - p.y); if (dd < Math.max(best.d, 1.6)) { best.d = dd; best.o = n.room ? { type: 'npc', n, label: 'Ask the bat' } : { type: 'npc', n, label: 'Talk to ' + n.name }; } });
      const rows = rowsOf();
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) { const t = G.tileAt(rows, Math.floor(p.x) + dx, Math.floor(p.y) + dy); if ((t === 'U' || t === 'd') && best.d > 1.2) { best.d = 1.2; best.o = { type: 'stairs', up: t === 'U', label: t === 'U' ? 'Climb the stairs' : 'Go down the stairs' }; } }
      return best.o;
    }
    function interact() {
      if (S.panel || S.travelOpen || S.fading) return;
      const o = S.nearby; if (!o) return;
      if (o.type === 'door') openRoom(o.d.room, o.d);
      else if (o.type === 'stairs') goFloor(S.floor + (o.up ? 1 : -1), o.up);
      else if (o.n.room) openRoom(o.n.room, null);
      else talk(o.n);
    }
    function talk(n) {
      if (S.say !== n) { S.say = n; S.sayI = 0; } else S.sayI++;
      if (S.sayI >= n.lines.length) { S.say = null; el('w-say').hidden = true; return; }
      const b = el('w-say'); b.hidden = false; b.innerHTML = `<b>${esc(n.name.toUpperCase())}</b>${esc(n.lines[S.sayI])}`;
      blip(300, 0.1, 0.04, 'sine');
    }

    /* ---------- panels ---------- */
    let closeHook = null;
    function openRoom(id, door) {
      const r = rooms[id]; if (!r || S.panel) return;
      S.panel = id; S.say = null; el('w-say').hidden = true; S.path = null;
      const pb = el('w-pbody'); pb.className = 'w-pb'; pb.textContent = '';
      el('w-ptitle').textContent = r.title; el('w-panel').hidden = false; blip(200, 0.15, 0.06, 'sine');
      history.replaceState(null, '', '#walk/' + id);
      if (r.kind === 'posters') postersPanel(pb, r.ref || id);
      else if (r.kind === 'dashboard') dashboardPanel(pb, id);
      if (r.kind !== 'dashboard') mountDash(pb, r.ref || id);
      else if (r.kind === 'chat') { pb.classList.add('flush'); pb.style.padding = '.8rem'; closeHook = window.CastleChat ? window.CastleChat.mount(pb, opts.chat || {}) : null; if (!closeHook) pb.textContent = 'Chat module not loaded.'; }
      S.leave = door; S.cooldown = 0.7;
      el('w-pclose').focus();
    }
    function closePanel() {
      if (!S.panel) return;
      if (typeof closeHook === 'function') closeHook(); closeHook = null;
      unmountDash();
      el('w-pbody').textContent = ''; el('w-panel').hidden = true; S.panel = null; S.cooldown = 0.7;
      const d = S.leave; S.leave = null;
      if (d) { S.p.x = d.stand[0] + .5; S.p.y = d.stand[1] + .5; }
      history.replaceState(null, '', location.pathname + location.search);
    }
    function postersPanel(pb, id) {
      const r = ROOMS.find((x) => x.id === id);
      if (!r) { pb.innerHTML = '<p class="lead">This room has no posters yet.</p>'; return; }
      pb.innerHTML = `<p class="lead">${esc(r.say.join(' '))}</p><div class="w-posters">` + r.posters.map((p) =>
        `<article class="w-poster"><h3>${esc(p.title)}</h3>${p.big ? `<p class="big">${esc(p.big)}</p>` : ''}${p.steps ? `<ol>${p.steps.map((s) => `<li>${esc(s)}</li>`).join('')}</ol>` : ''}` +
        p.lines.map((t) => `<p>${esc(t)}</p>`).join('') + `<p class="fn"><a href="${BASE}${esc(p.src[1])}">${esc(p.src[0])}</a></p></article>`).join('') + '</div>';
    }
    /* Dashboard blocks (site/dashboard.js) live in #dash-store; a room borrows its block while open. */
    let borrowed = [];
    function mountDash(pb, id) {
      const store = document.getElementById('dash-store'), blk = store && store.querySelector(`[data-dash="${id}"]`);
      if (!blk) return false;
      const bar = document.getElementById('dash-bar'), wrap = document.createElement('div');
      wrap.className = 'w-dash'; pb.appendChild(wrap);
      [bar, blk].forEach((n) => { if (n) { borrowed.push(n); wrap.appendChild(n); n.hidden = false; } });
      if (window.Dash) window.Dash.enter(id);
      return true;
    }
    function unmountDash() {
      const store = document.getElementById('dash-store');
      borrowed.forEach((n) => { n.hidden = true; if (store) store.appendChild(n); }); borrowed = [];
    }
    function dashboardPanel(pb, id) {
      pb.classList.add('flush');
      if (mountDash(pb, id)) return;
      const url = new URLSearchParams(location.search).get('hud') || (map.dashboard && map.dashboard.url);
      if (!url) { pb.innerHTML = '<p class="lead" style="padding:1rem">The dashboard is not connected on this page.</p>'; return; }
      pb.innerHTML = `<iframe title="Live dashboard" src="${esc(url)}"></iframe>`;
    }
    el('w-pclose').addEventListener('click', closePanel);

    /* ---------- travel list ---------- */
    function openTravel() {
      if (S.panel) return;
      const by = {};
      Object.entries(rooms).forEach(([id, r]) => { (by[r.floor] = by[r.floor] || []).push(id); });
      el('w-tlist').innerHTML = Object.keys(by).sort().map((fl) => `<h3>${esc(floors[fl].name)}</h3><ul aria-label="${esc(floors[fl].name)}">` +
        by[fl].map((id) => `<li><button type="button" data-room="${id}" aria-label="Go to ${esc(rooms[id].title)}, floor ${+fl + 1}">${esc(rooms[id].title)}<small>${esc(blurb(id))}</small></button></li>`).join('') + '</ul>').join('');
      el('w-travel').hidden = false; S.travelOpen = true; el('w-tlist').querySelector('button').focus();
    }
    function blurb(id) { const r = ROOMS.find((x) => x.id === (rooms[id].ref || id)); return rooms[id].blurb || (r && r.door) || (rooms[id].kind === 'chat' ? 'Ask the bat anything. Watch each step it takes.' : ''); }
    function closeTravel() { el('w-travel').hidden = true; S.travelOpen = false; }
    el('w-tlist').addEventListener('click', (e) => {
      const b = e.target.closest('button[data-room]'); if (!b) return;
      const id = b.dataset.room, door = map.doors.find((d) => d.room === id), r = rooms[id];
      closeTravel();
      const st = door ? door.stand : r.stand || [S.p.x | 0, S.p.y | 0];
      S.floor = r.floor; S.p.x = st[0] + .5; S.p.y = st[1] + .5; snapCam(); updateFloorLabel(); openRoom(id, door);
    });
    el('w-skip').addEventListener('click', openTravel); el('w-tclose').addEventListener('click', closeTravel);

    /* ---------- input ---------- */
    const typing = (t) => t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName);
    addEventListener('keydown', (e) => {
      if (root.hidden || e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === 'escape') { if (S.travelOpen) closeTravel(); else if (S.panel) closePanel(); else if (S.say) { S.say = null; el('w-say').hidden = true; } return; }
      if (typing(e.target) || S.panel) return;
      if (S.travelOpen) return;
      if (k === 'm') { e.preventDefault(); openTravel(); return; }
      if ((k === 'e' || k === 'enter') && !e.repeat && !(k === 'enter' && /BUTTON|A/.test(e.target.tagName))) { e.preventDefault(); interact(); return; }
      if ('wasd'.includes(k) || k.startsWith('arrow') || k === 'shift') { S.keys.add(k); if (k.startsWith('arrow')) e.preventDefault(); }
    });
    addEventListener('keyup', (e) => S.keys.delete(e.key.toLowerCase()));
    addEventListener('blur', () => S.keys.clear());

    cv.addEventListener('pointerdown', (e) => { // click-to-walk with A*
      if (S.panel || S.travelOpen || S.fading) return;
      const r = cv.getBoundingClientRect(), z = zoom();
      const wx = (e.clientX - r.left) / r.width * cv.width / z + S.cam.x, wy = (e.clientY - r.top) / r.height * cv.height / z + S.cam.y;
      const tx = Math.floor(wx / TS), ty = Math.floor(wy / TS), rows = rowsOf();
      const sx = Math.floor(S.p.x), sy = Math.floor(S.p.y);
      let gx = tx, gy = ty, then = null;
      const door = doorsOn().find((d) => d.x === tx && d.y === ty), npc = npcsOn().find((n) => n.x === tx && n.y === ty);
      if (door) { gx = door.stand[0]; gy = door.stand[1]; then = () => openRoom(door.room, door); }
      else if (npc) { const c = [[0, 1], [0, -1], [1, 0], [-1, 0], [1, 1], [-1, 1]].map(([a, b]) => [tx + a, ty + b]).find(([a, b]) => !G.solid(rows, a, b)); if (!c) return; gx = c[0]; gy = c[1]; then = () => { S.nearby = findInteract(); interact(); }; }
      else if (G.tileAt(rows, tx, ty) === 'U' || G.tileAt(rows, tx, ty) === 'd') { /* walk onto it */ }
      const path = G.findPath(rows, sx, sy, gx, gy);
      if (path) { S.path = path; S.pending = then; blip(260, 0.06, 0.03, 'sine'); }
    });
    const joy = el('w-joy'); let joyId = null;
    const joyMove = (e) => { const r = joy.getBoundingClientRect(), dx = e.clientX - (r.left + 60), dy = e.clientY - (r.top + 60), d = Math.min(1, Math.hypot(dx, dy) / 50), a = Math.atan2(dy, dx); S.joy.x = Math.cos(a) * d; S.joy.y = Math.sin(a) * d; if (d < 0.2) S.joy.x = S.joy.y = 0; joy.firstElementChild.style.transform = `translate(${Math.cos(a) * d * 40}px,${Math.sin(a) * d * 40}px)`; };
    joy.addEventListener('pointerdown', (e) => { joyId = e.pointerId; joy.setPointerCapture(joyId); joyMove(e); });
    joy.addEventListener('pointermove', (e) => { if (e.pointerId === joyId) joyMove(e); });
    const joyEnd = () => { joyId = null; S.joy.x = S.joy.y = 0; joy.firstElementChild.style.transform = ''; };
    joy.addEventListener('pointerup', joyEnd); joy.addEventListener('pointercancel', joyEnd);
    el('w-act').addEventListener('click', interact);

    /* ---------- ambient life ---------- */
    const bats = Array.from({ length: 7 }, (_, i) => ({ a: i * 0.9, r: 120 + i * 40, cx: 300 + i * 220, cy: 60 + (i % 3) * 60, s: 0.3 + i * 0.05, sz: 0.6 + (i % 3) * 0.25 }));
    const clouds = Array.from({ length: 5 }, (_, i) => ({ x: i * 420, y: 20 + i * 38, w: 360 + i * 60, s: 8 + i * 3 }));
    const motes = Array.from({ length: 40 }, () => ({ x: Math.random(), y: Math.random(), s: 0.01 + Math.random() * 0.03, p: Math.random() * 6 }));
    function drawBat(c, x, y, sc, t) {
      const f = Math.sin(t * 14) * 0.7;
      c.save(); c.translate(x, y); c.scale(sc, sc); c.fillStyle = '#07020a';
      c.beginPath(); c.moveTo(0, -4); c.quadraticCurveTo(-14, -14 - f * 12, -30, -4 - f * 8); c.quadraticCurveTo(-18, 0, -12, 5); c.quadraticCurveTo(-6, 0, 0, 6);
      c.quadraticCurveTo(6, 0, 12, 5); c.quadraticCurveTo(18, 0, 30, -4 - f * 8); c.quadraticCurveTo(14, -14 - f * 12, 0, -4); c.fill();
      c.beginPath(); c.arc(0, -1, 5, 0, 7); c.fill(); c.restore();
    }

    /* ---------- camera ---------- */
    const zoom = () => cv.height / (TS * VIEW_ROWS);
    function snapCam() { cam(1); }
    function cam(lerp) {
      const z = zoom(), vw = cv.width / z, vh = cv.height / z, f = F(), mw = f.rows[0].length * TS, mh = f.rows.length * TS;
      let tx = S.p.x * TS - vw / 2, ty = S.p.y * TS - vh / 2;
      tx = mw <= vw ? (mw - vw) / 2 : Math.max(0, Math.min(mw - vw, tx));
      ty = mh <= vh ? (mh - vh) / 2 : Math.max(0, Math.min(mh - vh, ty));
      S.cam.x += (tx - S.cam.x) * lerp; S.cam.y += (ty - S.cam.y) * lerp;
    }
    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2), w = root.clientWidth, h = root.clientHeight, cap = 1700 / Math.max(w, 1);
      const k = Math.min(dpr, cap > 0.5 ? cap : 0.5);
      cv.width = Math.round(w * k); cv.height = Math.round(h * k);
    }
    addEventListener('resize', resize); resize(); snapCam(); updateFloorLabel();

    /* ---------- render ---------- */
    const light = document.createElement('canvas'), lg = light.getContext('2d');
    function glow(c, x, y, r, col, a) { const g = c.createRadialGradient(x, y, 0, x, y, r); g.addColorStop(0, col.replace('A', a)); g.addColorStop(1, col.replace('A', 0)); c.fillStyle = g; c.fillRect(x - r, y - r, r * 2, r * 2); }
    function render(dt) {
      const t = S.time, z = zoom(), f = F(), W = f.rows[0].length, H = f.rows.length;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      // backdrop: painted image with parallax
      const bg = assets.bg[S.floor];
      ctx.fillStyle = '#0b0510'; ctx.fillRect(0, 0, cv.width, cv.height);
      if (bg.complete && bg.naturalWidth) {
        const sc = Math.max(cv.width / bg.naturalWidth, cv.height / bg.naturalHeight) * 1.12, bw = bg.naturalWidth * sc, bh = bg.naturalHeight * sc;
        ctx.drawImage(bg, (cv.width - bw) / 2 - (S.cam.x * z * 0.05) % 40, (cv.height - bh) / 2 - S.cam.y * z * 0.04, bw, bh);
        ctx.fillStyle = f.id === 0 ? 'rgba(11,5,16,.15)' : 'rgba(11,5,16,.55)'; ctx.fillRect(0, 0, cv.width, cv.height);
      }
      if (f.id === 0 || f.id === 2) { // drifting clouds and flying bats over the sky
        ctx.save(); ctx.scale(z, z);
        clouds.forEach((c) => { const x = ((c.x + t * c.s) % (cv.width / z + 600)) - 300; const g = ctx.createRadialGradient(x, c.y, 0, x, c.y, c.w / 2); g.addColorStop(0, 'rgba(120,80,150,.28)'); g.addColorStop(1, 'rgba(120,80,150,0)'); ctx.fillStyle = g; ctx.fillRect(x - c.w / 2, c.y - 80, c.w, 160); });
        bats.forEach((b) => { const a = t * b.s + b.a, x = ((b.cx + Math.cos(a) * b.r + t * 26 * b.sz) % (cv.width / z + 200)), y = b.cy + Math.sin(a * 1.7) * 40; drawBat(ctx, x, y, b.sz, t + b.a); });
        ctx.restore();
      }
      ctx.save(); ctx.scale(z, z); ctx.translate(-Math.round(S.cam.x), -Math.round(S.cam.y));
      ctx.drawImage(layers[S.floor], 0, 0);
      const rows = f.rows, vx0 = Math.max(0, Math.floor(S.cam.x / TS) - 1), vx1 = Math.min(W - 1, Math.ceil((S.cam.x + cv.width / z) / TS) + 1), vy0 = Math.max(0, Math.floor(S.cam.y / TS) - 2), vy1 = Math.min(H - 1, Math.ceil((S.cam.y + cv.height / z) / TS) + 1);
      const lights = [];
      for (let y = vy0; y <= vy1; y++) for (let x = vx0; x <= vx1; x++) {
        const tl = rows[y][x], cx = x * TS + TS / 2, cy = y * TS;
        if (tl === 't') { const fl = 0.8 + Math.sin(t * 11 + x * 3 + y) * 0.12 + Math.sin(t * 23 + x) * 0.08; flame(ctx, cx, cy + 14, fl, t + x); lights.push([cx, cy + 14, 230 * fl, 1]); }
        else if (tl === 'c') { const fl = 0.8 + Math.sin(t * 13 + x) * 0.15; flame(ctx, cx, cy + 12, fl * 0.7, t + y); lights.push([cx, cy + 14, 110 * fl, 0.9]); }
        else if (tl === 'w') { ctx.save(); ctx.globalCompositeOperation = 'lighter'; const g = ctx.createLinearGradient(cx, cy + 12, cx - 40, cy + 120); g.addColorStop(0, 'rgba(150,170,255,.22)'); g.addColorStop(1, 'rgba(150,170,255,0)'); ctx.fillStyle = g; ctx.beginPath(); ctx.moveTo(cx - 8, cy + 14); ctx.lineTo(cx + 12, cy + 14); ctx.lineTo(cx - 36, cy + 120); ctx.lineTo(cx - 70, cy + 120); ctx.fill(); ctx.restore(); }
        else if (tl === '~') { ctx.fillStyle = `rgba(200,230,255,${0.12 + Math.sin(t * 3 + x + y) * 0.06})`; ctx.fillRect(x * TS + 6, y * TS + 6, TS - 12, TS - 12); }
        else if (tl === 'D' || tl === 'U' || tl === 'd') lights.push([cx, cy + TS * 0.7, 80, 0.55]);
      }
      // entities sorted by y
      const ents = npcsOn().map((n) => ({ y: n.y + 0.5, draw: () => drawNpc(n, t) }));
      ents.push({ y: S.p.y, draw: drawPlayer });
      ents.sort((a, b) => a.y - b.y).forEach((e) => e.draw());
      nameplates(ctx, t);
      // fog and motes
      if (f.outdoor) { ctx.save(); const oy = f.outdoor[0] * TS; for (let i = 0; i < 4; i++) { const x = ((t * (6 + i * 3) + i * 500) % (W * TS + 400)) - 200, g = ctx.createRadialGradient(x, oy + 120 + i * 20, 0, x, oy + 120 + i * 20, 220); g.addColorStop(0, 'rgba(170,150,200,.14)'); g.addColorStop(1, 'rgba(170,150,200,0)'); ctx.fillStyle = g; ctx.fillRect(x - 220, oy - 100, 440, 440); } ctx.restore(); }
      ctx.restore();
      // lighting: darkness with light holes
      if (light.width !== cv.width) { light.width = cv.width; light.height = cv.height; }
      lg.setTransform(1, 0, 0, 1, 0, 0); lg.globalCompositeOperation = 'source-over'; lg.fillStyle = `rgba(6,2,12,${f.light})`; lg.fillRect(0, 0, light.width, light.height);
      lg.globalCompositeOperation = 'destination-out'; lg.save(); lg.scale(z, z); lg.translate(-Math.round(S.cam.x), -Math.round(S.cam.y));
      lights.forEach(([x, y, r, a]) => glow(lg, x, y, r, 'rgba(0,0,0,A)', a));
      glow(lg, S.p.x * TS, S.p.y * TS - 14, 220, 'rgba(0,0,0,A)', 0.85); npcsOn().forEach((n) => glow(lg, (n.x + .5) * TS, (n.y + .2) * TS, 130, 'rgba(0,0,0,A)', 0.7));
      if (f.outdoor) { lg.fillStyle = 'rgba(0,0,0,.55)'; lg.fillRect(0, f.outdoor[0] * TS - 20, W * TS, (f.outdoor[1] - f.outdoor[0] + 2) * TS); }
      lg.restore(); ctx.drawImage(light, 0, 0);
      // warm glow additive
      ctx.save(); ctx.scale(z, z); ctx.translate(-Math.round(S.cam.x), -Math.round(S.cam.y)); ctx.globalCompositeOperation = 'lighter';
      lights.forEach(([x, y, r, a]) => glow(ctx, x, y, r * 0.8, 'rgba(255,150,50,A)', 0.2 * a));
      motes.forEach((m) => { const x = (m.x * W * TS + t * m.s * 200) % (W * TS), y = (m.y * H * TS + Math.sin(t + m.p) * 20); ctx.fillStyle = 'rgba(255,220,160,.35)'; ctx.fillRect(x, y, 2, 2); });
      ctx.restore();
    }
    function flame(c, x, y, s, ph) {
      c.save(); c.globalCompositeOperation = 'lighter';
      const g = c.createRadialGradient(x, y, 0, x, y, 16 * s); g.addColorStop(0, 'rgba(255,230,150,.95)'); g.addColorStop(0.4, 'rgba(255,140,40,.6)'); g.addColorStop(1, 'rgba(255,60,0,0)'); c.fillStyle = g;
      c.beginPath(); c.ellipse(x + Math.sin(ph * 9) * 1.5, y - 6 * s, 6 * s, 11 * s, 0, 0, 7); c.fill(); c.restore();
    }
    function drawPlayer() {
      const p = S.p, row = p.dir === 'down' ? 0 : p.dir === 'up' ? 1 : 2, fr = p.moving ? Math.floor(p.t) % 4 : 1;
      const w = 36, h = 48, x = p.x * TS, y = p.y * TS;
      ctx.save(); ctx.translate(x, y + 6); if (p.dir === 'left') ctx.scale(-1, 1);
      ctx.drawImage(assets.player, fr * 48, row * 64, 48, 64, -w / 2, -h + 4, w, h); ctx.restore();
    }
    function drawNpc(n, t) {
      const x = (n.x + 0.5) * TS, y = (n.y + 0.5) * TS;
      if (n.kind === 'count') { const fr = Math.floor(t * 1.6) % 2; ctx.drawImage(assets.count, fr * 48, 0, 48, 64, x - 20, y - 38, 40, 53); }
      else { // the bat familiar, perched on the desk: glowing eyes, slow wing shiver
        const sh = Math.sin(t * 2.2) * 0.12; ctx.save(); ctx.translate(x, y - 8 + Math.sin(t * 2) * 1.5);
        ctx.fillStyle = 'rgba(0,0,0,.35)'; ctx.beginPath(); ctx.ellipse(0, 22, 14, 5, 0, 0, 7); ctx.fill();
        ctx.fillStyle = '#120818'; ctx.beginPath(); ctx.moveTo(-6, -2); ctx.quadraticCurveTo(-24 - sh * 30, -14, -26, 14); ctx.quadraticCurveTo(-14, 8, -9, 20); ctx.lineTo(9, 20); ctx.quadraticCurveTo(14, 8, 26, 14); ctx.quadraticCurveTo(24 + sh * 30, -14, 6, -2); ctx.fill();
        ctx.beginPath(); ctx.ellipse(0, 4, 9, 14, 0, 0, 7); ctx.fill();
        ctx.beginPath(); ctx.moveTo(-8, -10); ctx.lineTo(-6, -22); ctx.lineTo(-1, -12); ctx.lineTo(1, -12); ctx.lineTo(6, -22); ctx.lineTo(8, -10); ctx.arc(0, -6, 8, 0, Math.PI); ctx.fill();
        ctx.fillStyle = '#ff4060'; ctx.shadowColor = '#ff2040'; ctx.shadowBlur = 8; ctx.beginPath(); ctx.arc(-3.5, -7, 1.9, 0, 7); ctx.arc(3.5, -7, 1.9, 0, 7); ctx.fill(); ctx.restore();
      }
      if (S.nearby && S.nearby.n === n) { ctx.fillStyle = '#e9c46a'; ctx.font = '700 14px Inter, sans-serif'; ctx.textAlign = 'center'; ctx.fillText(n.room ? '?' : '!', x, y - 48 + Math.sin(t * 5) * 3); }
    }
    function nameplates(c, t) {
      c.font = '700 11px Cinzel, serif'; c.textAlign = 'center';
      doorsOn().forEach((d) => {
        const label = rooms[d.room].title, w = c.measureText(label).width + 16;
        let x = d.x * TS + TS / 2, y = d.y * TS - 10;
        if (d.x === 0) { x = TS * 2.3; y = d.y * TS + 6; } else if (d.x >= F().rows[0].length - 1) { x = d.x * TS - TS * 1.3; y = d.y * TS + 6; }
        c.fillStyle = 'rgba(26,13,30,.9)'; c.strokeStyle = '#c99a3a'; c.lineWidth = 1.5; c.beginPath(); c.roundRect(x - w / 2, y - 12, w, 20, 5); c.fill(); c.stroke();
        c.fillStyle = '#f4d58d'; c.fillText(label, x, y + 2);
      });
      npcsOn().forEach((n) => { if (n.kind !== 'bat') return; const x = (n.x + .5) * TS, y = (n.y + .5) * TS - 40; c.font = '700 11px Cinzel, serif'; const w = c.measureText(n.name).width + 14; c.fillStyle = 'rgba(26,13,30,.9)'; c.strokeStyle = '#ff4060'; c.beginPath(); c.roundRect(x - w / 2, y - 12, w, 20, 5); c.fill(); c.stroke(); c.fillStyle = '#ffd0d8'; c.fillText(n.name, x, y + 2); });
    }
    function drawMini() {
      const f = F(), W = f.rows[0].length, H = f.rows.length, s = Math.min(160 / W, 92 / H), ox = (168 - W * s) / 2, oy = 14;
      mctx.clearRect(0, 0, 168, 110); mctx.fillStyle = '#e9c46a'; mctx.font = '600 9px Inter, sans-serif'; mctx.fillText('Floor ' + (S.floor + 1) + ' of ' + floors.length, 6, 10);
      for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const t = f.rows[y][x]; if (t === ' ') continue; mctx.fillStyle = t === 'U' || t === 'd' ? '#e9c46a' : t === 'D' ? '#ff6a8a' : G.SOLID.has(t) ? '#2a1636' : t === '=' ? '#8a1a3a' : '#5a4a68'; mctx.fillRect(ox + x * s, oy + y * s, Math.ceil(s), Math.ceil(s)); }
      npcsOn().forEach((n) => { mctx.fillStyle = n.kind === 'bat' ? '#ff4060' : '#ffffff'; mctx.fillRect(ox + n.x * s - 1, oy + n.y * s - 1, 3, 3); });
      mctx.fillStyle = '#6ee7a0'; mctx.beginPath(); mctx.arc(ox + S.p.x * s, oy + S.p.y * s, 3 + Math.sin(S.time * 6), 0, 7); mctx.fill();
    }

    /* ---------- loop: never paused ---------- */
    let last = performance.now();
    function frame(now) {
      const dt = Math.min(0.05, (now - last) / 1000); last = now; S.time += dt; S.cooldown = Math.max(0, S.cooldown - dt);
      step(dt); if (!S.panel) stairsCheck(); cam(1 - Math.pow(0.0008, dt));
      S.nearby = S.panel || S.fading ? null : findInteract();
      const pr = el('w-prompt'); if (S.nearby) { pr.innerHTML = `<kbd>E</kbd> ${esc(S.nearby.label)}`; pr.classList.add('on'); } else pr.classList.remove('on');
      render(dt); drawMini();
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);

    // test and demo hooks (no pause: these only move the player)
    const api = {
      state: S, map, openRoom, closePanel, openTravel, interact,
      teleport(floor, x, y) { S.floor = floor; S.p.x = x + .5; S.p.y = y + .5; S.path = null; snapCam(); updateFloorLabel(); },
      walkTo(x, y, then) { const p = G.findPath(rowsOf(), Math.floor(S.p.x), Math.floor(S.p.y), x, y); if (p) { S.path = p; S.pending = then || null; } return !!p; },
      hold(key, on) { on ? S.keys.add(key) : S.keys.delete(key); },
    };
    window.CastleWorld = api;
    // deep links: #walk/<room>, bare room ids, and the old HUD and tour links
    const OLD = { live: 'observatory', bench: 'ledger', evals: 'ledger', how: 'ladder' };
    const hid = location.hash.replace(/^#(walk\/|room\/|r-)?/, '');
    const m = [null, OLD[hid] || hid];
    if (m[1] && rooms[m[1]]) setTimeout(() => { const r = rooms[m[1]], d = map.doors.find((q) => q.room === m[1]); const st = d ? d.stand : r.stand; api.teleport(r.floor, st[0], st[1]); openRoom(m[1], d); }, 400);
    return api;
  }
  window.CastleStart = start;
})();
