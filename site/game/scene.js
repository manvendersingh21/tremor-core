/* Scene layers for the walk-in movie (site/game/walk.js calls these). Everything that stands in a painting lives in
   one box the size of the painting as it is shown (16:9, cover-fit), so its numbers are fractions of the painting:
   - the Count stands IN the painting: a cut-out (game/layers/count-full.webp) on the ground of each stretch, moving
     with the painting's own dolly, lit to match it, fog over his feet; his speech bubble hangs by his head.
   - the path to the gates: lantern glows and wisps on the ground that lead to the gate, fading as you walk.
   - the great door (game/layers/door-*.webp, cut by scripts/cut_door.py): closed until you reach it, then its two
     leaves swing in, gold light pours out and you walk through into the Great Hall.
   - the Great Hall (art/hall-grand-1.webp): its own painted gold doors are the doors you pick (lit when chosen),
     every painted candle flickers, moonlight shafts with dust, floor haze.
   Never paused. Cheap: a few DOM layers with CSS animation and a few canvas gradients per frame. */
(function () {
  'use strict';
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
  const ASPECT = 16 / 9;                       // every painting and clip of the walk
  function blob(rgb, a) {                      // a soft ellipse, 4:1, fully clear at its edge
    const c = document.createElement('canvas'); c.width = 256; c.height = 64; const x = c.getContext('2d');
    x.scale(4, 1); const r = x.createRadialGradient(32, 32, 0, 32, 32, 32); r.addColorStop(0, `rgba(${rgb},${a})`); r.addColorStop(1, `rgba(${rgb},0)`);
    x.fillStyle = r; x.fillRect(0, 0, 64, 64); return c;
  }

  /* Where the Count stands on each stretch, as fractions of the painting: feet at (u, v), h = his height.
     out: progress (0..1) at which you have walked past him. */
  const SPOT = {
    'a-approach': { u: 0.33, v: 0.97, h: 0.36, out: 0.42 },
    'c-drive': { u: 0.40, v: 0.86, h: 0.26, out: 0.62 },
    'e-hall': { u: 0.61, v: 0.885, h: 0.27, out: 9 },   // he waits for you in the hall
  };
  // a clip has no transform we can read: model its forward dolly as a zoom toward the gate (fit to a-approach.mp4)
  const CLIP_ZOOM = { 'a-approach': [0.5, 0.74, 1.6] };

  /* The painted doors of art/hall-grand-1.webp, [x0, y0, x1, y1] as fractions, read off the painting by eye.
     In A/D order: the left wall from near to far, the far gold doors, the right wall from far to near.
     paste: no painted door there, so a small gold door is drawn. shortcut: hand-placed; redo if the hall is repainted. */
  const SLOTS = [
    { room: 'observatory', box: [0.036, 0.489, 0.124, 0.841] },
    { room: 'crypt', box: [0.171, 0.567, 0.196, 0.800] },
    { room: 'ladder', box: [0.254, 0.606, 0.283, 0.789] },
    { room: 'familiar', box: [0.300, 0.628, 0.321, 0.776] },
    { room: 'tower', box: [0.476, 0.592, 0.536, 0.775] },
    { room: 'gpus', box: [0.679, 0.640, 0.698, 0.776], paste: true },
    { room: 'guild', box: [0.727, 0.602, 0.751, 0.789] },
    { room: 'gate', box: [0.813, 0.567, 0.845, 0.806] },
    { room: 'ledger', box: [0.888, 0.493, 0.976, 0.841] },
  ];
  const ORDER = SLOTS.map((s) => s.room);
  const DOOR = { leaf_l: [0.31152, 0.11198, 0.5, 0.90538], leaf_r: [0.5, 0.11198, 0.68848, 0.90538] };   // game/layers/door.json

  function create(root, opts) {
    const site = opts.site || '';
    const stage = root.querySelector('#m-stage'), say = root.querySelector('#m-say');
    const hallSrc = site + (opts.hall || 'art/hall-grand-1.webp');
    const pct = (b) => `left:${b[0] * 100}%;top:${b[1] * 100}%;width:${(b[2] - b[0]) * 100}%;height:${(b[3] - b[1]) * 100}%`;
    // the great door, between the drive and the hall
    const rig = document.createElement('div'); rig.className = 'm-rig';
    rig.innerHTML = `<img class="m-rig-hall" alt="" src="${hallSrc}"><div class="m-rig-door"><i class="m-rig-glow"></i>` +
      `<img class="m-leaf l" alt="" style="${pct(DOOR.leaf_l)}" src="${site}game/layers/door-leaf-l.webp">` +
      `<img class="m-leaf r" alt="" style="${pct(DOOR.leaf_r)}" src="${site}game/layers/door-leaf-r.webp">` +
      `<img class="m-rig-frame" alt="" src="${site}game/layers/door-frame.webp"></div>`;
    const anchor = document.createElement('div'); anchor.className = 'm-anchor';
    anchor.innerHTML = '<div class="m-flames"></div><div class="m-count" id="m-count"><i class="m-shadow"></i><img alt="" draggable="false"></div>';
    stage.append(rig, anchor);
    const count = anchor.querySelector('.m-count'), img = count.querySelector('img'), flames = anchor.querySelector('.m-flames');
    const door = rig.querySelector('.m-rig-door'), leafL = rig.querySelector('.m-leaf.l'), leafR = rig.querySelector('.m-leaf.r'), glowEl = rig.querySelector('.m-rig-glow');
    img.onerror = () => { if (!img.dataset.fb) { img.dataset.fb = 1; img.src = site + 'game/layers/count.png'; count.classList.add('half'); } };
    img.src = site + 'game/layers/count-full.webp';
    let shown = 0, cur = null, box = { l: 0, t: 0, w: 1, h: 1 };

    /* the painting's box on screen (object-fit: cover), in stage pixels */
    function fit() {
      const w = stage.clientWidth || innerWidth, h = stage.clientHeight || innerHeight;
      const bw = Math.max(w, h * ASPECT), bh = bw / ASPECT;
      box = { l: (w - bw) / 2, t: (h - bh) / 2, w: bw, h: bh };
      for (const el of [anchor, rig]) el.style.cssText = `left:${box.l}px;top:${box.t}px;width:${bw}px;height:${bh}px;` + (el === anchor ? anchor.dataset.tf || '' : '');
    }
    addEventListener('resize', fit); fit();

    /* every candle flame in the hall painting flickers: find the bright warm spots once, from the image itself */
    (function lights() {
      const im = new Image(); im.onload = () => {
        const w = 320, h = 180, c = document.createElement('canvas'); c.width = w; c.height = h;
        const x = c.getContext('2d', { willReadFrequently: true }); x.drawImage(im, 0, 0, w, h);
        let d; try { d = x.getImageData(0, 0, w, h).data; } catch (e) { return; }
        const L = (i, j) => { const k = (j * w + i) * 4; return d[k] + d[k + 1] * 0.8 - d[k + 2] * 0.6; };
        const pts = [];
        for (let j = 2; j < h - 2; j++) for (let i = 2; i < w - 2; i++) {
          const k = (j * w + i) * 4, r = d[k], gg = d[k + 1], b = d[k + 2];
          if (r < 225 || gg < 140 || b > 190 || r - b < 60) continue;          // a bright warm pixel
          const v = L(i, j); let top = true;
          for (let dj = -2; dj <= 2 && top; dj++) for (let di = -2; di <= 2; di++) if ((di || dj) && L(i + di, j + dj) > v) { top = false; break; }
          if (top && !pts.some((p) => Math.abs(p[0] - i) < 4 && Math.abs(p[1] - j) < 4)) pts.push([i, j, v]);
        }
        pts.sort((a, b) => b[2] - a[2]);
        flames.innerHTML = pts.slice(0, 110).map(([i, j], n) => {
          const u = i / w, v = j / h, s = 0.6 + 2.2 * Math.max(0, v - 0.45);   // nearer (lower) candles glow bigger
          return `<i style="left:${(u * 100).toFixed(2)}%;top:${(v * 100).toFixed(2)}%;--s:${s.toFixed(2)};animation-duration:${(0.11 + ((n * 37) % 23) / 100).toFixed(2)}s;animation-delay:-${((n * 53) % 97) / 100}s"></i>`;
        }).join('');
      };
      im.src = hallSrc;
    })();

    /* each frame: the painting's dolly copied onto the box, the Count, his bubble, the great door */
    function update(S, seg, p, still, hasClip) {
      // the box gets the same zoom as the painting; transform-origin is a screen point, so convert it
      let tf = '';
      if (hasClip) {
        const c = CLIP_ZOOM[seg.id];
        if (c) tf = `transform-origin:${c[0] * 100}% ${c[1] * 100}%;transform:scale(${(1 + (c[2] - 1) * Math.pow(p, 1.4)).toFixed(4)})`;
      } else if (still && still.style.transform) {
        const o = (still.style.transformOrigin || '50% 50%').split(' ').map(parseFloat), w = stage.clientWidth, h = stage.clientHeight;
        tf = `transform-origin:${(o[0] / 100 * w - box.l).toFixed(1)}px ${(o[1] / 100 * h - box.t).toFixed(1)}px;transform:${still.style.transform}`;
      }
      if (tf !== anchor.dataset.tf) { anchor.dataset.tf = tf; fit(); }

      const spot = !S.room && !S.panel && SPOT[seg.id];
      const want = spot ? 1 - smooth(spot.out - 0.12, spot.out, p) : 0;
      shown += (want - shown) * 0.12;
      count.style.opacity = shown.toFixed(3);
      if (spot && cur !== seg.id) {
        cur = seg.id; count.dataset.where = seg.id;
        count.style.left = (spot.u * 100) + '%'; count.style.top = (spot.v * 100) + '%'; count.style.height = (spot.h * 100) + '%';
      }
      const on = shown > 0.35 && innerWidth > 520;          // the bubble hangs by his head while he is in view
      say.classList.toggle('m-attached', on);
      if (on) {
        const r = count.getBoundingClientRect(), right = r.right + 300 < innerWidth;
        say.style.left = (right ? r.left + r.width * 0.78 : r.left + r.width * 0.2 - Math.min(340, say.offsetWidth)) + 'px';
        say.style.top = Math.max(60, r.top - say.offsetHeight * 0.55) + 'px';
        say.classList.toggle('m-tail-r', !right);
      } else { say.style.left = ''; say.style.top = ''; }

      // the great door: closed as you reach it, the leaves swing in, gold light, then you walk through
      const inDoor = !!seg.rig && !S.room;
      rig.classList.toggle('on', inDoor);
      if (inDoor) {
        const a = 84 * smooth(0.18, 0.62, p), push = Math.pow(smooth(0.3, 1, p), 1.6);
        leafL.style.transform = `rotateY(${a.toFixed(2)}deg)`; leafR.style.transform = `rotateY(${(-a).toFixed(2)}deg)`;
        door.style.transform = `scale(${(1 + 3.6 * push).toFixed(4)})`; door.style.opacity = (1 - smooth(0.72, 1, p)).toFixed(3);
        glowEl.style.opacity = (smooth(0.02, 0.4, p) * (1 - 0.6 * smooth(0.6, 1, p)) * (0.9 + 0.1 * Math.sin(S.time * 9))).toFixed(3);
      }
      flames.classList.toggle('on', (seg.id === 'e-hall' || S.hall) && !S.room);
    }

    /* the path to the gates: pairs of lantern glows on the ground, wisps drifting to the gate */
    const glow = (() => { const c = document.createElement('canvas'); c.width = c.height = 64; const x = c.getContext('2d'); const r = x.createRadialGradient(32, 32, 0, 32, 32, 32); r.addColorStop(0, 'rgba(255,220,150,1)'); r.addColorStop(0.3, 'rgba(255,170,80,.5)'); r.addColorStop(1, 'rgba(255,120,40,0)'); x.fillStyle = r; x.fillRect(0, 0, 64, 64); return c; })();
    const moon = (() => { const c = document.createElement('canvas'); c.width = c.height = 64; const x = c.getContext('2d'); const r = x.createRadialGradient(32, 32, 0, 32, 32, 32); r.addColorStop(0, 'rgba(225,205,255,.9)'); r.addColorStop(1, 'rgba(180,150,230,0)'); x.fillStyle = r; x.fillRect(0, 0, 64, 64); return c; })();
    function path(g, S, seg, p, W, H, lx) {
      if (seg.id !== 'a-approach' || S.room) return;
      const a = 1 - smooth(0.15, 0.55, p); if (a <= 0.01) return;
      const c = CLIP_ZOOM[seg.id], z = 1 + (c[2] - 1) * Math.pow(p, 1.4);
      const P = (u, v) => [((c[0] + (u - c[0]) * z) * W) + lx, (c[1] + (v - c[1]) * z) * H];
      g.save(); g.globalCompositeOperation = 'lighter';
      const top = P(0.5, 0.84), bl = P(0.22, 1.02), br = P(0.78, 1.02), tl = P(0.43, 0.84), tr = P(0.57, 0.84);
      const lg = g.createLinearGradient(0, bl[1], 0, top[1]); lg.addColorStop(0, `rgba(150,120,200,${0.16 * a})`); lg.addColorStop(1, `rgba(225,195,255,${0.3 * a})`);
      g.fillStyle = lg; g.beginPath(); g.moveTo(bl[0], bl[1]); g.lineTo(tl[0], tl[1]); g.lineTo(tr[0], tr[1]); g.lineTo(br[0], br[1]); g.closePath(); g.fill();
      for (let k = 0; k < 5; k++) {
        const d = k / 4, v = 1.0 - d * 0.16, half = 0.26 - d * 0.19;
        for (const s of [-1, 1]) {
          const [x, y] = P(0.5 + s * half, v), r = (0.09 - d * 0.055) * H * z;
          const f = 0.75 + 0.25 * Math.sin(S.time * (7 + k) + s * 2 + k);
          g.globalAlpha = a * f; g.drawImage(glow, x - r, y - r, r * 2, r * 2);
        }
      }
      for (let k = 0; k < 7; k++) {
        const q = (S.time * 0.12 + k / 7) % 1, wob = Math.sin(S.time * 1.7 + k * 2) * 0.03 * (1 - q);
        const [x, y] = P(0.5 + wob + (k % 2 ? 0.04 : -0.04) * (1 - q), 1.0 - q * 0.16), r = (0.03 - q * 0.018) * H * z;
        g.globalAlpha = a * Math.sin(q * Math.PI) * 0.9; g.drawImage(moon, x - r, y - r, r * 2, r * 2);
      }
      g.restore(); g.globalAlpha = 1;
    }

    /* fog over the Count's feet, so he stands in the scene (drawn on the fx canvas, above the painting) */
    const mist = blob('70,52,92', 0.85);
    function feet(g, S, W, H) {
      if (shown < 0.02) return;
      const r = count.getBoundingClientRect(), k = W / innerWidth;
      const w = r.width * 2.2 * k, h = r.height * 0.22 * k, x = (r.left + r.width / 2) * k + Math.sin(S.time * 0.4) * w * 0.05, y = r.bottom * k - h * 0.35;
      g.globalAlpha = shown * (cur === 'e-hall' ? 0.5 : 0.8); g.drawImage(mist, x - w / 2, y - h / 2, w, h); g.globalAlpha = 1;
    }

    /* the hall: the moonlight shaft from the rose window and the high windows, dust in it, haze along the floor */
    const dust = Array.from({ length: 70 }, (_, i) => ({ s: (i * 0.6180339) % 1, h: (i * 0.4142) % 1, sp: 0.2 + ((i * 0.7321) % 1) * 0.5 }));
    const haze = blob('150,120,190', 0.2);
    function hall(g, S, W, H, lx) {
      if (S.room) return;
      g.save(); g.globalCompositeOperation = 'lighter';
      // [top x, top y, bottom x, bottom y, strength] in screen fractions, matched to the shafts painted in hall-grand-1
      const beams = [[0.60, 0.05, 0.47, 0.72, 0.11], [0.84, 0.10, 0.62, 0.95, 0.06], [0.16, 0.12, 0.36, 0.92, 0.045]];
      beams.forEach(([x0, y0, x1, y1, a], i) => {
        const pulse = a * (0.7 + 0.3 * Math.sin(S.time * 0.35 + i * 2)), wd = W * 0.06;
        const X0 = x0 * W + lx * 0.6, X1 = x1 * W + lx * 1.1;
        const lg = g.createLinearGradient(X0, y0 * H, X1, y1 * H); lg.addColorStop(0, `rgba(205,185,255,${pulse})`); lg.addColorStop(1, 'rgba(205,185,255,0)');
        g.fillStyle = lg; g.beginPath(); g.moveTo(X0 - wd * 0.3, y0 * H); g.lineTo(X0 + wd * 0.3, y0 * H); g.lineTo(X1 + wd, y1 * H); g.lineTo(X1 - wd, y1 * H); g.closePath(); g.fill();
        for (let k = i; k < dust.length; k += 3) {
          const d = dust[k], q = (d.h + S.time * 0.02 * d.sp) % 1, x = X0 + (X1 - X0) * q + (d.s - 0.5) * wd * (0.6 + q), y = (y0 + (y1 - y0) * q) * H;
          g.globalAlpha = 0.55 * Math.sin(q * Math.PI) * (0.6 + 0.4 * Math.sin(S.time * 2 + k)); g.fillStyle = '#efe4ff'; g.fillRect(x, y, 2, 2);
        }
        g.globalAlpha = 1;
      });
      g.globalCompositeOperation = 'source-over';
      for (let k = 0; k < 5; k++) {                    // haze drifting along the floor
        const u = ((S.time * (0.006 + k * 0.002) * (k % 2 ? 1 : -1) + k * 0.23) % 1.4 + 1.4) % 1.4 - 0.2, r = W * (0.3 + 0.08 * k);
        g.drawImage(haze, u * W - r + lx, H * (0.86 + 0.03 * k) - r * 0.15, r * 2, r * 0.3);
      }
      g.restore();
    }

    /* the doors you pick in the hall. Wide screens: the hall's own painted doors, lit when chosen, a gold sign above
       each (far ones show their sign when chosen). A phone shows only the middle of the hall: a two-row arcade. */
    const wideNow = () => innerWidth / innerHeight > 1.05 && innerWidth > 700;
    function layoutDoors(el) {
      const ds = [...el.querySelectorAll('.m-door')], wide = wideNow();
      const home = wide ? anchor : root;
      if (el.parentNode !== home) home.insertBefore(el, wide ? null : root.querySelector('.m-bar'));
      el.classList.toggle('m-spots', wide); el.classList.toggle('m-arcade', !wide);
      ds.forEach((b) => {
        const s = SLOTS.find((x) => x.room === b.dataset.id);
        b.classList.remove('m-far', 'm-paste', 'm-edge-l', 'm-edge-r');
        if (!wide || !s) { b.removeAttribute('style'); return; }
        const [x0, y0, x1, y1] = s.box, hpx = (y1 - y0) * box.h;
        b.classList.toggle('m-far', y1 - y0 < 0.3); b.classList.toggle('m-paste', !!s.paste);
        b.style.cssText = pct(s.box) + `;--fs:${clamp(hpx * 0.07, 10, 15).toFixed(1)}px`;
        b.classList.toggle('m-edge-l', x0 < 0.15); b.classList.toggle('m-edge-r', x1 > 0.85);
      });
    }
    addEventListener('resize', () => { const el = root.querySelector('#m-doors'); if (el && !el.hidden) layoutDoors(el); });

    return { update, path, feet, hall, layoutDoors, count, order: ORDER };
  }

  window.MovieScene = { create, ORDER: SLOTS.map((s) => s.room) };
})();
