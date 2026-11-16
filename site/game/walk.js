/* CHIMERA, the walk-in movie game. YOU are the camera.
   The walk is a chain of painted video clips (site/game/clips/*.mp4, made by scripts/gen_video.py; each starts on the
   last frame of the one before). W plays it forward under your feet, S walks it back, Shift runs. A/D and the mouse
   turn your head (the frame is wider than the screen). E opens gates and doors. Live layers on top: a 120-bat flock,
   fog, fireflies, candle glow, the Count's bubble, door signs as real text, and the minimap. Never paused.
   If a clip is missing, that stretch is a slow painted dolly over its keyframe instead. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const rnd = (() => { let s = 7; return () => ((s = (s * 16807) % 2147483647) / 2147483647); })();

  /* The walk, in order. secs: how long the stretch takes at walking speed (Shift doubles it), whatever its clip's
     length: a clip is sped up to fit (playbackRate), win picks the part of a clip that is used.
     lock: a gate or door that is closed until you reach it, then opens by itself (E opens it too).
     clip: false = keep the painted stretch even if a clip lands. c-drive.mp4 (2026-11-15) stays at the gates and never
     walks up to the door; d-door and e-hall clips are planned to end on the old hall.webp, not the hall painted now. */
  const SEGS = [
    // fb: the painted dolly used while a clip is not made yet: [zoom, focus x, focus y] at the start and the end
    { id: 'a-approach', secs: 1.35, where: 'Before the iron gates', key: 'art/gate.webp', fb: [[1, 0.5, 0.62], [1.7, 0.5, 0.7]], say: 'Good evening. Hold W to walk up to the gates.' },
    { id: 'b-gates', secs: 0.8, win: [0, 2.4], where: 'Through the iron gates', key: 'game/clips/a-approach-last.jpg', fb: [[1, 0.5, 0.55], [2.4, 0.5, 0.5]], lock: 'gates', gate: true, say: 'The gates know me. Keep walking.' },
    { id: 'c-drive', secs: 0.7, clip: false, where: 'The lantern drive', key: 'art/drive.webp', fb: [[1, 0.5, 0.56], [3.3, 0.5, 0.485]], say: 'Follow the lanterns. The door is at the top.' },
    { id: 'd-door', secs: 0.5, clip: false, where: 'The great door', key: 'art/drive.webp', fb: [[3.3, 0.5, 0.485], [3.3, 0.5, 0.485]], lock: 'door', rig: true, say: 'The door opens for you. Step inside.' },
    { id: 'e-hall', secs: 0.4, clip: false, where: 'The Great Hall', key: 'art/hall-grand-1.webp', fb: [[1, 0.5, 0.6], [1.08, 0.5, 0.62]], say: 'Every door is a room. Pick one with A and D, then press E.' },
  ];
  const LOCK_AT = { gates: 'Open the iron gates', door: 'Open the great door' };

  async function start(root, opts = {}) {
    const site = opts.site || '';
    const touch = matchMedia('(pointer: coarse)').matches;   // phones: the stick and taps, not keys
    const ROOMS = window.ROOMS || [];
    const ORDER = (window.MovieScene && window.MovieScene.ORDER) || [];   // the hall's painted doors, in A/D order
    const rank = (id) => { const k = ORDER.indexOf(id); return k < 0 ? 99 : k; };
    const doors = ROOMS.map((r) => ({ id: r.id, title: r.title, sub: r.door, art: r.art || 'room-' + r.id })).sort((a, b) => rank(a.id) - rank(b.id));

    root.innerHTML = `
      <div class="m-stage" id="m-stage"><video id="m-v0" muted playsinline preload="auto"></video><video id="m-v1" muted playsinline preload="auto"></video><img id="m-img" alt=""></div>
      <canvas id="m-fx" aria-hidden="true"></canvas>
      <div class="m-doors" id="m-doors" hidden></div>
      <aside class="m-board" id="m-board" hidden aria-label="Savings board"></aside>
      <div class="m-bar"><span id="m-mode" class="mode-badge" role="status">…</span><span id="m-where"></span><span id="m-fps" class="m-fps"></span>
        <button class="m-btn m-gold" id="m-tourbtn" type="button">Tour<span class="m-k"> (T)</span></button><button class="m-btn" id="m-mapbtn" type="button">Map<span class="m-k"> (M)</span></button><button class="m-btn" id="m-talkbtn" type="button">Talk<span class="m-k"> to the Count (C)</span></button></div>
      <div class="m-prompt" id="m-prompt"></div>
      <div class="m-say" id="m-say"><b>Count Cuspid</b><span id="m-saytext"></span><small>Press <kbd>C</kbd> to talk to me · <kbd>T</kbd> for a tour</small></div>
      <canvas id="m-mini" width="180" height="130" aria-hidden="true"></canvas>
      <div class="m-help"><kbd>W</kbd> walk · <kbd>S</kbd> back · <kbd>Shift</kbd> run · <kbd>A</kbd><kbd>D</kbd>/mouse look · <kbd>E</kbd> open · <kbd>T</kbd> tour · <kbd>C</kbd> talk · <kbd>M</kbd> map · <kbd>Esc</kbd> leave</div>
      <div class="m-joy" id="m-joy"><i></i></div><button class="m-act" id="m-act" type="button" aria-label="Open">E</button>
      <section class="m-panel" id="m-panel" role="dialog" aria-modal="true" aria-labelledby="m-ptitle" hidden>
        <div class="m-ph"><h2 id="m-ptitle"></h2><button class="m-btn" id="m-pclose" type="button">Leave (Esc)</button></div>
        <div class="m-pb" id="m-pbody"></div></section>
      <div class="m-map" id="m-map" hidden><div role="dialog" aria-modal="true" aria-labelledby="m-mtitle"><h2 id="m-mtitle">The way in</h2><ol id="m-mlist"></ol><button class="m-btn" id="m-mclose" type="button">Close (Esc)</button></div></div>
      <div class="m-fade" id="m-fade"></div>`;
    const vids = [$('m-v0'), $('m-v1')], still = $('m-img'), stage = $('m-stage');
    const scene = window.MovieScene ? window.MovieScene.create(root, { site }) : null;   // the Count in the scene, path lights, hall (scene.js)
    const fx = $('m-fx'), g = fx.getContext('2d'), mini = $('m-mini').getContext('2d');

    /* ---------- clips: which exist ---------- */
    const have = {};
    await Promise.all(SEGS.map(async (s) => { if (s.clip === false) { have[s.id] = false; return; } try { const r = await fetch(`${site}game/clips/${s.id}.mp4`, { method: 'HEAD' }); have[s.id] = r.ok; } catch (e) { have[s.id] = false; } }));

    SEGS.forEach((s) => { const im = new Image(); im.src = site + s.key; });   // no blank frame when a stretch starts
    const S = { seg: 0, t: 0, over: 1.12, open: {}, keys: new Set(), yaw: 0, pitch: 0, look: { x: 0, y: 0 }, room: null, panel: null, map: false,
      hall: false, door: 0, time: 0, fps: [], walking: 0, joy: { x: 0, y: 0 } };
    let active = 0;
    function vidFor(i) { return vids[i % 2]; }
    function load(i) {
      const s = SEGS[i]; if (!s) return;
      const v = vidFor(i);
      if (have[s.id] && !v.src.endsWith(`${s.id}.mp4`)) { v.src = `${site}game/clips/${s.id}.mp4`; v.load(); }
    }
    /* A stretch with no clip whose keyframe is the last frame of the clip before it: keep that clip's own video,
       paused on its last frame, and dolly it. A still of the same frame decodes with other colours (a visible seam). */
    function held(i) { const s = SEGS[i], p = SEGS[i - 1]; return !have[s.id] && p && have[p.id] && s.key.endsWith(`${p.id}-last.jpg`) ? vidFor(i - 1) : null; }
    function show(i) {
      const s = SEGS[i]; active = i;
      const h = held(i);
      load(i);
      if (h) { h.pause(); const end = () => { if (h.duration && h.duration - h.currentTime > 0.1) h.currentTime = h.duration - 0.04; }; h.readyState ? end() : h.addEventListener('loadedmetadata', end, { once: true }); }
      vids.forEach((v, k) => v.classList.toggle('on', (have[s.id] && k === i % 2) || v === h));
      still.classList.toggle('on', !have[s.id] && !h);
      if (!have[s.id] && !h) still.src = site + s.key;
      if (!h) load(i + 1);                           // preload the next stretch (not into the video we are holding)
      say(s.say); $('m-where').textContent = s.where;
    }
    load(0); show(0);

    /* S.t is walking time into the stretch (0..secs). A clip's own time is mapped onto it. */
    const dur = (i) => SEGS[i].secs;
    function win(i) { const s = SEGS[i], v = vidFor(i), d = v.duration || 8; return s.win ? [s.win[0], Math.min(s.win[1], d)] : [0, d]; }
    const clipAt = (i, t) => { const [a, b] = win(i); return a + (b - a) * clamp(t / dur(i), 0, 1); };
    function setTime(i, t) {
      S.t = clamp(t, 0, dur(i));
      if (have[SEGS[i].id]) { const v = vidFor(i), ct = clipAt(i, S.t); if (Math.abs(v.currentTime - ct) > 0.02 && !v.seeking) v.currentTime = ct; }
    }

    /* ---------- walking: W plays the clip under your feet (sped up to fit the stretch), S walks it back ---------- */
    function arrive(l) {                            // you reached a closed gate or door: it opens
      if (S.open[l]) return; S.open[l] = true; creak();
      say(l === 'gates' ? 'The gates swing open for you. Keep walking.' : 'The great door opens. Step inside.');
    }
    function walk(dt, dir, run) {
      if (S.panel || S.map || S.room) return;
      const i = S.seg, s = SEGS[i], speed = run ? 2 : 1;
      if (s.lock && !S.open[s.lock]) { if (dir > 0) arrive(s.lock); else if (S.t > 0) return; }
      let t;
      t = S.t + dir * dt * speed;                   // our clock sets the pace; the clip follows it
      if (dir > 0 && have[s.id]) {                  // forward: the decoder plays at the matching speed (smooth)
        const v = vidFor(i), [a, b] = win(i), ct = clipAt(i, t);
        v.playbackRate = clamp((b - a) / dur(i) * speed, 0.25, 8); if (v.paused) v.play().catch(() => {});
        if (Math.abs(v.currentTime - ct) > 0.45 && !v.seeking) v.currentTime = ct;   // a decoder that cannot keep up skips ahead
      } else if (have[s.id]) vidFor(i).pause();
      if (t >= dur(i) - 0.01 && dir > 0) {
        const nx = SEGS[i + 1];
        if (have[s.id]) vidFor(i).pause();
        if (!nx) { setTime(i, dur(i)); enterHall(); return; }
        if (nx.lock) arrive(nx.lock);               // the gate or door opens as you reach it, not before
        S.seg = i + 1; show(S.seg); setTime(S.seg, 0); S.walking = dir; return;
      }
      if (t <= 0 && dir < 0) {
        if (i === 0) { setTime(0, 0); return; }
        S.seg = i - 1; show(S.seg); setTime(S.seg, dur(S.seg) - 0.01); return;
      }
      if (dir < 0) setTime(i, t); else S.t = clamp(t, 0, dur(i));
      S.walking = dir;
    }
    function stopWalk() { const s = SEGS[S.seg]; if (have[s.id]) vidFor(S.seg).pause(); S.walking = 0; }

    /* ---------- E: gates, the door, a room ---------- */
    function pendingLock() {
      const i = S.seg, s = SEGS[i], nx = SEGS[i + 1];
      if (s.lock && !S.open[s.lock] && S.t < 0.1) return s.lock;
      if (nx && nx.lock && !S.open[nx.lock] && S.t >= dur(i) - 0.05) return nx.lock;
      return null;
    }
    function use() {
      if (S.panel || S.map) return;
      if (S.hall) { openRoom(doors[S.door]); return; }
      const l = pendingLock(); if (!l) return;
      arrive(l);
      if (S.seg < SEGS.length - 1 && SEGS[S.seg + 1].lock === l) { S.seg++; show(S.seg); setTime(S.seg, 0); }
    }

    /* ---------- the hall: gold-plated doors with real signs ---------- */
    function enterHall() {
      if (S.hall) return; S.hall = true; S.door = 0;
      const box = $('m-doors');
      box.innerHTML = doors.map((d, k) => `<button class="m-door" data-k="${k}" data-id="${esc(d.id)}" type="button"><span class="m-plaque"><strong>${esc(d.title)}</strong><span>${esc(d.sub || '')}</span></span></button>`).join('');
      if (scene) scene.layoutDoors(box);
      box.hidden = false; markDoor(); board(true);
      say('Every door is a room. Pick one with A and D, then press E.');
    }
    function leaveHall() { S.hall = false; $('m-doors').hidden = true; board(false); }
    /* the savings board: live totals from /api/stats, the best measured result from /results.json (read from bench/*.md) */
    let boardTimer = 0;
    function board(on) {
      const b = $('m-board'); b.hidden = !on; clearInterval(boardTimer); if (!on) return;
      const n = (v) => Number(v || 0).toLocaleString('en-US');
      const REPO = 'https://github.com/manvendersingh21/tremor-core/blob/dev/';
      const paint = async () => {
        try {
          const M = window.ChimeraMode, demo = !M || (await M.detect()) === 'demo';
          const [st, rs] = await Promise.all([M ? M.stats() : fetch('/api/stats', { cache: 'no-store' }).then((r) => r.json()), fetch(`${site}results.json`).then((r) => r.json())]);
          const g = st.global && st.global.calls ? st.global : st.session || {};
          const from = demo || st.source ? `Saved run: <a href="${REPO}bench/results_backend.csv" target="_blank" rel="noopener">${esc(st.source || 'bench/results_backend.csv')}</a>` : 'Live: every call on this machine (/api/stats)';
          b.innerHTML = `<h3>Savings board</h3><dl><dt>Tokens kept off the big model</dt><dd class="m-big">${n(g.tokens_kept_off_big)}</dd><dt>Dollars saved</dt><dd>$${Number(g.dollars_saved || 0).toFixed(4)} <small>(spent $${Number(g.dollars_spent || 0).toFixed(4)})</small></dd><dt>Calls, cache hit rate</dt><dd>${n(g.calls)}, ${Math.round((g.hit_rate || 0) * 100)}%</dd></dl>` +
            `<p class="m-from">${from}</p><p>Best measured: ${esc(rs.headlines.repeat_tokens_off)} fewer 763B tokens on a repeat question <a href="${REPO}bench/results_backend.md" target="_blank" rel="noopener">bench/results_backend.md</a></p>`;
        } catch (e) { if (!b.querySelector('dl')) b.innerHTML = '<h3>Savings board</h3><p>The numbers could not be read. The rooms still show every saved result.</p>'; }
      };
      paint(); boardTimer = setInterval(paint, 5000);
    }
    function markDoor() { $('m-doors').querySelectorAll('.m-door').forEach((b, k) => b.classList.toggle('sel', k === S.door)); }
    $('m-doors').addEventListener('click', (e) => { const b = e.target.closest('.m-door'); if (b) { S.door = +b.dataset.k; markDoor(); use(); } });

    /* ---------- rooms: the door-opening clip, then the painted room with its data ---------- */
    async function openRoom(d) {
      if (!d || S.panel) return;
      leaveHall(); creak();
      const clip = `${site}game/clips/room-${d.id}.mp4`, info = ROOMS.find((r) => r.id === d.id) || {};
      let ok = false; if (info.clip !== false) { try { ok = (await fetch(clip, { method: 'HEAD' })).ok; } catch (e) { ok = false; } }   // clip:false = no door clip made, do not ask
      const v = vidFor(active + 1);
      if (ok) {
        v.src = clip; v.load(); vids.forEach((x) => x.classList.remove('on')); still.classList.remove('on'); v.classList.add('on');
        v.playbackRate = S.tour ? 2.5 : 1; await v.play().catch(() => {});   // the guided tour plays door clips fast
        await new Promise((r) => { v.onended = r; setTimeout(r, 9000); });
      } else { fade(); still.src = `${site}art/${d.art}.webp`; still.classList.add('on'); vids.forEach((x) => x.classList.remove('on')); }
      S.room = d;
      $('m-where').textContent = d.title;
      openPanel(d.title, (pb) => window.MoviePanels.room(pb, d, { site }));
    }
    function leaveRoom() {
      if (!S.room) return; S.room = null; fade();
      SEGS.forEach((s, k) => { if (k === SEGS.length - 1) { load(k); } });
      S.seg = SEGS.length - 1; show(S.seg); setTime(S.seg, dur(S.seg) - 0.05); enterHall();
    }

    /* ---------- panels and the map ---------- */
    let closeHook = null;
    function openPanel(title, fill) {
      S.panel = true; S.keys.clear(); stopWalk();
      $('m-ptitle').textContent = title; const pb = $('m-pbody'); pb.textContent = ''; pb.removeAttribute('style');
      $('m-panel').hidden = false; closeHook = fill(pb) || null; $('m-pclose').focus();
    }
    function closePanel() {
      if (!S.panel) return; if (typeof closeHook === 'function') closeHook(); closeHook = null;
      $('m-pbody').textContent = ''; $('m-panel').hidden = true; S.panel = false;
      if (S.room) leaveRoom();
    }
    $('m-pclose').addEventListener('click', closePanel);
    function talk() { if (!S.panel) openPanel('Talk to Count Cuspid', (pb) => window.MoviePanels.chat(pb)); }
    $('m-talkbtn').addEventListener('click', talk);
    function openMap() {
      if (S.panel) return; S.map = true;
      const here = S.room ? -1 : S.seg;
      $('m-mlist').innerHTML = SEGS.map((s, k) => `<li class="${k === here ? 'here' : ''}"><button type="button" data-seg="${k}">${esc(s.where)}</button></li>`).join('') +
        doors.map((d, k) => `<li class="${S.room && S.room.id === d.id ? 'here' : ''}"><button type="button" data-door="${k}">Door: ${esc(d.title)}</button></li>`).join('');
      $('m-map').hidden = false; $('m-mlist').querySelector('button').focus();
    }
    function closeMap() { S.map = false; $('m-map').hidden = true; }
    $('m-mapbtn').addEventListener('click', openMap); $('m-mclose').addEventListener('click', closeMap);
    $('m-mlist').addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return; closeMap();
      if (b.dataset.door != null) { jump(SEGS.length - 1, true); enterHall(); S.door = +b.dataset.door; markDoor(); use(); return; }
      jump(+b.dataset.seg, false);
    });
    function jump(i, end) {
      fade(); if (S.room) { S.room = null; } leaveHall();
      for (let k = 1; k <= i; k++) if (SEGS[k].lock) S.open[SEGS[k].lock] = true;
      S.seg = i; show(i);
      const t = end ? dur(i) - 0.01 : 0; S.t = t;
      if (have[SEGS[i].id]) { const v = vidFor(i); v.pause(); const go = () => { v.currentTime = clipAt(i, t); }; v.readyState ? go() : v.addEventListener('loadedmetadata', go, { once: true }); }   // a jump always lands, even mid-seek
      if (end && i === SEGS.length - 1) enterHall();
    }
    function fade() { const f = $('m-fade'); f.classList.add('on'); setTimeout(() => f.classList.remove('on'), 350); }

    /* ---------- input ---------- */
    const typing = (t) => t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName);
    addEventListener('keydown', (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === 'escape') { if (S.map) closeMap(); else if (S.panel) closePanel(); else if (S.hall) { leaveHall(); } return; }
      if (typing(e.target) || S.panel || S.map) return;
      if (k === 'm') { openMap(); return; }
      if (k === 'c') { e.preventDefault(); talk(); return; }
      if (k === 't') { e.preventDefault(); if (window.CastleTour) window.CastleTour.toggle(); return; }
      if ((k === 'e' || k === 'enter') && !e.repeat && !(k === 'enter' && /^(BUTTON|A)$/.test(e.target.tagName))) { e.preventDefault(); use(); return; }
      if (S.hall && (k === 'a' || k === 'arrowleft' || k === 'd' || k === 'arrowright') && !e.repeat) { S.door = (S.door + (k === 'a' || k === 'arrowleft' ? -1 : 1) + doors.length) % doors.length; markDoor(); e.preventDefault(); return; }
      if (S.hall && (k === 's' || k === 'arrowdown')) leaveHall();
      if ('wasd'.includes(k) || k.startsWith('arrow') || k === 'shift') { S.keys.add(k); e.preventDefault(); }
    });
    addEventListener('keyup', (e) => { S.keys.delete(e.key.toLowerCase()); });
    addEventListener('blur', () => S.keys.clear());
    addEventListener('mousemove', (e) => { if (S.panel) return; S.look.x = (e.clientX / innerWidth - 0.5) * 2; S.look.y = (e.clientY / innerHeight - 0.5) * 2; });
    const joy = $('m-joy'); let jid = null;
    const jm = (e) => { const r = joy.getBoundingClientRect(), dx = e.clientX - (r.left + 60), dy = e.clientY - (r.top + 60), d = Math.min(1, Math.hypot(dx, dy) / 50), a = Math.atan2(dy, dx); S.joy.x = d < 0.2 ? 0 : Math.cos(a) * d; S.joy.y = d < 0.2 ? 0 : Math.sin(a) * d; joy.firstElementChild.style.transform = `translate(${Math.cos(a) * d * 40}px,${Math.sin(a) * d * 40}px)`; };
    joy.addEventListener('pointerdown', (e) => { jid = e.pointerId; joy.setPointerCapture(jid); jm(e); });
    joy.addEventListener('pointermove', (e) => { if (e.pointerId === jid) jm(e); });
    const je = () => { jid = null; S.joy.x = S.joy.y = 0; joy.firstElementChild.style.transform = ''; };
    joy.addEventListener('pointerup', je); joy.addEventListener('pointercancel', je);
    $('m-act').addEventListener('click', use);

    /* ---------- sound ---------- */
    let ac = null;
    function creak() {
      try {
        ac = ac || new (window.AudioContext || window.webkitAudioContext)();
        const o = ac.createOscillator(), f = ac.createBiquadFilter(), v = ac.createGain();
        o.type = 'sawtooth'; o.frequency.setValueAtTime(70, ac.currentTime); o.frequency.linearRampToValueAtTime(140, ac.currentTime + 0.6); o.frequency.linearRampToValueAtTime(55, ac.currentTime + 1.6);
        f.type = 'bandpass'; f.frequency.value = 600; f.Q.value = 8;
        v.gain.setValueAtTime(0.0001, ac.currentTime); v.gain.exponentialRampToValueAtTime(0.1, ac.currentTime + 0.2); v.gain.exponentialRampToValueAtTime(0.0001, ac.currentTime + 1.8);
        o.connect(f); f.connect(v); v.connect(ac.destination); o.start(); o.stop(ac.currentTime + 1.9);
      } catch (e) { /* sound waits for a key press */ }
    }
    function say(t) { $('m-saytext').textContent = touch ? String(t).replace('Hold W', 'Push the stick up').replace('Pick one with A and D, then press E.', 'Tap one to open it.') : t; }

    /* ---------- live layers: bats, fog, fireflies ---------- */
    let W = 0, H = 0;
    function resize() { const k = Math.min(devicePixelRatio || 1, 1.25); W = fx.width = Math.round(innerWidth * k); H = fx.height = Math.round(innerHeight * k); }
    addEventListener('resize', () => { resize(); if (scene && S.hall) scene.layoutDoors($('m-doors')); }); resize();
    const bats = Array.from({ length: 120 }, (_, i) => {
      const depth = i < 78 ? 0 : i < 108 ? 1 : 2;
      return { depth, size: [5 + rnd() * 4, 11 + rnd() * 7, 24 + rnd() * 22][depth], r: [0.05 + rnd() * 0.2, 0.1 + rnd() * 0.3, 0.2 + rnd() * 0.45][depth], a: rnd() * 6.3,
        w: (rnd() > 0.5 ? 1 : -1) * [0.18 + rnd() * 0.25, 0.12 + rnd() * 0.18, 0.08 + rnd() * 0.1][depth], e: 0.35 + rnd() * 0.5, wob: rnd() * 6.3, flap: 9 + rnd() * 7, ph: rnd() * 6.3,
        cx: (rnd() - 0.5) * [0.3, 0.7, 1.2][depth], cy: (rnd() - 0.5) * [0.18, 0.3, 0.4][depth] };
    });
    const glow = (() => { const c = document.createElement('canvas'); c.width = c.height = 128; const x = c.getContext('2d'); const r = x.createRadialGradient(64, 64, 0, 64, 64, 64); r.addColorStop(0, 'rgba(255,214,140,1)'); r.addColorStop(0.25, 'rgba(255,160,70,.55)'); r.addColorStop(1, 'rgba(255,120,40,0)'); x.fillStyle = r; x.fillRect(0, 0, 128, 128); return c; })();
    const fog = (() => { const c = document.createElement('canvas'); c.width = c.height = 256; const x = c.getContext('2d'); const r = x.createRadialGradient(128, 128, 0, 128, 128, 128); r.addColorStop(0, 'rgba(190,160,220,.26)'); r.addColorStop(1, 'rgba(190,160,220,0)'); x.fillStyle = r; x.fillRect(0, 0, 256, 256); return c; })();
    const fogs = Array.from({ length: 8 }, (_, i) => ({ u: rnd(), v: 0.7 + rnd() * 0.25, s: 0.5 + rnd() * 0.7, sp: (0.004 + rnd() * 0.01) * (i % 2 ? 1 : -1) }));
    const flies = Array.from({ length: 50 }, () => ({ u: rnd(), v: 0.55 + rnd() * 0.4, ph: rnd() * 6.3, sp: 0.4 + rnd() }));
    function bat(x, y, s, flap, alpha, tilt) {
      const up = Math.sin(flap) * 0.9;
      g.save(); g.translate(x, y); g.rotate(tilt); g.scale(s / 30, s / 30); g.globalAlpha = alpha; g.fillStyle = '#0c0410';
      g.beginPath(); g.moveTo(0, -2); g.quadraticCurveTo(-8, -10 - up * 12, -30, -6 - up * 16); g.quadraticCurveTo(-22, -1, -20, 4); g.quadraticCurveTo(-14, 0, -11, 6); g.quadraticCurveTo(-6, 2, -3, 7);
      g.lineTo(3, 7); g.quadraticCurveTo(6, 2, 11, 6); g.quadraticCurveTo(14, 0, 20, 4); g.quadraticCurveTo(22, -1, 30, -6 - up * 16); g.quadraticCurveTo(8, -10 - up * 12, 0, -2); g.fill();
      g.beginPath(); g.ellipse(0, 1, 3.4, 6, 0, 0, 7); g.fill(); g.restore(); g.globalAlpha = 1;
    }
    function drawFx(dt) {
      g.clearRect(0, 0, W, H);
      const outside = !S.room && S.seg <= 2, R = Math.min(W, H), lx = -S.yaw * W * 0.06;
      if (outside) {                                 // the flock circles the moon: upper right of the painting
        const mx = W * 0.6 + lx * 0.5, my = H * 0.24 - S.pitch * H * 0.04;
        for (const b of bats) {
          const a = b.a + S.time * b.w, wob = Math.sin(S.time * 0.7 + b.wob), par = [0.3, 0.7, 1.4][b.depth];
          const x = mx + (b.cx + Math.cos(a) * b.r * (1 + 0.25 * wob)) * R * 1.1 + lx * par, y = my + (b.cy + Math.sin(a) * b.r * b.e + Math.sin(S.time * 1.3 + b.ph) * 0.02) * R;
          bat(x, y, b.size * (R / 900) * (1 + S.seg * 0.15), S.time * b.flap + b.ph, [0.55, 0.8, 0.95][b.depth], Math.cos(a) * 0.3 * Math.sign(b.w));
        }
        fogs.forEach((o) => { o.u = (o.u + o.sp * dt + 1.4) % 1.4 - 0.2; const r = W * 0.35 * o.s; g.drawImage(fog, o.u * W - r + lx, o.v * H - r * 0.4, r * 2, r * 0.8); });
      } else if (!S.room) {                          // inside: a few bats under the vault, candle motes
        if (scene && S.seg === SEGS.length - 1) scene.hall(g, S, W, H, lx);
        for (const b of bats.slice(0, 10)) { const a = b.a + S.time * b.w * 0.6; bat(W * 0.5 + Math.cos(a) * W * 0.3 + lx, H * 0.18 + Math.sin(a) * H * 0.06, b.size * 0.8 * (R / 900), S.time * b.flap + b.ph, 0.7, 0); }
      }
      if (scene) { const sg = SEGS[S.seg]; scene.path(g, S, sg, clamp(S.t / dur(S.seg), 0, 1), W, H, lx); scene.feet(g, S, W, H); }
      g.globalCompositeOperation = 'lighter';
      flies.forEach((o) => { const x = (o.u + Math.sin(S.time * 0.3 * o.sp + o.ph) * 0.03) * W + lx * 1.2, y = (o.v + Math.cos(S.time * 0.4 * o.sp + o.ph) * 0.02) * H; const a = 0.35 + 0.6 * Math.max(0, Math.sin(S.time * 2 * o.sp + o.ph)), r = 5 * (H / 900); g.globalAlpha = a * (S.room ? 0.4 : 1); g.drawImage(glow, x - r, y - r, r * 2, r * 2); });
      g.globalAlpha = 1; g.globalCompositeOperation = 'source-over';
      const vg = g.createRadialGradient(W / 2, H / 2, H * 0.4, W / 2, H / 2, H * 0.95); vg.addColorStop(0, 'rgba(0,0,0,0)'); vg.addColorStop(1, 'rgba(6,2,12,.45)'); g.fillStyle = vg; g.fillRect(0, 0, W, H);
    }

    /* ---------- dolly effects: the gate leaves part, the great door pours out gold light ---------- */
    const veil = document.createElement('div'); veil.className = 'm-veil'; stage.after(veil);
    function dollyFx(sg, e) {
      if (sg && sg.gate) { veil.style.background = `linear-gradient(90deg, rgba(8,3,12,${(0.9 * (1 - e)).toFixed(3)}) ${(50 - e * 50).toFixed(1)}%, transparent ${(50 - e * 50).toFixed(1)}%, transparent ${(50 + e * 50).toFixed(1)}%, rgba(8,3,12,${(0.9 * (1 - e)).toFixed(3)}) ${(50 + e * 50).toFixed(1)}%)`; veil.style.opacity = 1; }
      else if (sg && sg.door) { veil.style.background = `radial-gradient(ellipse at 50% 58%, rgba(255,214,140,${(e * e * 0.6).toFixed(3)}) ${(e * 22).toFixed(1)}%, rgba(255,160,70,${(e * e * 0.3).toFixed(3)}) ${(e * 50).toFixed(1)}%, transparent 100%)`; veil.style.opacity = 1; }
      else veil.style.opacity = 0;
    }

    /* ---------- minimap: the way in as a path, you as a dot ---------- */
    function drawMini() {
      const m = mini, w = 180, h = 130;
      m.clearRect(0, 0, w, h); m.fillStyle = 'rgba(11,5,16,.86)'; m.fillRect(0, 0, w, h);
      m.fillStyle = '#e9c46a'; m.font = '600 10px Inter, sans-serif'; m.fillText(S.room ? S.room.title : SEGS[S.seg].where, 8, 14);
      const pts = [[30, 118], [30, 96], [30, 74], [30, 46], [30, 30], [150, 30]];   // gates, drive, door, hall
      m.strokeStyle = '#6a5a78'; m.lineWidth = 8; m.lineJoin = 'round'; m.beginPath(); pts.forEach(([x, y], k) => (k ? m.lineTo(x, y) : m.moveTo(x, y))); m.stroke();
      m.fillStyle = S.open.gates ? '#6a5a78' : '#c08a3a'; m.fillRect(20, 95, 20, 3);
      m.fillStyle = S.open.door ? '#6a5a78' : '#ffd27a'; m.fillRect(22, 45, 16, 3);
      m.fillStyle = '#d9c9e0'; m.font = '9px Inter, sans-serif'; m.fillText('gates', 44, 99); m.fillText('drive', 44, 76); m.fillText('door', 44, 49); m.fillText('Great Hall', 70, 24);
      doors.forEach((d, k) => { const x = 44 + k * (100 / Math.max(1, doors.length - 1)); m.fillStyle = S.room && S.room.id === d.id ? '#ff6a8a' : (S.hall && k === S.door ? '#ffd27a' : '#8a6a3a'); m.fillRect(x - 3, 36, 6, 6); });
      let x, y;
      if (S.room) { const k = doors.findIndex((d) => d.id === S.room.id); x = 44 + k * (100 / Math.max(1, doors.length - 1)); y = 39; }
      else { const p = clamp(S.t / dur(S.seg), 0, 1), a = pts[S.seg], b = pts[S.seg + 1]; x = a[0] + (b[0] - a[0]) * p; y = a[1] + (b[1] - a[1]) * p; if (S.hall) { x = 44 + S.door * (100 / Math.max(1, doors.length - 1)); y = 30; } }
      m.fillStyle = '#6ee7a0'; m.beginPath(); m.arc(x, y, 4.5 + Math.sin(S.time * 6) * 0.8, 0, 7); m.fill();
    }

    /* ---------- the loop ---------- */
    let last = performance.now(), fN = 0, fT = 0;
    function frame(now) {
      const dt = Math.min(0.05, (now - last) / 1000); last = now; S.time += dt;
      const k = S.keys, f = (k.has('w') || k.has('arrowup') ? 1 : 0) - (k.has('s') || k.has('arrowdown') ? 1 : 0) - S.joy.y;
      const turn = (k.has('d') || k.has('arrowright') ? 1 : 0) - (k.has('a') || k.has('arrowleft') ? 1 : 0) + S.joy.x;
      if (!S.hall && Math.abs(f) > 0.3) walk(dt, Math.sign(f), k.has('shift')); else if (S.walking) stopWalk();
      if (!S.hall) S.yaw = clamp(S.yaw + turn * dt * 1.4, -1, 1);
      S.yaw += ((S.hall ? 0 : S.yaw) * 0.97 + S.look.x * 0.5 - S.yaw) * Math.min(1, dt * 3) * (turn ? 0 : 1);
      S.pitch += (S.look.y * 0.6 - S.pitch) * Math.min(1, dt * 3);
      // turning your head: the frame is 12% wider than the screen
      const bob = S.walking ? Math.sin(S.time * (k.has('shift') ? 14 : 9)) * 0.004 : 0;
      S.over += ((S.seg >= SEGS.length - 2 && !S.room ? 1 : 1.12) - S.over) * Math.min(1, dt * 4);   // past the great door the hall is shown whole
      const room = (S.over - 1) / 0.12;
      stage.style.transform = `translate(${(-S.yaw * 5.2 * room).toFixed(2)}%, ${((-S.pitch * 3 + bob * 100) * room).toFixed(2)}%) scale(${S.over.toFixed(4)})`;
      const sg = SEGS[S.seg];
      const hv = held(S.seg), dollyEl = hv || still;
      vids.forEach((v) => { if (v !== hv && v.style.transform) v.style.transform = ''; });
      if (!have[sg.id] && !S.room && sg.fb) {      // the painted dolly: ease the zoom toward the focus point
        const p = clamp(S.t / dur(S.seg), 0, 1), e = p * p * (3 - 2 * p), [a, b] = sg.fb;
        const z = a[0] + (b[0] - a[0]) * e, u = a[1] + (b[1] - a[1]) * e, v = a[2] + (b[2] - a[2]) * e;
        dollyEl.style.transformOrigin = `${(u * 100).toFixed(1)}% ${(v * 100).toFixed(1)}%`; dollyEl.style.transform = `scale(${z.toFixed(4)})`;
        dollyFx(sg, e);
      } else { dollyEl.style.transform = ''; dollyFx(null, 0); }
      if (scene) scene.update(S, sg, clamp(S.t / dur(S.seg), 0, 1), dollyEl, have[sg.id], W, H);
      root.classList.toggle('m-inhall', S.hall);
      drawFx(dt); drawMini();
      const pr = $('m-prompt'), l = !S.panel && !S.map && !S.hall && !S.walking && pendingLock();
      if (l) { pr.innerHTML = `<kbd>E</kbd> ${LOCK_AT[l]}`; pr.classList.add('on'); }
      else if (S.hall && !S.panel) { pr.innerHTML = `<kbd>A</kbd><kbd>D</kbd> choose a door · <kbd>E</kbd> enter ${esc(doors[S.door] ? doors[S.door].title : '')}`; pr.classList.add('on'); }
      else if (!S.panel && !S.map && !S.walking && S.seg === 0 && S.t < 0.1) { pr.innerHTML = matchMedia('(pointer: coarse)').matches ? 'Push the stick up to walk to the castle' : 'Hold <kbd>W</kbd> to walk to the castle'; pr.classList.add('on'); }
      else pr.classList.remove('on');
      fN++; fT += dt; if (fT >= 1) { S.fps.push(fN / fT); if (S.fps.length > 120) S.fps.shift(); $('m-fps').textContent = Math.round(fN / fT) + ' fps'; fN = 0; fT = 0; }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
    if (window.ChimeraMode) window.ChimeraMode.badge($('m-mode')); else $('m-mode').remove();
    $('m-tourbtn').addEventListener('click', () => { if (window.CastleTour) window.CastleTour.toggle(); });
    const api = { state: S, have, segs: SEGS, doors, use, talk, openMap, jump, enterHall, closePanel, openRoom, say, fps: () => S.fps.slice() };
    window.MovieGame = api;
    return api;
  }
  window.MovieGameStart = start;
})();
