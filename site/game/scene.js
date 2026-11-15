/* Scene layers for the walk-in movie (site/game/walk.js calls these):
   - the Count stands IN the painting: a cut-out (game/layers/count-full.png) placed on the ground of each stretch,
     moving with the same dolly as the painting, lit to match it, with fog drawn over his feet; his speech bubble
     hangs by his head. You walk past him; he waits for you further on.
   - the path to the gates: lantern lights and wisps on the ground that lead to the gate, fading as you walk.
   - the Great Hall: shafts of moonlight with dust, and the gold doors set along both walls in perspective.
   Never paused. Cheap: one image, a few canvas gradients per frame. */
(function () {
  'use strict';
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

  /* Where the Count stands on each stretch, as fractions of the painting: feet at (u, v), h = his height.
     out: progress (0..1) at which you have walked past him. */
  const SPOT = {
    'a-approach': { u: 0.33, v: 0.97, h: 0.36, out: 0.42, look: 1 },
    'c-drive': { u: 0.40, v: 0.86, h: 0.26, out: 0.72, look: 1 },
    'd-door': { u: 0.455, v: 0.56, h: 0.07, out: 0.45, look: 1 },
    'e-hall': { u: 0.44, v: 0.84, h: 0.22, out: 9, look: 1 },   // he waits for you in the hall
  };
  // a clip has no transform we can read: model its forward dolly as a zoom toward the gate (fit to a-approach.mp4)
  const CLIP_ZOOM = { 'a-approach': [0.5, 0.74, 1.6] };

  function create(root, opts) {
    const site = opts.site || '';
    const stage = root.querySelector('#m-stage'), say = root.querySelector('#m-say');
    const anchor = document.createElement('div'); anchor.className = 'm-anchor';
    anchor.innerHTML = '<div class="m-count" id="m-count"><i class="m-shadow"></i><img alt="" draggable="false"></div>';
    stage.appendChild(anchor);
    const count = anchor.firstChild, img = count.querySelector('img');
    img.onerror = () => { if (!img.dataset.fb) { img.dataset.fb = 1; img.src = site + 'game/layers/count.png'; count.classList.add('half'); } };
    img.src = site + 'game/layers/count-full.webp';
    let shown = 0, cur = null;

    /* each frame: put the Count where this stretch's painting is, with the painting's own zoom */
    function update(S, seg, p, still, hasClip, W, H) {
      const spot = !S.room && !S.panel && SPOT[seg.id];
      const want = spot ? 1 - smooth(spot.out - 0.12, spot.out, p) : 0;
      shown += (want - shown) * 0.12;
      count.style.opacity = shown.toFixed(3);
      if (spot) {
        if (cur !== seg.id) { cur = seg.id; count.classList.toggle('flip', spot.look < 0); count.dataset.where = seg.id; }
        count.style.left = (spot.u * 100) + '%'; count.style.top = (spot.v * 100) + '%'; count.style.height = (spot.h * 100) + '%';
        if (hasClip) {
          const c = CLIP_ZOOM[seg.id];
          if (c) { anchor.style.transformOrigin = `${c[0] * 100}% ${c[1] * 100}%`; anchor.style.transform = `scale(${(1 + (c[2] - 1) * Math.pow(p, 1.4)).toFixed(4)})`; }
          else anchor.style.transform = '';
        } else { anchor.style.transformOrigin = still.style.transformOrigin; anchor.style.transform = still.style.transform; }
      }
      // the bubble hangs by his head while he is in view
      const on = shown > 0.35 && innerWidth > 520;
      say.classList.toggle('m-attached', on);
      if (on) {
        const r = count.getBoundingClientRect(), right = r.right + 300 < innerWidth;
        say.style.left = (right ? r.left + r.width * 0.78 : r.left + r.width * 0.2 - Math.min(340, say.offsetWidth)) + 'px';
        say.style.top = Math.max(60, r.top - say.offsetHeight * 0.55) + 'px';
        say.classList.toggle('m-tail-r', !right);
      } else { say.style.left = ''; say.style.top = ''; }
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
      // a soft moonlit band of ground from your feet to the gap between the gates
      const top = P(0.5, 0.84), bl = P(0.22, 1.02), br = P(0.78, 1.02), tl = P(0.43, 0.84), tr = P(0.57, 0.84);
      const lg = g.createLinearGradient(0, bl[1], 0, top[1]); lg.addColorStop(0, `rgba(150,120,200,${0.16 * a})`); lg.addColorStop(1, `rgba(225,195,255,${0.3 * a})`);
      g.fillStyle = lg; g.beginPath(); g.moveTo(bl[0], bl[1]); g.lineTo(tl[0], tl[1]); g.lineTo(tr[0], tr[1]); g.lineTo(br[0], br[1]); g.closePath(); g.fill();
      // lantern pairs along the edges, near ones bigger, each flickering
      for (let k = 0; k < 5; k++) {
        const d = k / 4, v = 1.0 - d * 0.16, half = 0.26 - d * 0.19;
        for (const s of [-1, 1]) {
          const [x, y] = P(0.5 + s * half, v), r = (0.09 - d * 0.055) * H * z;
          const f = 0.75 + 0.25 * Math.sin(S.time * (7 + k) + s * 2 + k);
          g.globalAlpha = a * f; g.drawImage(glow, x - r, y - r, r * 2, r * 2);
        }
      }
      // wisps walking the path toward the gate: they show you the way
      for (let k = 0; k < 7; k++) {
        const q = (S.time * 0.12 + k / 7) % 1, wob = Math.sin(S.time * 1.7 + k * 2) * 0.03 * (1 - q);
        const [x, y] = P(0.5 + wob + (k % 2 ? 0.04 : -0.04) * (1 - q), 1.0 - q * 0.16), r = (0.03 - q * 0.018) * H * z;
        g.globalAlpha = a * Math.sin(q * Math.PI) * 0.9; g.drawImage(moon, x - r, y - r, r * 2, r * 2);
      }
      g.restore(); g.globalAlpha = 1;
    }

    /* fog over the Count's feet, so he stands in the scene (drawn on the fx canvas, above the painting) */
    const mist = (() => { const c = document.createElement('canvas'); c.width = 256; c.height = 64; const x = c.getContext('2d'); const r = x.createRadialGradient(128, 32, 0, 128, 32, 128); r.addColorStop(0, 'rgba(70,52,92,.85)'); r.addColorStop(1, 'rgba(70,52,92,0)'); x.fillStyle = r; x.fillRect(0, 0, 256, 64); return c; })();
    function feet(g, S, W, H) {
      if (shown < 0.02) return;
      const r = count.getBoundingClientRect(), k = W / innerWidth;
      const w = r.width * 2.2 * k, h = r.height * 0.22 * k, x = (r.left + r.width / 2) * k + Math.sin(S.time * 0.4) * w * 0.05, y = r.bottom * k - h * 0.35;
      g.globalAlpha = shown * (cur === 'e-hall' ? 0.55 : 0.8); g.drawImage(mist, x - w / 2, y - h / 2, w, h); g.globalAlpha = 1;
    }

    /* the hall: slow shafts of moonlight from the tall windows, with dust in them */
    const dust = Array.from({ length: 60 }, (_, i) => ({ s: (i * 0.6180339) % 1, h: (i * 0.4142) % 1, sp: 0.2 + ((i * 0.7321) % 1) * 0.5 }));
    function hall(g, S, W, H, lx) {
      if (S.room) return;
      g.save(); g.globalCompositeOperation = 'lighter';
      const beams = [[0.86, -0.05, 0.56, 0.95, 0.10], [0.95, 0.0, 0.70, 1.0, 0.08], [0.14, -0.05, 0.40, 0.95, 0.05]];
      beams.forEach(([x0, y0, x1, y1, a], i) => {
        const pulse = a * (0.75 + 0.25 * Math.sin(S.time * 0.35 + i * 2)), wd = W * 0.07;
        const X0 = x0 * W + lx * 0.6, X1 = x1 * W + lx * 1.1;
        const lg = g.createLinearGradient(X0, y0 * H, X1, y1 * H); lg.addColorStop(0, `rgba(200,180,255,${pulse})`); lg.addColorStop(1, 'rgba(200,180,255,0)');
        g.fillStyle = lg; g.beginPath(); g.moveTo(X0 - wd * 0.4, y0 * H); g.lineTo(X0 + wd * 0.4, y0 * H); g.lineTo(X1 + wd, y1 * H); g.lineTo(X1 - wd, y1 * H); g.closePath(); g.fill();
        for (let k = i; k < dust.length; k += 3) {
          const d = dust[k], q = (d.h + S.time * 0.02 * d.sp) % 1, x = X0 + (X1 - X0) * q + (d.s - 0.5) * wd * (0.8 + q), y = (y0 + (y1 - y0) * q) * H;
          g.globalAlpha = 0.5 * Math.sin(q * Math.PI) * (0.6 + 0.4 * Math.sin(S.time * 2 + k)); g.fillStyle = '#efe4ff'; g.fillRect(x, y, 2, 2);
        }
        g.globalAlpha = 1;
      });
      g.restore();
    }

    /* the gold doors along both walls of the hall, shrinking toward the far end (wide screens);
       a two-row arcade on a phone, so every sign can be read */
    const LEFT = [0.2, 0.45, 0.62, 0.76, 0.87], RIGHT = [0.32, 0.55, 0.70, 0.82];
    function layoutDoors(box) {
      const ds = [...box.querySelectorAll('.m-door')], wide = innerWidth / innerHeight > 1.05 && innerWidth > 700;
      const home = wide ? anchor : root;          // wide: the doors sit in the painting and move with it; phone: a flat arcade
      if (box.parentNode !== home) home.insertBefore(box, wide ? null : root.querySelector('.m-bar'));
      box.classList.toggle('m-persp', wide); box.classList.toggle('m-arcade', !wide);
      ds.forEach((b, k) => {
        if (!wide) { b.removeAttribute('style'); b.classList.remove('m-far'); return; }
        const left = k < LEFT.length, d = left ? LEFT[k] : RIGHT[(k - LEFT.length) % RIGHT.length], s = left ? -1 : 1;
        const vy = 0.67, h = 0.34 * (1 - d) + 0.05, x = 0.5 + s * (0.30 * (1 - d) + 0.06), yb = vy + (1 - vy) * (1 - d) * 0.62;   // hall.webp: far door at (0.5, 0.67)
        b.classList.toggle('m-far', d >= 0.6);   // far doors: the sign shows when chosen
        b.style.cssText = `left:${(x * 100).toFixed(2)}%;top:${((yb - h) * 100).toFixed(2)}%;height:${(h * 100).toFixed(2)}%;z-index:${Math.round(100 - d * 100)};--ry:${-s * 38}deg;--fs:${(0.45 + (1 - d) * 0.6).toFixed(2)}`;
      });
    }

    return { update, path, feet, hall, layoutDoors, count };
  }

  window.MovieScene = { create };
})();
