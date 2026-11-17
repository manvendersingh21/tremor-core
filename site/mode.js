/* LIVE or DEMO. If GET /api/stats answers (make web, the real backend), the page shows live data.
   Otherwise (a public link such as GitHub Pages, or the backend is down) it reads demo.json: saved results built by
   site/build.py from bench/*.md and bench/*.csv. Every saved number names its file. Nothing here invents a number.
   If the backend goes down mid-session the page falls to DEMO (badges update through the 'chimera-mode' event), and
   it goes back to LIVE when /api/stats answers again. */
(function () {
  'use strict';
  const here = document.currentScript ? new URL('.', document.currentScript.src).href : new URL('.', location.href).href;
  const forced = /[?&]demo=1\b/.test(location.search);   // ?demo=1: what a judge sees on the public link
  let mode = null, probe = null, saved = null, wasLive = false, watch = 0;
  function get(url, ms) {
    const c = new AbortController(), t = setTimeout(() => c.abort(), ms);
    return fetch(url, { cache: 'no-store', signal: c.signal }).finally(() => clearTimeout(t));
  }
  function set(m) {
    if (m === mode) return;
    mode = m; probe = Promise.resolve(m);
    if (m === 'live') wasLive = true;
    if (m === 'demo' && wasLive && !watch) watch = setInterval(async () => { if (await ok()) { clearInterval(watch); watch = 0; set('live'); } }, 10000);
    document.dispatchEvent(new CustomEvent('chimera-mode', { detail: m }));
  }
  async function ok() {
    try { const r = await get('/api/stats', 3000); if (!r.ok) return null; const j = await r.json(); return j && (j.global || j.session) ? j : null; } catch (e) { return null; }
  }
  /* 'live' or 'demo' */
  function detect() {
    if (probe) return probe;
    if (forced) { set('demo'); return probe; }
    probe = ok().then((j) => { set(j ? 'live' : 'demo'); return mode; });
    return probe;
  }
  function demo() { return saved || (saved = fetch(here + 'demo.json').then((r) => { if (!r.ok) throw new Error('demo.json ' + r.status); return r.json(); })); }
  /* /api/stats when live; if it stops answering, the page falls to DEMO and gets demo.json's saved block */
  async function stats() {
    if ((await detect()) === 'live') { const j = await ok(); if (j) return j; set('demo'); }
    return (await demo()).stats;
  }
  function paint(el, m) {
    el.className = 'mode-badge ' + m;
    el.textContent = m === 'live' ? 'LIVE' : 'DEMO · saved results';
    el.title = m === 'live' ? 'Live data from the backend on this machine (/api/stats)' : 'No backend answers, so the page shows saved results from bench/*.md and bench/*.csv (site/demo.json)';
  }
  /* a LIVE or DEMO badge that follows the mode */
  async function badge(el) {
    document.addEventListener('chimera-mode', (e) => paint(el, e.detail));
    const m = await detect(); paint(el, m); return m;
  }
  /* DEMO chat: the saved question closest to a typed one, by word overlap (Jaccard) after the same lead-in
     stripping as the backend (packages/chimera-core/cache/band.py). No model and no embedding in the browser.
     Numbers and "not" must agree, so "2 apples" never matches "3 apples". Returns {ex, sim, ok}: ok = sim >= bar. */
  const LEAD = ['i would like to know', 'i want to know', 'let me know', 'do you know', 'please', 'kindly', 'can you', 'could you', 'would you',
    'tell me', 'show me', 'give me', 'what is', 'whats', 'what are', 'hey', 'hi', 'hello'];
  const STOP = new Set('the a an of in on at to for is are was were be does do did what which who whom how when where why that this it its by with and or from'.split(' '));
  const NEG = new Set(['not', 'no', 'never', 'without', 'cannot', 'cant', 'dont', 'doesnt', 'isnt']);
  function words(q) {
    let s = String(q).toLowerCase().replace(/['\u2019]/g, '').replace(/[^a-z0-9+\-*/=<>%^.]+/g, ' ').replace(/(^|\s)\.+|\.+(\s|$)/g, ' ').trim();
    for (let again = true; again;) { again = false; for (const p of LEAD) if (s === p || s.startsWith(p + ' ')) { s = s.slice(p.length).trim(); again = true; break; } }
    return s.split(/\s+/).filter((w) => w && !STOP.has(w)).map((w) => (w.length > 3 && /[a-z]s$/.test(w) && !/ss$/.test(w) ? w.slice(0, -1) : w));
  }
  const nums = (ws) => ws.filter((w) => /\d/.test(w)).sort().join(' '), neg = (ws) => ws.some((w) => NEG.has(w));
  function closest(q, examples, bar) {
    bar = bar == null ? 0.6 : bar;
    const a = words(q), A = new Set(a);
    let best = null;
    for (const ex of examples || []) {
      const b = words(ex.q), B = new Set(b);
      const inter = [...A].filter((w) => B.has(w)).length, uni = new Set([...A, ...B]).size;
      const sim = Math.round((uni ? inter / uni : 0) * 100) / 100;
      const clash = nums(a) !== nums(b) ? 'numbers differ' : neg(a) !== neg(b) ? 'one says not' : '';   // never served
      if (!best || sim > best.sim) best = { ex, sim, clash };
    }
    return best ? Object.assign(best, { ok: best.sim >= bar && !best.clash, bar }) : null;
  }
  window.ChimeraMode = { detect, demo, stats, badge, closest, now: () => mode, base: here };
})();
