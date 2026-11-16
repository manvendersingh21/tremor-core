/* Panels over the walk-in movie: a room's posters and data, and the chat with the Count.
   Data: rooms.js posters (real numbers from bench/*.md), the Halloween dashboard (/api/stats, /events, /api/evals),
   the saved results in demo.json (site/build.py: bench/*.md, bench/*.csv, .kiro/, tests/) and /api/chat through
   world/chat.js. Nothing here invents a number: each block names the file it was read from. */
(function () {
  'use strict';
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const BASE = 'https://github.com/manvendersingh21/tremor-core/blob/dev/';
  const DASH = { observatory: 'live', ledger: 'evals', ladder: 'how' };  // rooms that also show the dashboard
  const src = (f) => `<p class="fn"><a href="${BASE}${esc(f)}" target="_blank" rel="noopener">${esc(f)}</a></p>`;
  const usd0 = (v) => '$' + Math.round(v).toLocaleString('en-US');

  function posters(list) {
    if (!list || !list.length) return '';
    return '<div class="m-posters">' + list.map((p) =>
      `<article class="m-poster"><h3>${esc(p.title)}</h3>${p.big ? `<p class="big">${esc(p.big)}</p>` : ''}${p.steps ? `<ol>${p.steps.map((s) => `<li>${esc(s)}</li>`).join('')}</ol>` : ''}` +
      p.lines.map((t) => `<p>${esc(t)}</p>`).join('') + `<p class="fn"><a href="${BASE}${esc(p.src[1])}" target="_blank" rel="noopener">${esc(p.src[0])}</a></p></article>`).join('') + '</div>';
  }

  /* ---------- saved-result blocks, one per room that has one (both LIVE and DEMO: these are measured runs) ---------- */
  function workshop(D) {
    const k = D.kiro;
    return `<div class="m-keys"><div><b>${k.properties}</b><span>property tests (Hypothesis)</span></div><div><b>${k.bugs_found}</b><span>real bugs found</span></div>` +
      `<div><b class="m-win">${k.bugs_fixed}</b><span>fixed, ${k.xfail_left} xfail left</span></div><div><b>${k.property_files}</b><span>property test files in tests/</span></div></div>` + posters(k.posters);
  }
  const h200s = (s) => { const m = /^(\d+) \((\d+%)\)$/.exec(s); return m ? `${m[1]} H200${m[1] === '1' ? '' : 's'}, ${m[2]} busy` : s + ' H200s busy'; };
  function cost(D, h) {
    const c = D.cost, rows = c.scale[h || 'no_repeats'];
    const bar = (v, max, cls, label) => `<div class="m-bar-row"><span class="m-bl">${label}</span><span class="m-bt"><i class="${cls}" style="width:${Math.max(0.6, v / max * 100).toFixed(2)}%"></i></span><b>${usd0(v)}</b></div>`;
    const sv = (s) => {   // "-$2,889 (-611%)" -> "$2,889 a month more (+611%)", in red: a loss stays visible
      const m = /^-(\$[\d,]+) \(-([\d.]+%)\)$/.exec(s);
      return m ? `<b class="m-lose">${esc(m[1])} a month more (+${esc(m[2])})</b>` : `<b class="m-win">${esc(s.replace(/ \(/, ' a month saved ('))}</b>`;
    };
    return `<section class="m-cost" aria-label="Monthly cost chart"><div class="m-cost-h"><h3>The bill: a month of coding calls</h3>` +
      `<span class="m-seg" role="group" aria-label="Share of repeats"><button type="button" data-h="no_repeats" aria-pressed="${h !== 'repeats_30'}">no repeats</button><button type="button" data-h="repeats_30" aria-pressed="${h === 'repeats_30'}">30% repeats</button></span></div>` +
      rows.map((r) => {
        const max = Math.max(r.gpt55_only, r.cascade_gpt55, r.top763_only, r.cascade_763);
        return `<div class="m-cost-g"><h4>${r.calls_a_day.toLocaleString('en-US')} calls a day <small>${esc(h200s(r.h200s))}</small></h4>` +
          bar(r.gpt55_only, max, 'gpt', 'GPT-5.5 only') + bar(r.cascade_gpt55, max, 'lad', 'Ladder, GPT-5.5 for failures') +
          `<p class="m-sv">vs GPT-5.5: ${sv(r.saved_gpt55)}</p>` +
          bar(r.top763_only, max, 'top', '763B only') + bar(r.cascade_763, max, 'lad', 'Ladder, 763B for failures') +
          `<p class="m-sv">vs 763B: ${sv(r.saved_763)}</p></div>`;
      }).join('') +
      `<table class="m-t"><tr><th>Tier</th><th>$ per 1,000 calls</th><th>Pass</th></tr>${c.per_1k.map((r) => `<tr><td>${esc(r.tier)}</td><td>${esc(r.usd_per_1k)}</td><td>${esc(r.pass)}</td></tr>`).join('')}</table>` +
      `<p class="m-note">An idle H200 still bills ${esc(c.idle_h200_day)} a day. The 30B failed ${esc(c.pass_30b)} coding tasks; the ladder re-asks the big model for those.</p>${src(c.file)}</section>`;
  }
  function crypt(D) {
    const b = D.bank;
    return `<div class="m-keys">${D.cache.slice(0, 3).map((r) => `<div><b>${esc(r[1].split(' (')[0])}</b><span>${esc(r[0])}</span></div>`).join('')}</div>` +
      `<table class="m-t"><tr><th>Cache</th><th>Measured</th><th>File</th></tr>${D.cache.map((r) => `<tr><td>${esc(r[0])}</td><td>${esc(r[1])}</td><td><a href="${BASE}${esc(r[2])}" target="_blank" rel="noopener">${esc(r[2])}</a></td></tr>`).join('')}</table>` +
      `<h3 class="m-h3">The solved-problem bank (${esc(b.size)})</h3><table class="m-t"><tr><th>Run</th><th>Served</th><th>Hint only</th><th>Miss</th><th>Wrong served</th><th>30B calls</th><th>Big calls</th><th>Big $</th></tr>` +
      b.runs.map((r) => `<tr><td>${esc(r.name)}</td><td>${r.served} of ${r.problems}</td><td>${r.hint_only}</td><td>${r.miss}</td><td class="m-win">${r.wrong_caught}</td><td>${r.calls_30b}</td><td>${r.calls_big}</td><td>$${r.big_usd.toFixed(4)}</td></tr>`).join('') + '</table>' + src(b.file);
  }
  function tower(D) {
    const s = D.spec, x = (v) => parseFloat(v);
    const pick = (re) => s.rows.find((r) => re.test(r.run)), big = pick(/alone$/), e = pick(/EAGLE/), k4 = pick(/^Cross-box, 30B drafter, K=4$/);
    const keys = [[big, 'tok/s, the 235B alone', big && big.tok_s, ''], [e, 'same box, EAGLE-3 head', e && e.vs, 'm-win'], [k4, 'a 30B drafter on a second box, K=4', k4 && k4.vs, 'm-lose']].filter((x) => x[0]);
    return `<div class="m-keys">${keys.map(([, l, v, c]) => `<div><b class="${c}">${esc(v)}</b><span>${esc(l)}</span></div>`).join('')}</div><h3 class="m-h3">${esc(s.title)}</h3><table class="m-t"><tr><th>Run</th><th>Who drafts, who checks</th><th>tok/s</th><th>vs 235B alone</th><th>Same output</th></tr>` +
      s.rows.map((r) => `<tr><td>${esc(r.run)}</td><td>${esc(r.how)}</td><td>${esc(r.tok_s)}</td><td class="${x(r.vs) > 1.001 ? 'm-win' : x(r.vs) < 0.999 ? 'm-lose' : ''}">${esc(r.vs)}</td><td>${esc(r.same)}</td></tr>`).join('') +
      '</table>' + note(s.rows) + src(s.file);
  }
  function note(rows) {   // read off the rows above, not typed
    const e = rows.find((r) => /EAGLE/.test(r.run)), cross = rows.filter((r) => /^Cross-box/.test(r.run)), m = e && /^(\d+)\/(\d+)$/.exec(e.same);
    const out = [];
    if (e && m) out.push(`Same-box EAGLE-3 ran ${esc(e.vs)} as fast, but its output differed from the 235B alone on ${m[2] - m[1]} of ${m[2]} prompts.`);
    if (cross.length) out.push(`A drafter on a second box was slower than the 235B alone in ${cross.filter((r) => parseFloat(r.vs) < 1).length} of ${cross.length} runs.`);
    return out.length ? `<p class="m-note">${out.join(' ')}</p>` : '';
  }
  function gpus(D) {   // the cost case: what the 30B costs per 1,000 calls on each box (bench/results_company_cost.md)
    const c = D.cost, rows = c.per_1k.filter((r) => /^30B on/.test(r.tier));
    const pick = (re, cls) => { const r = rows.find((x) => re.test(x.tier)); return r ? `<div><b class="${cls}">${esc(r.usd_per_1k)}</b><span>${esc(r.tier)} · pass ${esc(r.pass)}</span></div>` : ''; };
    return `<div class="m-keys">${pick(/busy 100% of the day/, 'm-win')}${pick(/busy 10%/, '')}${pick(/tuned V100.*busy 100%/, 'm-win')}${pick(/one request at a time$/, 'm-lose')}${pick(/before tuning/, 'm-lose')}</div>` +
      `<p class="m-note">Per 1,000 coding calls. An idle H200 still bills ${esc(c.idle_h200_day)} a day, so the price per call depends on how busy it is.</p>${src(c.file)}`;
  }
  const DATA = { workshop, ledger: (D) => cost(D), crypt, tower, gpus };

  function room(pb, d, opts) {
    const r = (window.ROOMS || []).find((x) => x.id === d.id);
    const view = DASH[d.id], demo = /[?&]demo=1\b/.test(location.search) ? '&demo=1' : '';
    pb.innerHTML = `<p class="m-lead">${esc(r ? r.say.join(' ') : '')}</p>` + (DATA[d.id] ? '<div class="m-data"><p class="m-loading">Reading the saved results…</p></div>' : '') +
      (view ? `<iframe class="m-dash" title="${esc(d.title)}: dashboard" src="${opts.site || ''}dashboard/halloween.html?view=${view}&embed=1${demo}"></iframe>` : '') + posters(r && r.posters);
    if (!DATA[d.id] || !window.ChimeraMode) return;
    const el = pb.querySelector('.m-data');
    window.ChimeraMode.demo().then((D) => {
      el.innerHTML = DATA[d.id](D);
      el.addEventListener('click', (e) => { const b = e.target.closest('[data-h]'); if (b) el.innerHTML = cost(D, b.dataset.h); });
    }).catch(() => { el.innerHTML = '<p class="m-err">The saved results (demo.json) could not be read. The posters below still hold every number.</p>'; });
  }

  function chat(pb) {
    pb.classList.add('m-chat');
    pb.innerHTML = '<div class="m-chatbox"></div>';
    return window.CastleChat.mount(pb.firstChild, {
      endpoint: '/api/chat', health: '/api/health', placeholder: 'Ask the Count',
      greeting: 'Good evening. Ask me anything. Your question goes through the real ladder: the Supabase cache, then our own 30B, then the Crusoe 763B. You will see each step it takes. Press "Ask twice" to watch the cache answer the second time.',
    });
  }

  window.MoviePanels = { room, chat };
})();
