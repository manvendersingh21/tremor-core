/* HTML panels over the 3D castle: guide chat, savings board, Dashboard, Chat, Evals.
   Data: /api/stats, /api/health, /events (dashboard.js), /api/chat (chat.js), /api/bench + /api/evals (dashboard.js).
   Fields the backend has not shipped yet are shown as "pending API" (requested in docs/api.md), never invented. */
(function () {
  'use strict';
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const n = (v) => (v == null ? '–' : Number(v).toLocaleString());
  const usd = (v) => (v == null ? '–' : '$' + (v < 0.01 ? Number(v).toFixed(5) : Number(v).toFixed(4)));
  const pct = (v) => (v == null ? '–' : Math.round(v * 100) + '%');
  const PENDING = '<span class="p-pend" title="The backend has not shipped this field yet. Requested in docs/api.md.">pending API</span>';
  const getJSON = async (u) => { try { const r = await fetch(u, { cache: 'no-store' }); return r.ok ? await r.json() : null; } catch (e) { return null; } };

  /* Dashboard blocks live in #dash-store in index.html; a panel borrows one while open */
  function borrow(host, id) {
    const store = document.getElementById('dash-store'), blk = store && store.querySelector(`[data-dash="${id}"]`), bar = document.getElementById('dash-bar');
    if (!blk) return () => {};
    const wrap = document.createElement('div'); wrap.className = 'w-dash'; host.appendChild(wrap);
    const moved = [bar, blk].filter(Boolean); moved.forEach((x) => { wrap.appendChild(x); x.hidden = false; });
    if (window.Dash) window.Dash.enter(id);
    return () => moved.forEach((x) => { x.hidden = true; store.appendChild(x); });
  }

  function statCards(s, label) {
    if (!s) return `<p class="lbl">Could not read /api/stats.</p>`;
    const ch = s.cache_hits || {};
    return `<div class="p-cards">
      <div class="p-card"><b>${n(s.tokens_kept_off_big)}</b><span>tokens kept off the big model</span></div>
      <div class="p-card"><b>${usd(s.dollars_saved)}</b><span>dollars saved (spent ${usd(s.dollars_spent)})</span></div>
      <div class="p-card"><b>${n(s.gpu_calls_avoided)}</b><span>GPU calls avoided</span></div>
      <div class="p-card"><b>${pct(s.hit_rate)}</b><span>cache hit rate · ${n(s.calls)} calls</span></div>
      <div class="p-card"><b>${n(ch.exact || 0)} / ${n(ch.shared || 0)}</b><span>hits: exact (old rows) / Supabase</span></div>
      <div class="p-card"><b>${n(s.big_calls_avoided)}</b><span>big-model calls avoided</span></div>
    </div><p class="lbl">${esc(label)}. Source: <code>/api/stats</code>.</p>`;
  }

  function traceList(rows, max) {
    if (!rows.length) return `<p class="lbl">No question asked from this browser yet. Ask the guide or open the Chat door. Server-side recent traces: ${PENDING}.</p>`;
    return `<ol class="p-traces">` + rows.slice(0, max).map((r) => `<li><div class="p-q">${esc(r.q)}</div>
      <div class="p-steps">${r.steps.map((x) => `<span>${esc(x)}</span>`).join('<i>→</i>')}</div>
      <div class="p-tag"><b>${esc(r.cache ? 'cache HIT' : r.tier)}</b>${r.cos != null ? ' · cos ' + (+r.cos).toFixed(3) : ''} · ${esc(r.model || (r.cache ? 'no model' : ''))} · ${n(r.tokens_in)}→${n(r.tokens_out)} tok · ${r.ms != null ? Math.round(r.ms) + ' ms' : ''} · ${usd(r.dollars)}</div></li>`).join('') + '</ol>';
  }

  function spark(points) { // cumulative tokens saved over the telemetry stream
    if (points.length < 2) return '<p class="lbl">Waiting for telemetry events on <code>/events</code>.</p>';
    const W = 560, H = 120, max = points[points.length - 1] || 1;
    const d = points.map((v, i) => `${(i / (points.length - 1) * W).toFixed(1)},${(H - v / max * (H - 10)).toFixed(1)}`).join(' ');
    return `<svg viewBox="0 0 ${W} ${H}" class="p-spark" role="img" aria-label="Tokens saved over time, ${n(max)} in total"><polyline points="${d}" fill="none" stroke="#e9c46a" stroke-width="2.5"/></svg>
      <p class="lbl">${n(max)} tokens saved over the last ${points.length} events from ${esc(spark.src || 'the telemetry log')} (<code>/events</code>). A per-day series: ${PENDING}.</p>`;
  }

  /* ---------------- panels ---------------- */
  const P = {};

  P.board = async (pb, ctx) => {
    const st = ctx.stats || await getJSON('/api/stats');
    pb.innerHTML = `<p class="lead">The board in the hall reads the same numbers. Every call on this machine is logged with its tier, tokens, latency and dollars.</p>` +
      statCards(st && st.global, 'All calls logged on this machine') + statCards(st && st.session, 'Since this server started');
  };

  P.guide = (pb, ctx) => chatWithSide(pb, {
    greeting: `Good evening, I am ${ctx.guideName || 'the guide'}. Ask me anything: your question goes through the real ladder (the Supabase cache, then our own GPU 30B, then the 763B in the cloud), and you see where each answer came from. When you are done, take the grand staircase. Upstairs are three doors: Dashboard, Chat and Evals.`,
    side: 'guide',
  });

  P.chat = (pb) => chatWithSide(pb, { greeting: 'I am Count Cuspid. This is my room. Ask, and watch every step the router takes: cache, 30B, 763B. The side panel counts what it cost.', side: 'chat' });

  function chatWithSide(pb, o) {
    pb.classList.add('flush'); pb.style.padding = '.8rem';
    pb.innerHTML = `<div class="p-chatwrap"><div class="p-chat"></div><aside class="p-side" aria-label="Chat statistics"></aside></div>`;
    const side = pb.querySelector('.p-side');
    const draw = async () => {
      const st = await getJSON('/api/stats'), mine = window.CastleChat ? window.CastleChat.history() : [];
      const today = new Date().toDateString(), t = mine.filter((r) => new Date(r.ts).toDateString() === today);
      const tok = (rs) => rs.reduce((a, r) => a + (r.tokens_in || 0) + (r.tokens_out || 0), 0);
      const types = {}; mine.forEach((r) => { const x = types[r.type] = types[r.type] || { n: 0, tok: 0, hit: 0 }; x.n++; x.tok += (r.tokens_in || 0) + (r.tokens_out || 0); if (r.cache) x.hit++; });
      const g = st && st.global, s = st && st.session;
      side.innerHTML = (o.side === 'guide' ? `<h3>The castle</h3><p>Outside: the gate. Here: the Great Hall, my desk and the savings board. Up the grand staircase: <b>Dashboard</b> (savings, database, how it answered), <b>Chat</b> (the Count's room) and <b>Evals</b> (tests and benchmarks). Press <kbd>M</kbd> for the map.</p>` : '') +
        `<h3>Cache hit rate</h3><p><b>${pct(g && g.hit_rate)}</b> of ${n(g && g.calls)} calls on this machine; <b>${pct(s && s.hit_rate)}</b> of ${n(s && s.calls)} since the server started.</p>
         <h3>Tokens used today</h3><p><b>${n(tok(t))}</b> in ${t.length} questions from this browser. All users: ${PENDING}</p>
         <h3>Tokens per task</h3>${Object.keys(types).length ? `<table class="p-tbl"><tr><th>Task</th><th>Asked</th><th>Tokens</th><th>Cache hits</th></tr>${Object.entries(types).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v.n}</td><td>${n(v.tok)}</td><td>${v.hit}</td></tr>`).join('')}</table>` : '<p>Nothing asked from this browser yet.</p>'}
         <p class="lbl">Task type is guessed here from the question (code, lookup, chat). Server-side grouping: ${PENDING}</p>`;
    };
    const close = window.CastleChat.mount(pb.querySelector('.p-chat'), { endpoint: '/api/chat', health: '/api/health', greeting: o.greeting, placeholder: o.side === 'guide' ? 'Ask the guide' : 'Ask the Count', onFinal: () => setTimeout(draw, 50) });
    draw();
    return close;
  }

  P.dashboard = (pb, ctx) => {
    pb.innerHTML = `<div class="p-dash"><section><h3>Savings</h3><div id="p-st"></div></section>
      <section><h3>Tokens saved over time</h3><div id="p-sp"></div></section>
      <section><h3>Database size</h3><table class="p-tbl">
        <tr><th>Store</th><th>Rows or nodes</th><th>Size</th></tr>
        <tr><td>Supabase cache (prompts)</td><td>${PENDING}</td><td>${PENDING}</td></tr>
        <tr><td>Memory: teacher_pairs</td><td>${PENDING}</td><td>${PENDING}</td></tr>
        <tr><td>Neo4j graph</td><td>${PENDING} nodes, ${PENDING} edges</td><td>–</td></tr></table>
        <p class="lbl" id="p-db"></p></section>
      <section><h3>How it answered (this browser)</h3><div id="p-tr"></div></section></div>`;
    const q = (id) => pb.querySelector('#' + id);
    (async () => {
      const st = ctx.stats || await getJSON('/api/stats');
      q('p-st').innerHTML = statCards(st && st.global, 'All calls logged on this machine');
      const h = await getJSON('/api/health');
      q('p-db').textContent = h && h.supabase ? `Supabase is ${h.supabase.up ? 'up' : 'down'}${h.supabase.lookup_ms != null ? ', lookup ' + Math.round(h.supabase.lookup_ms) + ' ms' : ''}.` : 'Supabase reachability: not reported by /api/health.';
    })();
    q('p-tr').innerHTML = traceList(window.CastleChat ? window.CastleChat.history() : [], 8);
    // live series from the telemetry stream
    const pts = []; let sum = 0, es = null;
    let src = 'this machine\'s telemetry log';
    try {
      es = new EventSource('/events');
      es.onmessage = (m) => { try { const e = JSON.parse(m.data); if (e._meta) { src = /demo/.test(e._meta.source) ? 'DEMO data (make demo), not real calls' : e._meta.source; return; } sum += e.tokens_saved || 0; pts.push(sum); if (pts.length > 400) pts.shift(); spark.src = src; q('p-sp').innerHTML = spark(pts); } catch (_) { /* skip a bad line */ } };
    } catch (e) { /* no EventSource */ }
    q('p-sp').innerHTML = spark(pts);
    const back = borrow(pb, 'observatory');
    return () => { if (es) es.close(); back(); };
  };

  P.evals = (pb) => {
    pb.innerHTML = `<p class="lead">Every benchmark run in one log: single runs, no repeats, losses in red. Sources are the <code>bench/results*.md</code> files.</p>`;
    return borrow(pb, 'ledger');
  };

  window.CastlePanels = { open: (id, pb, ctx) => { const f = P[id]; if (!f) { pb.textContent = 'Unknown room.'; return null; } const r = f(pb, ctx || {}); return typeof r === 'function' ? r : null; } };
})();
