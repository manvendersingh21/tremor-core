/* The bat's room: chat + live routing trace + local monitor strip. UI only.
   Talks to POST /api/chat (SSE, docs/api.md: embed, cache_local, cache_shared, decide, call, draft, final, answer, error, done)
   and polls GET /api/health every 2 s. If the endpoint is missing it falls back to a labelled MOCK so the UI still runs. */
(function () {
  'use strict';
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pick = (o, ...ks) => { for (const k of ks) if (o && o[k] != null) return o[k]; return undefined; };
  const ms = (v) => (v == null ? '' : v < 10 ? v.toFixed(1) + ' ms' : Math.round(v) + ' ms');
  const usd = (v) => (!v ? '$0' : '$' + (v < 0.01 ? v.toPrecision(2) : v.toFixed(4)));
  const CLOUD = /cloud|top|crusoe|gmi|deepseek|modal|h200|120b|763b/i;  // tier names that are NOT self-hosted
  const THRESH = 0.97, GATE = 0.95, MAXLEN = 2000;  // gate/threshold are overwritten by the event values

  function mount(host, cfg) {
    cfg = cfg || {};
    const url = cfg.endpoint || 'api/chat', healthUrl = cfg.health || 'api/health';
    let mock = false, dead = false, busy = false;
    const totals = { turns: 0, hits: 0, gpuAvoided: 0, usdSaved: 0, kept: 0 };
    host.innerHTML = `<div class="c-wrap">
      <div class="c-col">
        <div class="c-mon" id="c-mon" aria-label="Laptop monitor"></div>
        <div class="c-log" id="c-log" role="log" aria-live="polite"></div>
        <form class="c-form" id="c-form"><input id="c-in" maxlength="${MAXLEN}" autocomplete="off" aria-label="Ask the bat" placeholder="Ask the bat anything (max ${MAXLEN} characters)"><button class="w-btn" id="c-send" type="submit">Send</button></form>
        <div class="c-mock" id="c-mock" hidden>Backend not connected: the replies below are a local MOCK, not a model.</div>
      </div>
      <div class="c-trace" id="c-trace" aria-label="Routing trace"><h4>ROUTING TRACE</h4><div id="c-tr"><p style="color:#cdb8d8">Ask something. Each step the router takes will appear here, live.</p></div><div class="t-sum" id="c-sum"></div></div></div>`;
    const $ = (s) => host.querySelector(s), log = $('#c-log'), input = $('#c-in');
    addMsg('bat', 'Squeak. I am the castle’s one agent. Ask me anything and watch the road your question takes: shared cache, the self-hosted GPU 30B, then the big cloud model.');
    input.focus();

    function addMsg(who, text) { const d = document.createElement('div'); d.className = 'c-msg ' + who; d.textContent = text; log.appendChild(d); log.scrollTop = log.scrollHeight; return d; }

    /* ---------- trace ---------- */
    let T = null;
    function newTrace(q) {
      const tr = $('#c-tr');
      tr.innerHTML = `<div class="t-row"><span class="t-k">Question</span><span class="t-v">${esc(q.length > 80 ? q.slice(0, 80) + '…' : q)}</span></div>
        <div class="t-row" id="t-embed"><span class="t-k">1 Embedding</span><span class="t-v">…</span></div>
        <div class="t-lanes">
          <div class="t-lane run" id="t-local"><h5>Local cache (SQLite)</h5><div class="b">looking…</div></div>
          <div class="t-lane run" id="t-shared"><h5>Shared cache (Supabase)</h5><div class="b">looking…</div></div>
          <div class="t-lane run" id="t-draft"><h5>GPU 30B (self-hosted)</h5><div class="b">waiting…</div></div>
          <div class="t-lane run" id="t-mem"><h5>Memory</h5><div class="b">looking for solved examples…</div></div>
        </div>
        <div class="t-row" id="t-cos"><span class="t-k">2 Cosine</span><span class="t-v">waiting for the caches…</span></div>
        <div class="t-row" id="t-decide"><span class="t-k">3 Decision</span><span class="t-v">…</span></div>
        <div class="t-row" id="t-call"><span class="t-k">4 Call</span><span class="t-v">…</span></div>
        <div class="t-row" id="t-final"><span class="t-k">5 Final</span><span class="t-v">…</span></div>`;
      T = { q, sim: null, matched: null, guard: null, el: (id) => tr.querySelector('#' + id) };
    }
    const setRow = (id, html) => { const r = T.el(id); if (r) r.querySelector('.t-v').innerHTML = html; };
    const selfTitle = (tier) => { // the lane says which self-hosted model really answered: the 3B is an experiment tier, not the product
      const h = T.el('t-draft').querySelector('h5'); h.textContent = /local|3b|mac|laptop/i.test(tier || '') ? 'Mac 3B (experiment, not the 30B)' : 'GPU 30B (self-hosted)'; };
    const lane = (id, cls, html) => { const r = T.el(id); if (!r) return; r.className = 't-lane ' + cls; r.querySelector('.b').innerHTML = html; };
    function cosine() {
      if (T.sim == null) return;
      const pct = Math.max(0, Math.min(1, T.sim)) * 100, th = T.th || THRESH;
      setRow('t-cos', `<div class="t-bar" role="img" aria-label="best cosine ${T.sim.toFixed(3)} against threshold ${th}"><i style="width:${pct}%"></i><s style="left:${th * 100}%"></s></div>` +
        `best <b>${T.sim.toFixed(3)}</b> vs threshold <b>${th}</b> ${T.sim >= th ? '<span class="t-chip good">hit</span>' : '<span class="t-chip warn">below</span>'}` +
        (T.matched ? `<br>matched: “${esc(String(T.matched).slice(0, 80))}”` : '') + `<br>guard: ${esc(T.guard || 'no candidate')}`);
    }
    function onEvent(name, d) {
      if (!T) return;
      d = d || {};
      if (name === 'embed') setRow('t-embed', `done <b>${ms(pick(d, 'ms', 'latency_ms'))}</b>${pick(d, 'dim') ? ' · ' + d.dim + '-dim vector' : ''}`);
      else if (name === 'cache_local' || name === 'cache_shared') {
        if (name === 'cache_shared') T.shared = true; else T.local = true;
        const id = name === 'cache_local' ? 't-local' : 't-shared', hit = !!pick(d, 'hit'), m = pick(d, 'ms', 'latency_ms');
        const sim = pick(d, 'score', 'sim', 'similarity'), st = pick(d, 'status'), err = st === 'timeout' || st === 'down' ? st : pick(d, 'error'), kind = pick(d, 'kind', 'source');
        if (pick(d, 'threshold') != null) T.th = d.threshold;
        if (st === 'skipped') { lane(id, 'miss', 'skipped<br>local cache already hit'); return; }
        if (sim != null && (T.sim == null || sim > T.sim)) { T.sim = sim; const mp = pick(d, 'matched', 'matched_prompt'); if (mp) T.matched = mp; }
        const gd = pick(d, 'guard'); if (gd) T.guard = gd;
        if (hit) T.hit = { kind: kind || 'semantic', where: name === 'cache_local' ? 'local' : 'shared' };
        lane(id, err ? 'err' : hit ? 'hit' : 'miss', err ? `<b>${esc(err)}</b><br>${err === 'down' ? 'SQLite answered instead' : 'over budget'}<br>${ms(m)}` : `<b>${hit ? 'HIT' : 'MISS'}</b>${kind ? ' · ' + esc(kind) : ''}<br>${ms(m)}${sim != null ? '<br>cos ' + (+sim).toFixed(3) : ''}`);
        cosine();
      } else if (name === 'draft') {
        T.drafted = true; selfTitle(pick(d, 'tier'));
        const c = pick(d, 'confidence', 'mean_prob', 'conf'), gate = pick(d, 'gate', 'threshold') ?? GATE, err = pick(d, 'error', 'unavailable'), skipped = pick(d, 'skipped');
        lane('t-draft', err ? 'err' : skipped ? 'miss' : c != null && c >= gate ? 'hit' : 'miss',
          err ? 'self-hosted model unreachable' : skipped ? `skipped<br>${esc(typeof skipped === 'string' ? skipped : 'heavy task')}` :
            `conf <b>${c == null ? '?' : (+c).toFixed(3)}</b> / gate ${gate}<div class="t-bar"><i style="width:${Math.min(1, c || 0) * 100}%"></i><s style="left:${gate * 100}%"></s></div>${ms(pick(d, 'ms', 'latency_ms'))}${pick(d, 'tokens') != null ? ' · ' + d.tokens + ' tok' : ''}`);
      } else if (name === 'decide') {
        const a = pick(d, 'tier', 'action') || '?', r = T.el('t-decide').querySelector('.t-v');
        r.innerHTML = (T.decided ? r.innerHTML + '<br>↑ ' : '') + `<b>${esc(a)}</b>${pick(d, 'reason') ? ' · ' + esc(d.reason) : ''}`; T.decided = true;
      } else if (name === 'call') {
        const r = T.el('t-call').querySelector('.t-v'), line = `<b>${esc(pick(d, 'tier') || '')}</b> ${esc(pick(d, 'model') || '')} · ${d.ok === false ? '<span class="t-chip warn">failed ' + esc(d.error || '') + '</span>' : ms(pick(d, 'ms')) + ' · in ' + (d.tokens_in ?? '?') + ' / out ' + (d.tokens_out ?? '?') + ' tok'}`;
        r.innerHTML = (T.called ? r.innerHTML + '<br>' : '') + line; T.called = true;
        if (!CLOUD.test(pick(d, 'tier') || '')) { selfTitle(d.tier); if (d.ok === false) lane('t-draft', 'err', 'unreachable<br>' + esc(d.error || '')); else if (!T.drafted) lane('t-draft', 'hit', `<b>${esc(d.tier)}</b> answered<br>${d.tokens_out ?? '?'} tok · ${ms(d.ms)}`); }
      } else if (name === 'memory') {
        // memory events: {retrieved: n, examples: [{prompt, model}], ms} before the call; {stored: bool} after a verified big-model answer
        T.mem = true;
        // backend shape: {op: 'retrieve', chars, ms} then {op: 'store', stored, tier, tests_passed}
        const n = pick(d, 'retrieved', 'count', 'k'), ex = pick(d, 'examples') || [], stored = d.op === 'retrieve' ? undefined : pick(d, 'stored', 'teacher_stored');
        if (d.op === 'retrieve' && n == null) { lane('t-mem', d.chars ? 'hit' : 'miss', d.chars ? `<b>retrieved</b> ${d.chars} chars of solved examples · ${ms(d.ms)}` : `<b>0</b> solved examples retrieved · ${ms(d.ms)}`); return; }
        const r = T.el('t-mem'), prev = r.querySelector('.b').innerHTML;
        if (stored != null) lane('t-mem', stored ? 'hit' : r.className.replace('t-lane ', ''), (/retriev/.test(prev) ? prev + '<br>' : '') + (stored ? '<b>stored as teacher data</b>' : `not stored as teacher data${d.tier ? ' (' + esc(d.tier) + ' is not the big model)' : ''}`));
        else lane('t-mem', n ? 'hit' : 'miss', `<b>${n || 0}</b> solved example${n === 1 ? '' : 's'} retrieved${pick(d, 'ms') != null ? ' · ' + ms(d.ms) : ''}` + ex.slice(0, 2).map((e) => `<br>“${esc(String(e.prompt || e).slice(0, 60))}”`).join(''));
      } else if (name === 'final') finalRow(d);
    }
    function finalRow(d) {
      T.finalized = true;
      const tier = pick(d, 'tier', 'tier_used') || '?', tin = pick(d, 'tokens_in', 'input_tokens'), tout = pick(d, 'tokens_out', 'output_tokens'), cached = pick(d, 'cached_tokens'),
        cost = pick(d, 'dollars', 'usd'), total = pick(d, 'ms', 'total_ms'), kept = pick(d, 'tokens_kept_off_big', 'tokens_saved'), cacheHit = !!pick(d, 'cache') || /cache/.test(tier), avoided = cacheHit || pick(d, 'gpu_call_avoided');
      const self = !CLOUD.test(tier); if (self && !cacheHit) selfTitle(tier);
      if (!T.drafted && !T.called) lane('t-draft', cacheHit ? 'miss' : self ? 'hit' : 'miss', cacheHit ? 'not needed<br>cache answered' : self ? `<b>${esc(tier)}</b> answered<br>${tout ?? '?'} tok · ${ms(total)}` : 'climbed<br>' + esc(tier) + ' answered');
      if (!T.mem) lane('t-mem', 'miss', cacheHit ? 'not needed<br>cache answered' : 'no memory events<br>(module not connected)');
      if (!T.shared) lane('t-shared', 'miss', 'not configured<br>local cache only');
      if (!T.local) lane('t-local', 'miss', 'not in this ladder<br>shared cache only');
      if (!T.decided) setRow('t-decide', cacheHit ? `<b>serve from cache</b> · cosine ≥ ${T.th || THRESH}` : `<b>${esc(tier)}</b> answered`);
      if (!T.called) setRow('t-call', cacheHit ? '<span class="t-chip good">no model called</span>' : `<b>${esc(tier)}</b> ${esc(pick(d, 'model') || '')}`);
      setRow('t-final', `<span class="t-chip ${cacheHit ? 'good' : ''}">${esc(tier)}${d.cache ? ' (' + esc(d.cache) + ' cache)' : ''}</span><span class="t-chip">${esc(pick(d, 'model') || (cacheHit ? 'no model' : 'model unnamed'))}</span>` +
        `<span class="t-chip">in ${tin ?? '?'} / out ${tout ?? '?'} tok</span><span class="t-chip">cached ${cached ?? 0}</span><span class="t-chip">${usd(cost)}</span><span class="t-chip ${total != null && total < 200 && cacheHit ? 'good' : ''}">${ms(total)}</span>` +
        `<span class="t-chip good">${kept ?? 0} tokens kept off the big model</span>${avoided ? '<span class="t-chip good">GPU call avoided</span>' : ''}`);
      totals.turns++; if (cacheHit) totals.hits++; if (avoided || cacheHit) totals.gpuAvoided++; totals.usdSaved += pick(d, 'dollars_saved') ?? 0; totals.kept += kept || 0;
      $('#c-sum').innerHTML = `This chat: <b>${totals.turns}</b> turns · hit rate <b>${Math.round(totals.hits / totals.turns * 100)}%</b> · GPU calls avoided <b>${totals.gpuAvoided}</b> · saved <b>${usd(totals.usdSaved)}</b> · <b>${totals.kept}</b> tokens kept off the big model`;
    }

    /* ---------- sending ---------- */
    $('#c-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const q = input.value.trim().slice(0, MAXLEN); if (!q || busy || dead) return;
      input.value = ''; busy = true; $('#c-send').disabled = true;
      addMsg('me', q); newTrace(q); const t0 = performance.now();
      const out = addMsg('bat', '…'); let text = '', tag = '', gotErr = false;
      const addTag = () => { const s = document.createElement('span'); s.className = 'c-tag'; s.textContent = tag; out.appendChild(s); };
      const on = (name, d) => {
        if (name === 'answer') { text = pick(d, 'text') || ''; out.textContent = text || '(no answer)'; if (tag) addTag(); }
        else if (name === 'error') { gotErr = true; out.textContent = 'The bat flutters. ' + (d.code === 'timeout' ? 'The far towers did not answer in time.' : 'No tier could answer right now. Try again in a moment.'); setRow('t-final', `<span class="t-chip warn">${esc(d.code || 'error')}</span>`); }
        else if (name === 'done') {
          // shortcut: the server sends no `final` on a cache hit yet (docs/api.md says it should); build it from the cache event and browser timing
          if (!T.finalized && T.hit && !gotErr) { const d2 = { tier: T.hit.kind + '_cache', model: null, tokens_in: 0, tokens_out: 0, cached_tokens: 0, dollars: 0, ms: performance.now() - t0, cache: T.hit.where, tokens_kept_off_big: Math.round((q.length + text.length) / 4) }; onEvent('final', d2); tag = `${d2.tier} · no model · 0→0 tok · $0 · ${ms(d2.ms)}`; addTag(); }
          if (!text && !gotErr) out.textContent = '(no answer)';
        }
        else { onEvent(name, d); if (name === 'final') { tag = `${pick(d, 'tier') || ''} · ${pick(d, 'model') || (d.cache ? 'no model' : 'model unnamed')} · ${(d.tokens_in ?? 0)}→${(d.tokens_out ?? 0)} tok · ${usd(pick(d, 'dollars', 'usd'))} · ${ms(pick(d, 'ms', 'total_ms'))}`; if (text) addTag(); } }
        log.scrollTop = log.scrollHeight;
      };
      try { await stream(q, on); }
      catch (err) { if (!text) out.textContent = 'The bat flutters. ' + (err && err.polite ? err.polite : 'No tier is reachable right now. Try again in a moment.'); }
      busy = false; $('#c-send').disabled = false; input.focus();
    });
    async function stream(q, on) {
      if (!mock) {
        let r; try { r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' }, body: JSON.stringify({ prompt: q }) }); } catch (e) { r = null; }
        if (r && (r.status === 429 || r.status === 503)) { const e = new Error('rate'); e.polite = r.status === 429 ? 'The bat is catching its breath. Too many questions; wait ' + (r.headers.get('Retry-After') || 'a few') + ' seconds.' : 'The castle is busy. Try again in a moment.'; throw e; }
        if (r && r.status === 403) { const e = new Error('held'); e.polite = 'That action is risky, so it waits for a person to approve it.'; throw e; }
        if (r && r.ok && r.body) { await sse(r.body, on); return; }
        if (!r || [404, 405, 501].includes(r.status)) { mock = true; $('#c-mock').hidden = false; } else { const e = new Error('http'); e.polite = 'The bat cannot answer right now (' + r.status + ').'; throw e; }
      }
      await mockStream(q, on);
    }
    async function sse(body, on) {
      const rd = body.getReader(), dec = new TextDecoder(); let buf = '';
      for (;;) {
        const { value, done } = await rd.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        let i; while ((i = buf.indexOf('\n\n')) >= 0) {
          const blk = buf.slice(0, i); buf = buf.slice(i + 2); let name = 'message', data = '';
          blk.split('\n').forEach((l) => { if (l.startsWith('event:')) name = l.slice(6).trim(); else if (l.startsWith('data:')) data += l.slice(5).trim(); });
          if (!data) continue; let d; try { d = JSON.parse(data); } catch (e) { continue; }
          if (name === 'message' && d.event) { name = d.event; d = d.data || d; }
          on(name, d);
        }
      }
    }

    /* ---------- MOCK (only when /api/chat does not exist) ---------- */
    const mcache = new Map();
    const wait = (t) => new Promise((r) => setTimeout(r, t));
    async function mockStream(q, on) {
      const key = q.toLowerCase().replace(/\s+/g, ' ').replace(/[?.!]+$/, ''), t0 = performance.now();
      await wait(40); on('embed', { ms: 11.4, dim: 384 });
      const hit = mcache.has(key);
      await Promise.all([
        wait(hit ? 9 : 18).then(() => on('cache_local', { hit, kind: hit ? 'exact' : null, ms: hit ? 9 : 18, score: hit ? 1 : 0.41, threshold: THRESH, guard: hit ? 'off' : null })),
        wait(hit ? 0 : 140).then(() => on('cache_shared', { hit: false, status: hit ? 'skipped' : 'ok', ms: 140, score: 0.38, threshold: THRESH })),
      ]);
      if (hit) { on('final', { tier: 'exact_cache', model: null, tokens_in: 0, tokens_out: 0, cached_tokens: 0, dollars: 0, ms: performance.now() - t0, tokens_kept_off_big: 40, cache: 'exact' }); on('answer', { text: mcache.get(key) }); on('done', {}); return; }
      on('memory', { retrieved: 0, examples: [], ms: 3 }); on('decide', { tier: 'mock-30b', reason: 'cheapest healthy tier' }); await wait(650);
      on('call', { tier: 'mock-30b', model: 'mock', ok: true, ms: 650, tokens_in: 12, tokens_out: 38 }); on('draft', { tier: 'mock-30b', confidence: 0.97, gate: GATE });
      const a = 'MOCK reply (no backend connected): ' + q;
      mcache.set(key, a); on('final', { tier: 'mock-30b', model: 'mock', tokens_in: 12, tokens_out: 38, cached_tokens: 0, dollars: 0, ms: performance.now() - t0, tokens_kept_off_big: 50, cache: null }); on('answer', { text: a }); on('done', {});
    }

    /* ---------- laptop monitor ---------- */
    const chips = [['gpu_tunnel', 'GPU 30B tunnel'], ['supabase', 'Supabase'], ['crusoe', 'Crusoe 763B'], ['gmi', 'GMI'], ['llama', 'Mac 3B (experiment)']];
    function up(v) { if (v == null) return null; if (typeof v === 'boolean') return v; return !!pick(v, 'up', 'ok', 'reachable', 'ready'); }
    function renderHealth(h, isMock) {
      const g = (...k) => pick(h, ...k), out = [];
      chips.forEach(([k, label]) => {
        const v = g(k), u = up(v); if (v === undefined && (k === 'gmi' || k === 'llama')) return;
        const t = v && typeof v === 'object' ? (k === 'llama' && v.tokens_per_s != null ? ` · ${(+v.tokens_per_s).toFixed(1)} tok/s` : pick(v, 'ms', 'lookup_ms') != null ? ` · ${Math.round(pick(v, 'ms', 'lookup_ms'))} ms` : '') : '', extra = t;
        out.push(`<span class="c-chip ${u == null ? 'unk' : u ? 'up' : 'down'}">${label}: <i>${u == null ? (isMock ? '?' : 'not set') : u ? 'up' : 'down'}</i>${extra}</span>`);
      });
      const ram = g('ram'), ramv = ram && typeof ram === 'object' ? ram.free_mb : undefined;
      out.push(`<span class="c-chip ${ramv == null ? 'unk' : ramv < 1500 ? 'down' : 'up'}">RAM free: <b>${ramv == null ? '?' : ramv >= 1024 ? (ramv / 1024).toFixed(1) + ' GB' : Math.round(ramv) + ' MB'}</b></span>`);
      if (h.modal && h.modal.state) out.push(`<span class="c-chip unk">Modal H200: <b>${esc(h.modal.state)}</b></span>`);
      if (isMock) out.push('<span class="c-chip unk">health: not connected</span>');
      $('#c-mon').innerHTML = out.join('');
    }
    async function poll() {
      if (!host.isConnected || dead) return;
      try { const r = await fetch(healthUrl, { cache: 'no-store' }); if (!r.ok) throw 0; renderHealth(await r.json(), false); }
      catch (e) { renderHealth({}, true); }
      timer = setTimeout(poll, 2000);
    }
    let timer = setTimeout(poll, 0);
    return function unmount() { dead = true; clearTimeout(timer); };
  }
  window.CastleChat = { mount, THRESH, GATE };
})();
