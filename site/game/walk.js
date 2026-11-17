/* CHIMERA, the walk-in castle. YOU are the camera, in a real 3D world (game/world3d.js, three.js vendored).
   One continuous walk on one rail: the road outside the closed iron gates -> the gates swing open as you reach them
   -> the lantern drive -> the great door opens as you reach it -> the Great Hall. It never cuts and never jumps back.
   W walks (towards where you look), S walks back, Shift runs. The mouse looks anywhere: click to lock it, Esc
   releases it; dragging works too, and A/D or the arrow keys turn. E opens or closes the gate or door you look at,
   and opens the room door you look at in the hall. Live layers: a bat flock round the moon, the Count's bubble,
   the door signs as real text, the painted minimap. Never paused. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const rnd = (() => { let s = 7; return () => ((s = (s * 16807) % 2147483647) / 2147483647); })();
  const angle = (a) => Math.atan2(Math.sin(a), Math.cos(a));

  /* The walk in stretches (rail seconds s0..s1). The map, the tour and the tests use these names. */
  const SEGS = [
    { id: 'a-approach', s0: 0, s1: 1.25, where: 'Before the iron gates', say: 'Good evening. The gates are shut, but they know me. Hold W and walk up to them.' },
    { id: 'b-gates', s0: 1.25, s1: 1.8, where: 'Through the iron gates', lock: 'gates', say: 'The gates swing open for you. Keep walking.' },
    { id: 'c-drive', s0: 1.8, s1: 2.65, where: 'The lantern drive', say: 'Follow the lanterns. The great door is ahead.' },
    { id: 'd-door', s0: 2.65, s1: 3.2, where: 'The great door', lock: 'door', say: 'The great door opens. Step inside.' },
    { id: 'e-hall', s0: 3.2, s1: 3.45, where: 'The Great Hall', say: 'Every gold door is a room. Look at one and press E.' },
  ];
  SEGS.forEach((s) => { s.secs = s.s1 - s.s0; });
  const NAME = { gates: 'the iron gates', door: 'the great door' };

  async function start(root, opts = {}) {
    const site = opts.site || '';
    const touch = matchMedia('(pointer: coarse)').matches;
    const ROOMS = window.ROOMS || [];
    const W3 = await (window.World3DReady || Promise.reject(new Error('no 3D')));
    const { SLOTS, PLAN, railZ, railS, S_HALL, S_END } = W3;
    const ORDER = SLOTS.map((s) => s.room);
    const rank = (id) => { const k = ORDER.indexOf(id); return k < 0 ? 99 : k; };
    const doors = ROOMS.map((r) => ({ id: r.id, title: r.title, sub: r.door, art: r.art || 'room-' + r.id, clip: r.clip })).filter((d) => ORDER.includes(d.id)).sort((a, b) => rank(a.id) - rank(b.id));

    root.innerHTML = `
      <canvas class="m-gl" id="m-gl" tabindex="0" aria-label="The castle in 3D. Hold W to walk, the mouse or A and D to look around, E to open, M for the map."></canvas>
      <canvas id="m-fx" aria-hidden="true"></canvas>
      <div class="m-doors" id="m-doors" hidden></div>
      <div class="m-cross" id="m-cross" aria-hidden="true"></div>
      <aside class="m-board" id="m-board" hidden aria-label="Savings board"></aside>
      <div class="m-bar"><span id="m-mode" class="mode-badge" role="status">…</span><span id="m-where"></span><span id="m-fps" class="m-fps"></span>
        <button class="m-btn m-gold" id="m-tourbtn" type="button">Tour<span class="m-k"> (T)</span></button><button class="m-btn" id="m-mapbtn" type="button">Map<span class="m-k"> (M)</span></button><button class="m-btn" id="m-talkbtn" type="button">Talk<span class="m-k"> to the Count (C)</span></button></div>
      <div class="m-prompt" id="m-prompt"></div>
      <div class="m-say" id="m-say"><b>Count Cuspid</b><span id="m-saytext"></span><small>Press <kbd>C</kbd> to talk to me · <kbd>T</kbd> for a tour</small></div>
      <figure class="m-minimap" id="m-minimap" aria-hidden="true"><figcaption>The Castle</figcaption><canvas id="m-mini"></canvas><p id="m-mini-at"></p></figure>
      <div class="m-help"><kbd>W</kbd> walk · <kbd>S</kbd> back · <kbd>Shift</kbd> run · <kbd>Click</kbd> look with the mouse (<kbd>Esc</kbd> frees it) · <kbd>A</kbd><kbd>D</kbd> turn · <kbd>E</kbd> open/close · <kbd>T</kbd> tour · <kbd>C</kbd> talk · <kbd>M</kbd> map</div>
      <div class="m-joy" id="m-joy"><i></i></div><button class="m-act" id="m-act" type="button" aria-label="Open">E</button>
      <section class="m-panel" id="m-panel" role="dialog" aria-modal="true" aria-labelledby="m-ptitle" hidden>
        <div class="m-pbg" id="m-pbg" aria-hidden="true"><i class="m-candle"></i><i class="m-fog a"></i><i class="m-fog b"></i></div>
        <div class="m-ph"><h2 id="m-ptitle"></h2><button class="m-btn" id="m-pclose" type="button">Leave (Esc)</button></div>
        <div class="m-pb" id="m-pbody"></div><i class="m-corner tl"></i><i class="m-corner tr"></i><i class="m-corner bl"></i><i class="m-corner br"></i></section>
      <div class="m-map" id="m-map" hidden><div class="m-mapbox" role="dialog" aria-modal="true" aria-labelledby="m-mtitle"><h2 id="m-mtitle">Map of the castle</h2>
        <div class="m-mapgrid"><canvas id="m-bigmap" aria-label="Map of the castle grounds and the Great Hall"></canvas><ol id="m-mlist"></ol></div>
        <button class="m-btn" id="m-mclose" type="button">Close (Esc)</button><i class="m-corner tl"></i><i class="m-corner tr"></i><i class="m-corner bl"></i><i class="m-corner br"></i></div></div>
      <div class="m-fade" id="m-fade"></div>`;
    const gl = $('m-gl'), fx = $('m-fx'), g = fx.getContext('2d');
    const world = W3.create(gl, { site, phone: touch });

    const S = { s: 0, seg: 0, t: 0, yaw: 0, pitch: 0.06, open: { gates: false, door: false }, anim: { gates: 0, door: 0 }, keys: new Set(), room: null, panel: false, map: false,
      hall: false, door: 0, time: 0, fps: [], walking: 0, joy: { x: 0, y: 0 }, aim: null, tour: false, target: null };
    const have = {};   // kept for old callers: the walk no longer plays clips
    const zNow = () => railZ(S.s);
    function syncSeg() { let i = 0; while (i < SEGS.length - 1 && S.s >= SEGS[i].s1) i++; S.seg = i; S.t = clamp(S.s - SEGS[i].s0, 0, SEGS[i].secs); return SEGS[i]; }
    let lastSeg = -1, lastGaze = -1;

    /* ---------- walking on the rail ---------- */
    function arrive(l) {
      if (S.open[l]) return; S.open[l] = true; creak();
      say(l === 'gates' ? 'The gates swing open for you. Keep walking.' : 'The great door opens. Step inside.');
    }
    function shut(l) {
      if (!S.open[l]) return; S.open[l] = false; clang();
      say(l === 'gates' ? 'The gates are shut behind you. They open again if you walk back to them.' : 'The great door is shut behind you. Walk back to it and it opens again.');
    }
    const PLANES = [['gates', PLAN.gateZ, 3.6], ['door', PLAN.doorZ, 5.2]];   // where each one stands, and how near you are when it opens
    function walk(dt, f, run) {
      const dir = Math.sign(f) * (Math.cos(S.yaw) < -0.25 ? -1 : 1), z0 = zNow();
      let s1 = clamp(S.s + dir * dt * (run ? 2 : 1), 0, S_END), z1 = railZ(s1);
      for (const [l, pz, near] of PLANES) {
        const toward = Math.abs(z1 - pz) < Math.abs(z0 - pz);
        if (!S.open[l] && toward && Math.abs(z1 - pz) < near) arrive(l);   // it opens as you reach it, not before
        if (S.anim[l] < 0.72 && ((z0 - pz) * (z1 - pz) <= 0 || Math.abs(z1 - pz) < 0.8) && toward) { s1 = S.s; z1 = z0; }   // wait a beat for it to swing clear
      }
      S.walking = s1 === S.s ? 0 : dir; S.s = s1;
      if (S.s >= S_HALL && !S.hall) enterHall(); else if (S.s < S_HALL - 0.04 && S.hall) leaveHall();
    }

    /* ---------- what you are looking at: a gate, the door, a room door ---------- */
    const fwd = () => ({ x: -Math.sin(S.yaw) * Math.cos(S.pitch), y: Math.sin(S.pitch), z: -Math.cos(S.yaw) * Math.cos(S.pitch) });
    function lookAt(p, maxD) {
      const z = zNow(), dx = p.x, dy = p.y - 1.7, dz = p.z - z, d = Math.hypot(dx, dy, dz); if (d > maxD) return 9;
      const f = fwd(); return Math.acos(clamp((dx * f.x + dy * f.y + dz * f.z) / d, -1, 1));
    }
    function findTarget() {
      if (S.panel || S.map || S.room) return null;
      const z = zNow(); let best = null;
      const consider = (t, a, lim) => { if (a < lim && (!best || a < best.a)) best = { ...t, a }; };
      if (S.hall || z < PLAN.hallZ0) world.roomDoors.forEach((d, k) => consider({ kind: 'room', k }, lookAt(d.at, 30), 0.42));
      for (const [l, pz] of PLANES) {
        const dist = Math.abs(z - pz), a = lookAt(world.anchors[l === 'gates' ? 'gates' : 'door'], l === 'gates' ? 18 : 24);
        if (dist < (l === 'gates' ? 16 : 22)) consider({ kind: l }, a, dist < 4 ? 1.2 : 0.55);
      }
      return best;
    }
    function use() {
      if (S.panel || S.map) return;
      const t = S.tour ? null : S.target || findTarget();
      if (!t || t.kind === 'room') { if (S.hall) openRoom(doors[S.door]); return; }   // S.door follows your gaze (or the tour, or a sign you clicked)
      const behind = t.kind === 'gates' ? zNow() < PLAN.gateZ : zNow() < PLAN.doorZ;
      if (S.open[t.kind]) { if (behind || Math.abs(zNow() - (t.kind === 'gates' ? PLAN.gateZ : PLAN.doorZ)) > 1.2) shut(t.kind); }
      else arrive(t.kind);
    }

    /* ---------- the hall: real-text signs over the gold doors ---------- */
    function enterHall() {
      if (S.hall) return; S.hall = true;
      if (S.s < S_HALL) { S.s = S_HALL + 0.01; S.open.gates = S.open.door = true; S.anim.gates = S.anim.door = 1; }   // a jump into the hall
      const box = $('m-doors');
      box.innerHTML = doors.map((d, k) => `<button class="m-door" data-k="${k}" data-id="${esc(d.id)}" type="button"><span class="m-plaque"><strong>${esc(d.title)}</strong><span>${esc(d.sub || '')}</span></span></button>`).join('');
      box.classList.toggle('m-arcade', touch || innerWidth < 700); box.classList.toggle('m-signs', !(touch || innerWidth < 700));
      box.hidden = false; board(true);
      say(touch ? 'Every gold door is a room. Tap a sign to open it.' : 'Every gold door is a room. Look at one and press E, or click its sign.');
    }
    function leaveHall() { S.hall = false; $('m-doors').hidden = true; board(false); }
    function placeSigns() {
      const box = $('m-doors'); if (box.hidden || box.classList.contains('m-arcade')) return;
      box.querySelectorAll('.m-door').forEach((b, k) => {
        const d = world.roomDoors[ORDER.indexOf(doors[k].id)]; if (!d) return;
        const p = world.project(d.sign), ok = p.front && !S.panel && (p.dist < 20 || (k === S.door && p.dist < 40));   // near signs, and the chosen one
        b.style.visibility = ok ? '' : 'hidden'; if (!ok) return;
        const sc = clamp(9 / p.dist, 0.55, 1.15);
        b.style.transform = `translate(${p.x.toFixed(1)}px, ${p.y.toFixed(1)}px) translate(-50%, -100%) scale(${sc.toFixed(3)})`;
        b.style.zIndex = String(100 - Math.round(p.dist));
      });
    }
    /* the savings board: live totals from /api/stats, the best measured result from results.json (read from bench/*.md) */
    let boardTimer = 0;
    function board(on) {
      const b = $('m-board'); b.hidden = !on; clearInterval(boardTimer); if (!on) return;
      const n = (v) => Number(v || 0).toLocaleString('en-US');
      const REPO = 'https://github.com/manvendersingh21/tremor-core/blob/dev/';
      const paint = async () => {
        try {
          const M = window.ChimeraMode, demo = !M || (await M.detect()) === 'demo';
          const [st, rs] = await Promise.all([M ? M.stats() : fetch('/api/stats', { cache: 'no-store' }).then((r) => r.json()), fetch(`${site}results.json`).then((r) => r.json())]);
          const gg = st.global && st.global.calls ? st.global : st.session || {};
          const from = demo || st.source ? `Saved run: <a href="${REPO}bench/results_backend.csv" target="_blank" rel="noopener">${esc(st.source || 'bench/results_backend.csv')}</a>` : 'Live: every call on this machine (/api/stats)';
          b.innerHTML = `<h3>Savings board</h3><dl><dt>Tokens kept off the big model</dt><dd class="m-big">${n(gg.tokens_kept_off_big)}</dd><dt>Dollars saved</dt><dd>$${Number(gg.dollars_saved || 0).toFixed(4)} <small>(spent $${Number(gg.dollars_spent || 0).toFixed(4)})</small></dd><dt>Calls, cache hit rate</dt><dd>${n(gg.calls)}, ${Math.round((gg.hit_rate || 0) * 100)}%</dd></dl>` +
            `<p class="m-from">${from}</p><p>Best measured: ${esc(rs.headlines.repeat_tokens_off)} fewer 763B tokens on a repeat question <a href="${REPO}bench/results_backend.md" target="_blank" rel="noopener">bench/results_backend.md</a></p>`;
        } catch (e) { if (!b.querySelector('dl')) b.innerHTML = '<h3>Savings board</h3><p>The numbers did not load. The rooms still show every saved result.</p>'; }
      };
      paint(); boardTimer = setInterval(paint, 5000);
    }
    $('m-doors').addEventListener('click', (e) => { const b = e.target.closest('.m-door'); if (b) { S.door = +b.dataset.k; openRoom(doors[S.door]); } });

    /* ---------- rooms: the gold door swings open, you step in, the room's painting and its numbers ---------- */
    let opening = false;
    async function openRoom(d) {
      if (!d || S.panel || opening) return;
      const wd = world.roomDoors[ORDER.indexOf(d.id)]; opening = true; S.door = doors.indexOf(d);
      if (wd) {                                         // turn to face it, then it opens
        const z = zNow(), want = Math.atan2(-wd.at.x, -(wd.at.z - z)); S.aim = { yaw: want, pitch: -0.02 };
        await new Promise((r) => setTimeout(r, S.tour ? 350 : 420)); wd.want = 1; creak();
        await new Promise((r) => setTimeout(r, S.tour ? 450 : 650));
      }
      fade(); S.aim = null; opening = false;
      S.room = d; $('m-where').textContent = d.title;
      openPanel(d.title, (pb) => window.MoviePanels.room(pb, d, { site }), { art: d.art, clip: d.clip !== false ? `${site}game/clips/room-${d.id}.mp4` : null });
    }
    function leaveRoom() {
      if (!S.room) return; const wd = world.roomDoors[ORDER.indexOf(S.room.id)]; if (wd) wd.want = 0;
      S.room = null; $('m-where').textContent = SEGS[S.seg].where;
    }

    /* ---------- panels and the map ---------- */
    let closeHook = null;
    function openPanel(title, fill, look = {}) {
      S.panel = true; S.keys.clear(); S.walking = 0; if (document.pointerLockElement) document.exitPointerLock();
      $('m-ptitle').textContent = title; const pb = $('m-pbody'); pb.textContent = ''; pb.removeAttribute('style'); pb.className = 'm-pb';
      const bg = $('m-pbg'), panel = $('m-panel');
      panel.dataset.kind = look.kind || 'room';
      bg.style.backgroundImage = look.art ? `url(${site}art/${look.art}.webp)` : '';
      bg.querySelectorAll('video').forEach((v) => v.remove());
      if (look.clip) {                                  // the room's own painted clip moves behind its numbers, if it was made
        fetch(look.clip, { method: 'HEAD' }).then((r) => { if (!r.ok || !S.panel) return; const v = document.createElement('video'); v.muted = true; v.loop = true; v.playsInline = true; v.autoplay = true; v.src = look.clip; bg.prepend(v); v.play().catch(() => {}); }).catch(() => {});
      }
      panel.hidden = false; closeHook = fill(pb) || null; $('m-pclose').focus();
    }
    function closePanel() {
      if (!S.panel) return; if (typeof closeHook === 'function') closeHook(); closeHook = null;
      $('m-pbody').textContent = ''; $('m-pbg').querySelectorAll('video').forEach((v) => v.remove()); $('m-panel').hidden = true; S.panel = false;
      if (S.room) leaveRoom(); gl.focus();
    }
    $('m-pclose').addEventListener('click', closePanel);
    function talk() { if (!S.panel) openPanel('Count Cuspid’s study', (pb) => window.MoviePanels.chat(pb, { site }), { kind: 'chat', art: 'study-chat' }); }
    $('m-talkbtn').addEventListener('click', talk);
    function stops() { return SEGS.map((s, k) => ({ k, where: s.where })); }
    function openMap() {
      if (S.panel) return; S.map = true; if (document.pointerLockElement) document.exitPointerLock();
      const here = S.room ? -1 : S.seg;
      $('m-mlist').innerHTML = stops().map(({ k, where }) => `<li class="${k === here && !S.hall ? 'here' : ''}"><button type="button" data-seg="${k}"><b>${k + 1}</b>${esc(where)}</button></li>`).join('') +
        doors.map((d, k) => `<li class="${S.room && S.room.id === d.id ? 'here' : ''}"><button type="button" data-door="${k}"><b>${String.fromCharCode(65 + k)}</b>${esc(d.title)}</button></li>`).join('');
      $('m-map').hidden = false; drawBig(); $('m-mlist').querySelector('button').focus();
    }
    function closeMap() { S.map = false; $('m-map').hidden = true; gl.focus(); }
    $('m-mapbtn').addEventListener('click', openMap); $('m-mclose').addEventListener('click', closeMap);
    $('m-mlist').addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return; closeMap();
      if (b.dataset.door != null) { jump(SEGS.length - 1, true); enterHall(); S.door = +b.dataset.door; openRoom(doors[S.door]); return; }
      jump(+b.dataset.seg, false);
    });
    function jump(i, end) {
      fade(); if (S.panel) closePanel(); if (S.room) S.room = null;
      const s = SEGS[i] || SEGS[0];
      for (let k = 0; k < SEGS.length; k++) if (SEGS[k].lock) { const past = k < i || (k === i && end), l = SEGS[k].lock; S.open[l] = past; S.anim[l] = past ? 1 : 0; }   // ahead of you: shut again
      S.s = end ? s.s1 - 0.005 : s.s0; S.yaw = 0; S.pitch = -0.02;
      if (end && i === SEGS.length - 1) { S.s = S_HALL + 0.01; enterHall(); } else if (S.hall) leaveHall();
      syncSeg();
    }
    function fade() { const f = $('m-fade'); f.classList.add('on'); setTimeout(() => f.classList.remove('on'), 380); }

    /* ---------- input: keys, mouse look (pointer lock or drag), touch look, the stick ---------- */
    const typing = (t) => t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName);
    addEventListener('keydown', (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === 'escape') { if (S.map) closeMap(); else if (S.panel) closePanel(); return; }
      if (typing(e.target) || S.panel || S.map) return;
      if (k === 'm') { openMap(); return; }
      if (k === 'c') { e.preventDefault(); talk(); return; }
      if (k === 't') { e.preventDefault(); if (window.CastleTour) window.CastleTour.toggle(); return; }
      if ((k === 'e' || k === 'enter') && !e.repeat && !(k === 'enter' && /^(BUTTON|A)$/.test(e.target.tagName))) { e.preventDefault(); use(); return; }
      if ('wasd'.includes(k) || k.startsWith('arrow') || k === 'shift') { S.keys.add(k); e.preventDefault(); }
    });
    addEventListener('keyup', (e) => { S.keys.delete(e.key.toLowerCase()); });
    addEventListener('blur', () => S.keys.clear());
    const look = (dx, dy) => { S.aim = null; S.yaw = angle(S.yaw - dx * 0.0032); S.pitch = clamp(S.pitch - dy * 0.0028, -1.2, 1.2); };
    let drag = null;
    gl.addEventListener('pointerdown', (e) => {
      if (e.pointerType === 'mouse' && !touch && gl.requestPointerLock && !document.pointerLockElement) { try { const r = gl.requestPointerLock(); if (r && r.catch) r.catch(() => {}); } catch (er) { /* drag still works */ } }
      drag = { id: e.pointerId, x: e.clientX, y: e.clientY }; try { gl.setPointerCapture(e.pointerId); } catch (er) { /* the pointer is locked: no capture needed */ }
    });
    gl.addEventListener('pointermove', (e) => {
      const locked = document.pointerLockElement === gl;
      if (locked && (e.movementX || e.movementY)) { look(e.movementX, e.movementY); if (drag) { drag.x = e.clientX; drag.y = e.clientY; } return; }
      if (drag && e.pointerId === drag.id) { look((e.clientX - drag.x) * (touch ? 1.6 : 1), (e.clientY - drag.y) * (touch ? 1.6 : 1)); drag.x = e.clientX; drag.y = e.clientY; }
    });
    const dragEnd = () => { drag = null; };
    gl.addEventListener('pointerup', dragEnd); gl.addEventListener('pointercancel', dragEnd);
    document.addEventListener('pointerlockchange', () => root.classList.toggle('m-locked', document.pointerLockElement === gl));
    const joy = $('m-joy'); let jid = null;
    const jm = (e) => { const r = joy.getBoundingClientRect(), dx = e.clientX - (r.left + 60), dy = e.clientY - (r.top + 60), d = Math.min(1, Math.hypot(dx, dy) / 50), a = Math.atan2(dy, dx); S.joy.x = d < 0.2 ? 0 : Math.cos(a) * d; S.joy.y = d < 0.2 ? 0 : Math.sin(a) * d; joy.firstElementChild.style.transform = `translate(${Math.cos(a) * d * 40}px,${Math.sin(a) * d * 40}px)`; };
    joy.addEventListener('pointerdown', (e) => { jid = e.pointerId; joy.setPointerCapture(jid); jm(e); });
    joy.addEventListener('pointermove', (e) => { if (e.pointerId === jid) jm(e); });
    const je = () => { jid = null; S.joy.x = S.joy.y = 0; joy.firstElementChild.style.transform = ''; };
    joy.addEventListener('pointerup', je); joy.addEventListener('pointercancel', je);
    $('m-act').addEventListener('click', use);

    /* ---------- sound: a creak when a gate or door opens, a clang when it shuts (after your first key) ---------- */
    let ac = null;
    function tone(f0, f1, f2, len, q, vol) {
      try {
        ac = ac || new (window.AudioContext || window.webkitAudioContext)();
        const o = ac.createOscillator(), f = ac.createBiquadFilter(), v = ac.createGain(), t = ac.currentTime;
        o.type = 'sawtooth'; o.frequency.setValueAtTime(f0, t); o.frequency.linearRampToValueAtTime(f1, t + len * 0.35); o.frequency.linearRampToValueAtTime(f2, t + len);
        f.type = 'bandpass'; f.frequency.value = 600; f.Q.value = q;
        v.gain.setValueAtTime(0.0001, t); v.gain.exponentialRampToValueAtTime(vol, t + 0.05); v.gain.exponentialRampToValueAtTime(0.0001, t + len);
        o.connect(f); f.connect(v); v.connect(ac.destination); o.start(); o.stop(t + len + 0.05);
      } catch (e) { /* sound waits for a key press */ }
    }
    const creak = () => tone(70, 140, 55, 1.6, 8, 0.1), clang = () => tone(220, 120, 60, 0.5, 3, 0.14);
    function say(t) { $('m-saytext').textContent = touch ? String(t).replace('Hold W and walk', 'Push the stick up and walk').replace(/Look at one and press E, or click its sign\.|Look at one and press E\./, 'Tap a sign to open it.') : t; }

    /* ---------- bats round the moon (2D, over the 3D sky), a vignette ---------- */
    let FW = 0, FH = 0;
    function resize() {
      const w = root.clientWidth || innerWidth, h = root.clientHeight || innerHeight, k = Math.min(devicePixelRatio || 1, 1.25);
      world.resize(w, h); FW = fx.width = Math.round(w * k); FH = fx.height = Math.round(h * k);
      const box = $('m-doors'); if (S.hall) { box.classList.toggle('m-arcade', touch || innerWidth < 700); box.classList.toggle('m-signs', !(touch || innerWidth < 700)); if (box.classList.contains('m-arcade')) box.querySelectorAll('.m-door').forEach((b) => { b.style.transform = ''; b.style.visibility = ''; }); }
      sizeMini();
    }
    addEventListener('resize', resize);
    const bats = Array.from({ length: 110 }, (_, i) => {
      const depth = i < 70 ? 0 : i < 100 ? 1 : 2;
      return { depth, size: [5 + rnd() * 4, 11 + rnd() * 7, 22 + rnd() * 18][depth], r: [0.05 + rnd() * 0.2, 0.1 + rnd() * 0.3, 0.2 + rnd() * 0.45][depth], a: rnd() * 6.3,
        w: (rnd() > 0.5 ? 1 : -1) * [0.18 + rnd() * 0.25, 0.12 + rnd() * 0.18, 0.08 + rnd() * 0.1][depth], e: 0.35 + rnd() * 0.5, wob: rnd() * 6.3, flap: 9 + rnd() * 7, ph: rnd() * 6.3,
        cx: (rnd() - 0.5) * [0.3, 0.7, 1.2][depth], cy: (rnd() - 0.5) * [0.18, 0.3, 0.4][depth] };
    });
    function bat(x, y, s, flap, alpha, tilt) {
      const up = Math.sin(flap) * 0.9;
      g.save(); g.translate(x, y); g.rotate(tilt); g.scale(s / 30, s / 30); g.globalAlpha = alpha; g.fillStyle = '#0c0410';
      g.beginPath(); g.moveTo(0, -2); g.quadraticCurveTo(-8, -10 - up * 12, -30, -6 - up * 16); g.quadraticCurveTo(-22, -1, -20, 4); g.quadraticCurveTo(-14, 0, -11, 6); g.quadraticCurveTo(-6, 2, -3, 7);
      g.lineTo(3, 7); g.quadraticCurveTo(6, 2, 11, 6); g.quadraticCurveTo(14, 0, 20, 4); g.quadraticCurveTo(22, -1, 30, -6 - up * 16); g.quadraticCurveTo(8, -10 - up * 12, 0, -2); g.fill();
      g.beginPath(); g.ellipse(0, 1, 3.4, 6, 0, 0, 7); g.fill(); g.restore(); g.globalAlpha = 1;
    }
    function drawFx() {
      g.clearRect(0, 0, FW, FH);
      const R = Math.min(FW, FH), k = FW / (root.clientWidth || innerWidth);
      if (zNow() > PLAN.hallZ0 + 0.5 && !S.room) {      // outside: the flock circles the moon, wherever it is on screen
        const m = world.moonScreen();
        if (m.front) {
          const mx = m.x * k, my = m.y * k;
          for (const b of bats) {
            const a = b.a + S.time * b.w, wob = Math.sin(S.time * 0.7 + b.wob);
            const x = mx + (b.cx + Math.cos(a) * b.r * (1 + 0.25 * wob)) * R * 1.1, y = my + (b.cy + Math.sin(a) * b.r * b.e + Math.sin(S.time * 1.3 + b.ph) * 0.02) * R;
            bat(x, y, b.size * (R / 900), S.time * b.flap + b.ph, [0.55, 0.8, 0.95][b.depth], Math.cos(a) * 0.3 * Math.sign(b.w));
          }
        }
      } else if (!S.room) {                              // inside: a few bats under the vault
        for (const b of bats.slice(0, 7)) { const a = b.a + S.time * b.w * 0.6; bat(FW * 0.5 + Math.cos(a) * FW * 0.32, FH * 0.14 + Math.sin(a) * FH * 0.05, b.size * 0.7 * (R / 900), S.time * b.flap + b.ph, 0.6, 0); }
      }
      const vg = g.createRadialGradient(FW / 2, FH / 2, FH * 0.42, FW / 2, FH / 2, FH * 0.98); vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, 'rgba(6,2,12,.5)'); g.fillStyle = vg; g.fillRect(0, 0, FW, FH);
    }

    /* ---------- the painted map: parchment, ink, gold; you are a glowing dot with a cone where you look ---------- */
    const mini = $('m-mini'), mg = mini.getContext('2d'), big = $('m-bigmap'), bg2 = big.getContext('2d');
    const parch = new Image(); parch.src = site + 'art/parchment-paper.webp';
    const VIEW = { x0: -24, x1: 24, z0: 12, z1: -88 };
    function sizeMini() {
      const r = mini.getBoundingClientRect(), k = Math.min(devicePixelRatio || 1, 2);
      if (r.width) { mini.width = Math.round(r.width * k); mini.height = Math.round(r.height * k); }
    }
    function plan(c, w, h, bigMap) {
      const xs = bigMap ? 42 : 24, sc = Math.min(w / (2 * xs), h / (VIEW.z0 - VIEW.z1)) * 0.96, ox = w / 2, oy = (h - (VIEW.z0 - VIEW.z1) * sc) / 2;
      const P = (x, z) => [ox + x * sc, oy + (z - VIEW.z1) * sc], u = w / 200;   // the castle at the top: you walk up the map
      c.clearRect(0, 0, w, h);
      if (parch.complete && parch.naturalWidth) { c.drawImage(parch, 0, 0, w, h); c.fillStyle = 'rgba(70,40,20,.10)'; c.fillRect(0, 0, w, h); }
      else { c.fillStyle = '#e6d3ac'; c.fillRect(0, 0, w, h); }
      const ink = '#3d2410', gold = '#a8741e', wine = '#6e1426';
      c.lineCap = 'round'; c.lineJoin = 'round';
      // trees: little ink pines in the grounds
      c.fillStyle = 'rgba(61,36,16,.42)';
      for (let i = 0; i < (bigMap ? 70 : 34); i++) { const x = ((i * 37) % 48) - 24, z = 11 - ((i * 53) % 30); if (Math.abs(x) < 6) continue; const [px, py] = P(x, z), s = 2.2 * u; c.beginPath(); c.moveTo(px, py - s * 1.8); c.lineTo(px + s, py + s * 0.6); c.lineTo(px - s, py + s * 0.6); c.fill(); }
      // the road and the drive, lanterns as gold dots
      let [a, b] = P(-2.3, 12), [a2, b2] = P(2.3, PLAN.doorZ);
      c.fillStyle = 'rgba(120,84,48,.35)'; c.fillRect(a, b, a2 - a, b2 - b);
      c.strokeStyle = ink; c.lineWidth = 1.1 * u; c.setLineDash([3 * u, 2.5 * u]); c.beginPath(); c.moveTo(...P(-2.3, 12)); c.lineTo(...P(-2.3, PLAN.doorZ)); c.moveTo(...P(2.3, 12)); c.lineTo(...P(2.3, PLAN.doorZ)); c.stroke(); c.setLineDash([]);
      c.fillStyle = gold; for (const z of world.plan.lanterns) for (const x of [-2.9, 2.9]) { const [px, py] = P(x, z); c.beginPath(); c.arc(px, py, 1.6 * u, 0, 7); c.fill(); }
      // the fence and the gates (open or shut)
      c.strokeStyle = ink; c.lineWidth = 1.6 * u; c.beginPath(); c.moveTo(...P(-24, 0)); c.lineTo(...P(-PLAN.gateHalf - 0.5, 0)); c.moveTo(...P(PLAN.gateHalf + 0.5, 0)); c.lineTo(...P(24, 0)); c.stroke();
      const ga = S.anim.gates * 1.4;
      c.strokeStyle = S.open.gates ? gold : wine; c.lineWidth = 2.4 * u;
      for (const side of [-1, 1]) { const [hx, hy] = P(side * PLAN.gateHalf, 0); c.beginPath(); c.moveTo(hx, hy); c.lineTo(hx - side * Math.cos(ga) * PLAN.gateHalf * sc, hy - Math.sin(ga) * PLAN.gateHalf * sc); c.stroke(); }
      c.fillStyle = ink; for (const side of [-1, 1]) { const [px, py] = P(side * (PLAN.gateHalf + 0.5), 0); c.fillRect(px - 2 * u, py - 2 * u, 4 * u, 4 * u); }
      // the castle: towers, the front wall, the great door
      c.fillStyle = 'rgba(61,36,16,.10)'; c.strokeStyle = 'rgba(61,36,16,.55)'; c.lineWidth = 1 * u;
      [a, b] = P(-PLAN.facadeHalf, PLAN.doorZ); [a2, b2] = P(PLAN.facadeHalf, PLAN.doorZ - 2.2); c.fillRect(a, b, a2 - a, b2 - b); c.strokeRect(a, b, a2 - a, b2 - b);
      for (const [x, z, r] of world.plan.towers) { const [px, py] = P(x, z); c.beginPath(); c.arc(px, py, r * sc, 0, 7); c.fill(); c.stroke(); }
      // the hall: purple floor, columns, red carpet
      [a, b] = P(-PLAN.hallHalf, PLAN.hallZ0); [a2, b2] = P(PLAN.hallHalf, PLAN.hallZ1);
      c.fillStyle = 'rgba(78,38,98,.30)'; c.fillRect(a, b, a2 - a, b2 - b); c.lineWidth = 2 * u; c.strokeStyle = ink; c.strokeRect(a, b, a2 - a, b2 - b);
      [a, b] = P(-1.7, PLAN.hallZ0); [a2, b2] = P(1.7, PLAN.hallZ1 + 0.5); c.fillStyle = 'rgba(110,20,38,.55)'; c.fillRect(a, b, a2 - a, b2 - b);
      c.fillStyle = ink; for (let z = PLAN.hallZ0 - 4; z > PLAN.hallZ1 + 2; z -= 6) for (const x of [-6.2, 6.2]) { const [px, py] = P(x, z); c.beginPath(); c.arc(px, py, 0.65 * sc, 0, 7); c.fill(); }
      const da = S.anim.door * 1.4; c.strokeStyle = S.open.door ? gold : wine; c.lineWidth = 2.6 * u;
      for (const side of [-1, 1]) { const [hx, hy] = P(side * PLAN.doorHalf, PLAN.doorZ); c.beginPath(); c.moveTo(hx, hy); c.lineTo(hx - side * Math.cos(da) * PLAN.doorHalf * sc, hy - Math.sin(da) * PLAN.doorHalf * sc); c.stroke(); }
      // the room doors: gold arches; the one you look at glows; letters match the map list
      SLOTS.forEach((s, k) => {
        const di = doors.findIndex((d) => d.id === s.room), x = s.side ? s.side * PLAN.hallHalf : 0, z = s.side ? s.z : PLAN.hallZ1;
        const [px, py] = P(x, z), on = S.hall && di === S.door, r = (on ? 3.6 : 2.6) * u;
        if (on) { const gl2 = c.createRadialGradient(px, py, 0, px, py, r * 4); gl2.addColorStop(0, 'rgba(255,200,90,.85)'); gl2.addColorStop(1, 'rgba(255,200,90,0)'); c.fillStyle = gl2; c.beginPath(); c.arc(px, py, r * 4, 0, 7); c.fill(); }
        c.fillStyle = on ? '#e9b44a' : gold; c.strokeStyle = ink; c.lineWidth = 0.8 * u; c.beginPath(); c.arc(px, py, r, 0, 7); c.fill(); c.stroke();
        if (bigMap) {
          const t = doors[di] ? doors[di].title.replace(/^The /, '').replace(' and The ', ' & ') : s.room, lx = s.side < 0 ? px - 7 * u : s.side > 0 ? px + 7 * u : px;
          c.font = `700 ${Math.round(7.6 * u)}px Cinzel, Georgia, serif`; c.textAlign = s.side < 0 ? 'right' : s.side > 0 ? 'left' : 'center'; c.textBaseline = 'middle';
          const tx = `${String.fromCharCode(65 + di)}  ${t}`, ty = s.side ? py : py + 11 * u;   // outside the walls, so no label crosses the hall
          c.lineWidth = 3 * u; c.strokeStyle = 'rgba(240,226,196,.92)'; c.strokeText(tx, lx, ty); c.fillStyle = on ? wine : ink; c.fillText(tx, lx, ty);
        } else { c.fillStyle = '#2a1206'; c.font = `700 ${Math.round(4.6 * u)}px Inter, sans-serif`; c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText(String.fromCharCode(65 + di), px, py + 0.3 * u); }
      });
      // labels
      const label = (t, x, z, al = 'left', size = 9) => { const [px, py] = P(x, z); c.font = `700 ${Math.round(size * u)}px Cinzel, Georgia, serif`; c.textAlign = al; c.textBaseline = 'middle'; c.lineWidth = 3 * u; c.strokeStyle = 'rgba(240,226,196,.9)'; c.strokeText(t, px, py); c.fillStyle = ink; c.fillText(t, px, py); };
      label('Gates', 3.6, 1.6); label('Drive', 3.6, -8); label('Great door', 3.6, PLAN.doorZ + 2.2); label('Great Hall', 0, bigMap ? PLAN.hallZ0 - 3.5 : (PLAN.hallZ0 + PLAN.hallZ1) / 2 + 3, 'center', bigMap ? 9 : 9.5);
      if (bigMap) label('Start', 3.6, PLAN.start, 'left', 8);
      // you: a glowing dot and a cone where you look
      const [yx, yy] = P(0, zNow()), dir = Math.atan2(-Math.cos(S.yaw), -Math.sin(S.yaw)), cone = 0.55, L = (bigMap ? 30 : 22) * u;
      const cg = c.createRadialGradient(yx, yy, 0, yx, yy, L); cg.addColorStop(0, 'rgba(255,214,120,.75)'); cg.addColorStop(1, 'rgba(255,214,120,0)');
      c.fillStyle = cg; c.beginPath(); c.moveTo(yx, yy); c.arc(yx, yy, L, dir - cone, dir + cone); c.closePath(); c.fill();
      const pulse = 1 + 0.2 * Math.sin(S.time * 5), hg = c.createRadialGradient(yx, yy, 0, yx, yy, 9 * u * pulse); hg.addColorStop(0, 'rgba(255,240,180,1)'); hg.addColorStop(0.35, 'rgba(255,190,70,.9)'); hg.addColorStop(1, 'rgba(255,150,40,0)');
      c.fillStyle = hg; c.beginPath(); c.arc(yx, yy, 9 * u * pulse, 0, 7); c.fill();
      c.fillStyle = '#7a1a2e'; c.beginPath(); c.arc(yx, yy, 2.6 * u, 0, 7); c.fill(); c.strokeStyle = '#fff3d0'; c.lineWidth = 1 * u; c.stroke();
    }
    function drawMini() {
      if (!mini.width) sizeMini(); plan(mg, mini.width, mini.height, false);
      const at = $('m-mini-at'), t = S.room ? S.room.title : S.hall && doors[S.door] ? 'Looking at: ' + doors[S.door].title : SEGS[S.seg].where;
      if (at.textContent !== t) at.textContent = t;
    }
    function drawBig() {
      const r = big.getBoundingClientRect(), k = Math.min(devicePixelRatio || 1, 2); big.width = Math.round(r.width * k); big.height = Math.round(r.height * k);
      plan(bg2, big.width, big.height, true);
    }

    /* ---------- the loop ---------- */
    let last = performance.now(), fN = 0, fT = 0;
    function frame(now) {
      const dt = Math.min(0.05, (now - last) / 1000); last = now; S.time += dt;
      const k = S.keys, free = !S.panel && !S.map && !opening;
      const f = (k.has('w') || k.has('arrowup') ? 1 : 0) - (k.has('s') || k.has('arrowdown') ? 1 : 0) - S.joy.y;
      const turn = (k.has('d') || k.has('arrowright') ? 1 : 0) - (k.has('a') || k.has('arrowleft') ? 1 : 0) + (Math.abs(S.joy.x) > 0.35 ? S.joy.x : 0);
      if (free && Math.abs(f) > 0.3) walk(dt, f, k.has('shift')); else S.walking = 0;
      if (free && turn) { S.aim = null; S.yaw = angle(S.yaw - turn * dt * 1.9); }
      if (S.aim) { S.yaw += angle(S.aim.yaw - S.yaw) * Math.min(1, dt * 6); S.pitch += (S.aim.pitch - S.pitch) * Math.min(1, dt * 6); }
      for (const l of ['gates', 'door']) S.anim[l] = clamp(S.anim[l] + (S.open[l] ? 1 : -1) * dt * (l === 'gates' ? 2.8 : 2.3), 0, 1);
      const sg = syncSeg();
      if (S.seg !== lastSeg) { lastSeg = S.seg; if (!S.room) $('m-where').textContent = sg.where; if (!S.tour && !S.hall) say(sg.say); }
      // what you look at
      S.target = free ? findTarget() : null;
      const gaze = S.target && S.target.kind === 'room' ? S.target.k : -1;
      if (S.hall && !S.tour && gaze >= 0 && gaze !== lastGaze) S.door = gaze;   // a new door in view becomes the chosen one
      lastGaze = gaze;
      world.roomDoors.forEach((d) => { d.sel = 0; }); if (S.hall) { const wd = world.roomDoors[ORDER.indexOf(doors[S.door] && doors[S.door].id)]; if (wd) wd.sel = 1; }
      const box = $('m-doors');
      box.querySelectorAll('.m-door').forEach((b, i) => { const on = i === S.door; if (on && !b.classList.contains('sel') && box.classList.contains('m-arcade')) box.scrollTo({ left: b.offsetLeft - 8, behavior: 'smooth' }); b.classList.toggle('sel', on); });
      world.setOpen(S.anim.gates, S.anim.door);
      const bob = S.walking ? Math.sin(S.time * (k.has('shift') ? 14 : 10)) * 0.035 : 0;
      world.render({ x: 0, y: 1.7 + bob, z: zNow(), yaw: S.yaw, pitch: S.pitch }, S.time);
      root.classList.toggle('m-inhall', S.hall);
      placeSigns(); placeBubble(); drawFx(); drawMini();
      prompt();
      fN++; fT += dt; if (fT >= 1) { S.fps.push(fN / fT); if (S.fps.length > 120) S.fps.shift(); $('m-fps').textContent = Math.round(fN / fT) + ' fps'; fN = 0; fT = 0; }
      requestAnimationFrame(frame);
    }
    function prompt() {
      const pr = $('m-prompt'), t = S.target; let h = '';
      if (S.panel || S.map) h = '';
      else if (!S.walking && S.s < 0.05) h = touch ? 'Push the stick up to walk to the castle · drag to look around' : 'Hold <kbd>W</kbd> to walk to the castle · drag or click to look around';
      else if (t && t.kind === 'room') h = touch ? `Tap the gold sign of ${esc(doors[t.k] ? doors[t.k].title : '')} to open it` : `<kbd>E</kbd> open ${esc(doors[t.k] ? doors[t.k].title : '')}`;
      else if (t && (t.kind === 'gates' || t.kind === 'door')) {
        const z = zNow(), pz = t.kind === 'gates' ? PLAN.gateZ : PLAN.doorZ, behind = z < pz;
        if (S.open[t.kind] && !S.walking && (behind || Math.abs(z - pz) > 1.2)) h = `<kbd>E</kbd> close ${NAME[t.kind]}${behind ? ' behind you' : ''}`;
        else if (!S.open[t.kind] && !S.walking) h = behind ? `<kbd>E</kbd> open ${NAME[t.kind]}, or walk back to ${t.kind === 'gates' ? 'them' : 'it'}` : `Walk up and ${NAME[t.kind]} open${t.kind === 'gates' ? '' : 's'} · <kbd>E</kbd> opens now`;
      }
      if (!h && !S.panel && !S.map && !S.walking && S.s < 0.05) h = touch ? 'Push the stick up to walk to the castle · drag to look around' : 'Hold <kbd>W</kbd> to walk to the castle · drag or click to look around';
      if (!h && S.hall && !S.panel && !S.walking) h = touch ? 'Tap a gold sign to open its room' : 'Look at a gold door and press <kbd>E</kbd> · <kbd>W</kbd> walks on down the hall';
      if (touch) h = h.replace(/<kbd>E<\/kbd>/g, 'Tap E:');
      if (pr.dataset.h !== h) { pr.dataset.h = h; pr.innerHTML = h; }
      pr.classList.toggle('on', !!h);
    }
    function placeBubble() {
      const say = $('m-say'), p = world.project(world.counts[S.hall || zNow() < PLAN.doorZ ? 1 : 0]);
      const on = !S.panel && !S.map && p.front && p.dist < 18 && p.dist > 1.2 && innerWidth > 520 && p.x > 40 && p.x < innerWidth - 40 && p.y > 60;
      say.classList.toggle('m-attached', on);
      if (on) {
        const right = p.x + 330 < innerWidth;
        say.style.left = (right ? p.x + 24 : p.x - 24 - Math.min(320, say.offsetWidth)) + 'px';
        say.style.top = Math.max(64, p.y - say.offsetHeight * 0.6) + 'px';
        say.classList.toggle('m-tail-r', !right);
      } else { say.style.left = ''; say.style.top = ''; }
    }
    resize();
    requestAnimationFrame(frame);
    if (window.ChimeraMode) window.ChimeraMode.badge($('m-mode')); else $('m-mode').remove();
    $('m-tourbtn').addEventListener('click', () => { if (window.CastleTour) window.CastleTour.toggle(); });
    say(SEGS[0].say); $('m-where').textContent = SEGS[0].where;
    gl.focus();
    const api = { state: S, have, segs: SEGS, doors, use, talk, openMap, jump, enterHall, closePanel, openRoom, say, world,
      fps: () => S.fps.slice(), look: (dyaw, dpitch) => { S.yaw = angle(S.yaw + dyaw); S.pitch = clamp(S.pitch + (dpitch || 0), -1.2, 1.2); }, z: zNow, railS };
    window.MovieGame = api;
    return api;
  }
  window.MovieGameStart = start;
})();
