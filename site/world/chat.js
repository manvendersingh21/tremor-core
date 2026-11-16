/* The bat's room: chat + live routing trace + local monitor strip. UI only.
   Talks to POST /api/chat (SSE, docs/api.md: embed, cache_shared, memory, decide, call, draft, final, answer, error, done)
   and polls GET /api/health every 2 s. With no backend (DEMO, site/mode.js) it replays saved real measurements from
   demo.json (bench/results_backend.csv) for a few saved questions, labelled as replays. It never makes up a reply. */
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
    let dead = false, busy = false;
    const totals = { turns: 0, hits: 0, gpuAvoided: 0, usdSaved: 0, kept: 0 };
    host.innerHTML = `<div class="c-wrap">
      <div class="c-col">
        <div class="c-mon" id="c-mon" aria-label="Laptop monitor"></div>
        <div class="c-mock" id="c-mock" hidden></div>
        <div class="c-chips" id="c-chips" hidden></div>
        <div class="c-log" id="c-log" role="log" aria-live="polite"></div>
        <form class="c-form" id="c-form"><input id="c-in" maxlength="${MAXLEN}" autocomplete="off" aria-label="Ask the bat" placeholder="${cfg.placeholder || 'Ask anything'} (max ${MAXLEN} characters)"><button class="w-btn" id="c-send" type="submit">Send</button>
          <button class="w-btn c-twice" id="c-twice" type="button" title="Ask the same question twice: the second answer should come from the cache">Ask twice (cache test)</button></form>
      </div>
      <div class="c-trace" id="c-trace" aria-label="Routing trace"><h4>ROUTING TRACE</h4><div id="c-tr"><p style="color:#cdb8d8">Ask something. Each step the router takes will appear here, live.</p></div><div class="t-sum" id="c-sum"></div></div></div>`;
    const $ = (s) => host.querySelector(s), log = $('#c-log'), input = $('#c-in');
    addMsg('bat', cfg.greeting || 'Squeak. I am the castle’s one agent. Ask me anything and watch the road your question takes: shared cache, the self-hosted GPU 30B, then the big cloud model.');
    input.focus();

    function addMsg(who, text) { const d = document.createElement('div'); d.className = 'c-msg ' + who; d.textContent = text; log.appendChild(d); log.scrollTop = log.scrollHeight; return d; }

    /* ---------- trace ---------- */
    let T = null;
    function newTrace(q) {
      const tr = $('#c-tr');
      tr.innerHTML = `<div class="t-row"><span class="t-k">Question</span><span class="t-v">${esc(q.length > 80 ? q.slice(0, 80) + '…' : q)}</span></div>
        <div class="t-row" id="t-embed"><span class="t-k">1 Embedding</span><span class="t-v">…</span></div>
        <div class="t-lanes">
          <div class="t-lane run" id="t-shared"><h5>Supabase cache</h5><div class="b">exact, then cosine…</div></div>
          <div class="t-lane run" id="t-draft"><h5>GPU 30B (self-hosted)</h5><div class="b">waiting…</div></div>
          <div class="t-lane run" id="t-mem"><h5>Memory</h5><div class="b">looking for solved examples…</div></div>
        </div>
        <div class="t-row" id="t-cos"><span class="t-k">2 Cosine</span><span class="t-v">waiting for the cache…</span></div>
        <div class="t-row" id="t-decide"><span class="t-k">3 Decision</span><span class="t-v">…</span></div>
        <div class="t-row" id="t-call"><span class="t-k">4 Call</span><span class="t-v">…</span></div>
        <div class="t-row" id="t-final"><span class="t-k">5 Final</span><span class="t-v">…</span></div>`;
      T = { q, sim: null, matched: null, guard: null, steps: [], el: (id) => tr.querySelector('#' + id) };
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
      T.steps.push(stepLine(name, d));
      if (name === 'embed') setRow('t-embed', `done <b>${ms(pick(d, 'ms', 'latency_ms'))}</b>${pick(d, 'dim') ? ' · ' + d.dim + '-dim vector' : ''}`);
      else if (name === 'cache_shared') {  // the only answer cache (Supabase); the Mac keeps none
        T.shared = true;
        const id = 't-shared', hit = !!pick(d, 'hit'), m = pick(d, 'ms', 'latency_ms');
        const sim = pick(d, 'score', 'sim', 'similarity'), st = pick(d, 'status'), err = st === 'timeout' || st === 'down' ? st : pick(d, 'error'), kind = pick(d, 'kind', 'source');
        if (pick(d, 'threshold') != null) T.th = d.threshold;
        if (st === 'skipped') { lane(id, 'miss', 'skipped'); return; }
        if (sim != null && (T.sim == null || sim > T.sim)) { T.sim = sim; const mp = pick(d, 'matched', 'matched_prompt'); if (mp) T.matched = mp; }
        const gd = pick(d, 'guard'); if (gd) T.guard = gd;
        if (hit) T.hit = { kind: kind || 'semantic', where: 'shared' };
        lane(id, err ? 'err' : hit ? 'hit' : 'miss', err ? `<b>${esc(err)}</b><br>${err === 'down' ? 'Supabase unreachable' : 'over the time budget'}<br>${ms(m)}` : `<b>${hit ? 'HIT' : 'MISS'}</b>${kind ? ' · ' + esc(kind) : ''} · ${ms(m)}${sim != null ? '<br>cos ' + (+sim).toFixed(3) + ' / ' + (pick(d, 'threshold') ?? THRESH) : ''}<br>guard: ${esc(gd || 'no candidate')}`);
        if (sim == null && !err) setRow('t-cos', 'no stored question to compare yet (no score)');
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
      T.finalized = true; T.final = d;
      if (!demoMode) remember(T, d);   // the side panels list this browser's real questions, not replays
      if (cfg.onFinal) cfg.onFinal();
      const tier = pick(d, 'tier', 'tier_used') || '?', tin = pick(d, 'tokens_in', 'input_tokens'), tout = pick(d, 'tokens_out', 'output_tokens'), cached = pick(d, 'cached_tokens'),
        cost = pick(d, 'dollars', 'usd'), total = pick(d, 'ms', 'total_ms'), kept = pick(d, 'tokens_kept_off_big', 'tokens_saved'), cacheHit = !!pick(d, 'cache') || /cache/.test(tier), avoided = cacheHit || pick(d, 'gpu_call_avoided');
      const self = !CLOUD.test(tier); if (self && !cacheHit) selfTitle(tier);
      if (!T.drafted && !T.called) lane('t-draft', cacheHit ? 'miss' : self ? 'hit' : 'miss', cacheHit ? 'not needed<br>cache answered' : self ? `<b>${esc(tier)}</b> answered<br>${tout ?? '?'} tok · ${ms(total)}` : 'climbed<br>' + esc(tier) + ' answered');
      if (!T.mem) lane('t-mem', 'miss', cacheHit ? 'not needed<br>cache answered' : 'no memory events<br>(module not connected)');
      if (!T.shared) lane('t-shared', 'miss', 'not configured<br>no cache lookup');
      if (!T.decided) setRow('t-decide', cacheHit ? `<b>serve from cache</b> · cosine ≥ ${T.th || THRESH}` : `<b>${esc(tier)}</b> answered`);
      if (!T.called) setRow('t-call', cacheHit ? '<span class="t-chip good">no model called</span>' : `<b>${esc(tier)}</b> ${esc(pick(d, 'model') || '')}`);
      setRow('t-final', `<span class="t-chip ${cacheHit ? 'good' : ''}">${esc(tier)}${d.cache ? ' (' + esc(d.cache) + ' cache)' : ''}</span><span class="t-chip">${esc(pick(d, 'model') || (cacheHit ? 'no model' : 'model unnamed'))}</span>` +
        `<span class="t-chip">in ${tin ?? '?'} / out ${tout ?? '?'} tok</span><span class="t-chip">cached ${cached ?? 0}</span><span class="t-chip">${usd(cost)}</span><span class="t-chip ${total != null && total < 200 && cacheHit ? 'good' : ''}">${ms(total)}</span>` +
        `<span class="t-chip good">${kept ?? 0} tokens kept off the big model</span>${avoided ? '<span class="t-chip good">GPU call avoided</span>' : ''}`);
      totals.turns++; if (cacheHit) totals.hits++; if (avoided || cacheHit) totals.gpuAvoided++; totals.usdSaved += pick(d, 'dollars_saved') ?? 0; totals.kept += kept || 0;
      $('#c-sum').innerHTML = `This chat: <b>${totals.turns}</b> turns · hit rate <b>${Math.round(totals.hits / totals.turns * 100)}%</b> · GPU calls avoided <b>${totals.gpuAvoided}</b> · saved <b>${usd(totals.usdSaved)}</b> · <b>${totals.kept}</b> tokens kept off the big model`;
    }

    /* ---------- demo mode: no backend (a public link). The Count replays saved real measurements and says so. ---------- */
    let demoMode = false, DEMO = null, replayed = null;
    const asked = new Set(), norm = (s) => String(s).toLowerCase().replace(/\s+/g, ' ').replace(/[?.!]+$/, '').trim();
    async function useDemo() {
      if (demoMode) return; demoMode = true;
      try { DEMO = (await window.ChimeraMode.demo()).chat; } catch (e) { DEMO = null; }
      const n = $('#c-mock'); n.hidden = false;
      n.innerHTML = DEMO ? `<b>DEMO</b> · no backend on this link, so I replay saved real measurements from <a href="https://github.com/manvendersingh21/tremor-core/blob/dev/${esc(DEMO.source)}" target="_blank" rel="noopener">${esc(DEMO.source)}</a>. Pick a saved question:` : '<b>DEMO</b> · no backend on this link, and the saved results (demo.json) could not be read.';
      n.title = DEMO ? DEMO.note : '';
      if (!DEMO) return;
      const c = $('#c-chips'); c.hidden = false;
      c.innerHTML = DEMO.examples.map((x) => `<button type="button" class="c-chip-q" data-q="${esc(x.q)}">${esc(x.q)}</button>`).join('');
      c.addEventListener('click', (e) => { const b = e.target.closest('[data-q]'); if (b && !busy) ask(b.dataset.q); });
    }
    if (window.ChimeraMode) window.ChimeraMode.detect().then((m) => { if (m === 'demo') useDemo(); });
    async function replay(q, on) {
      const ex = DEMO && DEMO.examples.find((x) => norm(x.q) === norm(q));
      if (!ex) {
        replayed = null; setRow('t-final', '<span class="t-chip warn">not a saved question</span>');
        on('answer', { text: 'In demo mode I can only replay the saved questions below. Run make web on your own machine for the live ladder.' }); on('done', {}); return;
      }
      const first = !asked.has(ex.id); asked.add(ex.id);
      for (const [n, d] of (first ? ex.first : ex.repeat)) { await wait(n === 'call' ? 450 : 90); on(n, d); }
      replayed = `DEMO replay · measured in the ${first ? 'COLD pass (first ask)' : 'WARM pass (the same question again)'} of ${DEMO.source}; answer text saved in ${DEMO.answers_from}`;
      on('answer', { text: ex.answer }); on('done', {});
    }

    /* ---------- sending ---------- */
    $('#c-form').addEventListener('submit', (e) => {
      e.preventDefault();
      const q = input.value.trim().slice(0, MAXLEN); if (!q || busy || dead) return;
      input.value = ''; ask(q);
    });
    /* the cache test: one question twice; the second answer should come from the cache */
    $('#c-twice').addEventListener('click', async () => {
      if (busy || dead) return;
      const q = input.value.trim().slice(0, MAXLEN) || (DEMO ? DEMO.examples[0].q : 'What is the capital of France?');
      input.value = '';
      const ex = DEMO && DEMO.examples.find((x) => norm(x.q) === norm(q)); if (demoMode && ex) asked.delete(ex.id);   // replay the first ask, then the repeat
      const a = await ask(q), b = await ask(q);
      compare(a, b);
    });
    function compare(a, b) {
      const d = addMsg('bat c-cmp', '');
      if (!a.final || !b.final) { d.textContent = 'The cache test needs two answers, and one did not come back.'; return; }
      const tok = (f) => (f.tokens_in || 0) + (f.tokens_out || 0), hit = (f) => !!f.cache || /cache/.test(f.tier || '');
      const row = (k, f) => `<td>${esc(f.tier || '?')}${hit(f) ? ' (cache)' : ''}</td><td>${ms(f.ms)}</td><td>${tok(f)}</td><td>${usd(f.dollars)}</td>`;
      const verdict = hit(a.final) && hit(b.final) ? 'Both answers came from the cache: this question was asked before. Type a new one to see a miss first.'
        : hit(b.final) ? `The second answer came from the cache: ${ms(Math.max(0, (a.final.ms || 0) - (b.final.ms || 0)))} faster, ${tok(a.final)} model tokens not spent again, ${b.final.tokens_kept_off_big ?? 0} tokens kept off the big model.`
          : 'The second answer did not come from the cache. An answer under the 0.95 confidence bar, or one that failed its check, is not cached.';
      d.innerHTML = `<b>Cache test</b><table class="c-cmpt"><tr><th></th><th>Answered by</th><th>Time</th><th>Model tokens</th><th>Cost</th></tr><tr><th>1st ask</th>${row('a', a.final)}</tr><tr><th>2nd ask</th>${row('b', b.final)}</tr></table><p class="${hit(b.final) ? 'c-win' : 'c-lose'}">${esc(verdict)}</p>` +
        (demoMode ? `<p class="c-demo">DEMO: a saved real measurement, replayed: ${esc(DEMO ? DEMO.source : '')}, COLD then WARM pass.</p>` : '');
      log.scrollTop = log.scrollHeight;
    }
    async function ask(q) {
      busy = true; $('#c-send').disabled = true; $('#c-twice').disabled = true;
      addMsg('me', q); newTrace(q); const t0 = performance.now(); replayed = null;
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
      if (replayed) { const s = document.createElement('span'); s.className = 'c-tag c-demo'; s.textContent = replayed; out.appendChild(s); }
      if (T.el('t-embed') && T.el('t-embed').querySelector('.t-v').textContent === '…') setRow('t-embed', demoMode ? 'not recorded in the saved run' : 'no embedding step (no cache configured)');
      busy = false; $('#c-send').disabled = false; $('#c-twice').disabled = false; if (!cfg.noFocus) input.focus();
      return { final: T.final || null, text };
    }
    async function stream(q, on) {
      if (!demoMode) {
        let r; try { r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' }, body: JSON.stringify({ prompt: q, task: taskType(q), conversation_id: conversation() }) }); } catch (e) { r = null; }
        if (r && (r.status === 429 || r.status === 503)) { const e = new Error('rate'); e.polite = r.status === 429 ? 'The bat is catching its breath. Too many questions; wait ' + (r.headers.get('Retry-After') || 'a few') + ' seconds.' : 'The castle is busy. Try again in a moment.'; throw e; }
        if (r && r.status === 403) { const e = new Error('held'); e.polite = 'That action is risky, so it waits for a person to approve it.'; throw e; }
        if (r && r.ok && r.body) { await sse(r.body, on); return; }
        if (!r || [404, 405, 501].includes(r.status)) { if (window.ChimeraMode) await useDemo(); else { const e = new Error('none'); e.polite = 'No backend answers here.'; throw e; } }
        else { const e = new Error('http'); e.polite = 'The bat cannot answer right now (' + r.status + ').'; throw e; }
      }
      await replay(q, on);
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

    const wait = (t) => new Promise((r) => setTimeout(r, t));

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
      if (demoMode) { $('#c-mon').hidden = true; return; }   // the DEMO note above the log says it once
      try { const r = await fetch(healthUrl, { cache: 'no-store' }); if (!r.ok) throw 0; renderHealth(await r.json(), false); }
      catch (e) { renderHealth({}, true); }
      timer = setTimeout(poll, 2000);
    }
    let timer = setTimeout(poll, 0);
    return function unmount() { dead = true; clearTimeout(timer); };
  }
  /* ---------- this browser's answered questions (the Dashboard and Chat side panels read them) ---------- */
  const KEY = 'chimera-traces';
  function stepLine(name, d) {
    if (name === 'cache_shared') return d.hit ? `cache HIT ${d.kind || ''} cos ${(+d.score || 1).toFixed(3)}` : `cache miss${d.score != null ? ' cos ' + (+d.score).toFixed(3) : ''}${d.status && d.status !== 'ok' ? ' (' + d.status + ')' : ''}`;
    if (name === 'call') return `${d.tier} ${d.ok === false ? 'failed' : Math.round(d.ms || 0) + ' ms'}`;
    if (name === 'draft') return `${d.tier} conf ${d.confidence != null ? (+d.confidence).toFixed(2) : '?'}/${d.gate}`;
    if (name === 'decide') return `try ${d.tier}`;
    if (name === 'memory') return d.op === 'retrieve' ? `memory ${d.chars || 0} chars` : `teacher ${d.stored ? 'stored' : 'not stored'}`;
    return name;
  }
  function taskType(q) {
    if (/```|\bdef |function\b|class |code|python|javascript|sql|regex|bug|compile|script|implement/i.test(q)) return 'code';
    if (/^(what|who|when|where|which|how many|how much|name|define|capital|list)\b/i.test(q.trim())) return 'lookup';
    return 'chat';
  }
  function remember(T, d) {
    try {
      const all = JSON.parse(localStorage.getItem(KEY) || '[]');
      all.unshift({ ts: Date.now(), q: T.q.slice(0, 120), type: taskType(T.q), tier: d.tier, model: d.model || null, cache: d.cache || (T.hit ? T.hit.where : null),
        cos: T.sim, tokens_in: d.tokens_in || 0, tokens_out: d.tokens_out || 0, ms: d.ms, dollars: d.dollars || 0, kept: d.tokens_kept_off_big || 0, steps: T.steps.slice(0, 14) });
      localStorage.setItem(KEY, JSON.stringify(all.slice(0, 60)));
    } catch (e) { /* storage full or blocked: the trace on screen is still complete */ }
  }
  /* one id per browser tab: /api/stats groups this chat's calls under it (by_conversation) */
  function conversation() {
    try { let c = sessionStorage.getItem('chimera-conv'); if (!c) { c = 'web-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8); sessionStorage.setItem('chimera-conv', c); } return c; }
    catch (e) { return 'web-anon'; }
  }
  const history = () => { try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch (e) { return []; } };
  window.CastleChat = { mount, THRESH, GATE, history, taskType, conversation };
})();
