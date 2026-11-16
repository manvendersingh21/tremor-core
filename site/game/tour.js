/* The guided tour: press T (or the Tour button) and Count Cuspid walks you through the castle, one stop per room,
   in about 3 minutes, ending on the cost chart in the Ledger. The stops and their words come from demo.json
   (site/demo.py tour(), numbers read from bench/*.md); site/docs/tour_script.md is the same list as a video script.
   It drives the walk through window.MovieGame (site/game/walk.js). Esc or T ends it. Animation never stops. */
(function () {
  'use strict';
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let on = false, skip = null, el = null, started = 0;
  const T = { toggle, start, stop, running: () => on, last: null };

  function ui() {
    if (el) return el;
    el = document.createElement('div');
    el.className = 'm-tour'; el.hidden = true; el.setAttribute('role', 'region'); el.setAttribute('aria-label', 'Guided tour');
    el.innerHTML = '<div class="m-tour-h"><b>Count Cuspid</b><span id="m-tour-n"></span></div><p id="m-tour-say" aria-live="polite"></p>' +
      '<div class="m-tour-p" aria-hidden="true"><i id="m-tour-fill"></i></div>' +
      '<div class="m-tour-b"><button type="button" class="m-btn m-gold" id="m-tour-next">Next stop</button><button type="button" class="m-btn" id="m-tour-end">End tour (Esc)</button></div>';
    (document.querySelector('.m-root') || document.body).appendChild(el);
    el.querySelector('#m-tour-next').addEventListener('click', () => { if (skip) skip(); });
    el.querySelector('#m-tour-end').addEventListener('click', stop);
    return el;
  }
  function wait(ms) { return new Promise((r) => { const t = setTimeout(r, ms); skip = () => { clearTimeout(t); skip = null; r(); }; }); }
  async function until(f, ms) { const t0 = performance.now(); while (on && !f() && performance.now() - t0 < ms) await sleep(80); }

  async function go(G, s) {
    const S = G.state, last = G.segs.length - 1;
    if (s.at === 'landing') { if (S.panel) G.closePanel(); G.jump(0, false); return; }
    if (s.at === 'walk') {   // a real walk-in: W held, gates and door open as you reach them (about 4 s)
      if (S.hall) return;
      S.keys.add('w'); await until(() => S.hall, 9000); S.keys.delete('w'); return;
    }
    if (S.panel) { G.closePanel(); await sleep(350); }
    if (!S.hall) { G.jump(last, true); G.enterHall(); }
    if (s.at === 'hall') return;
    const k = G.doors.findIndex((d) => d.id === s.room); if (k < 0) return;
    S.door = k; G.use();
    await until(() => S.panel, 6000);
    if (s.chart) { await sleep(500); const c = document.querySelector('.m-cost'); if (c) c.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  }

  async function start() {
    const G = window.MovieGame; if (on || !G || !window.ChimeraMode) return;
    let stops;
    try { stops = (await window.ChimeraMode.demo()).tour; } catch (e) { return; }
    on = true; G.state.tour = true; started = performance.now();
    const box = ui(); box.hidden = false; box.classList.remove('done');
    const fill = box.querySelector('#m-tour-fill'), say = box.querySelector('#m-tour-say'), n = box.querySelector('#m-tour-n');
    for (let i = 0; i < stops.length && on; i++) {
      const s = stops[i];
      n.textContent = `Tour · stop ${i + 1} of ${stops.length}`;
      say.textContent = s.say; if (!s.room) G.say(s.say);
      fill.style.transition = 'none'; fill.style.width = (i / stops.length * 100) + '%';
      await go(G, s); if (!on) break;
      void fill.offsetWidth; fill.style.transition = `width ${s.secs}s linear`; fill.style.width = ((i + 1) / stops.length * 100) + '%';
      await wait(s.secs * 1000);
    }
    if (!on) return;
    T.last = { secs: Math.round((performance.now() - started) / 100) / 10, stops: stops.length };
    on = false; G.state.tour = false; skip = null;
    n.textContent = 'Tour over'; say.textContent = 'That was the whole castle. Press T to take the tour again, or walk on your own.';
    box.classList.add('done'); box.querySelector('#m-tour-next').hidden = true;
    setTimeout(() => { if (!on) box.hidden = true; box.querySelector('#m-tour-next').hidden = false; }, 7000);
  }
  function stop() {
    if (!on) { if (el) el.hidden = true; return; }
    on = false; if (skip) skip();
    const G = window.MovieGame; if (G) { G.state.tour = false; G.state.keys.delete('w'); }
    T.last = { secs: Math.round((performance.now() - started) / 100) / 10, stopped: true };
    if (el) el.hidden = true;
  }
  function toggle() { return on ? stop() : start(); }
  addEventListener('keydown', (e) => {
    if (!on || e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === 'escape' || (k === 't' && !/^(INPUT|TEXTAREA)$/.test(e.target.tagName))) { stop(); if (k === 't') e.stopImmediatePropagation(); }
  }, true);
  window.CastleTour = T;
})();
