/* Panels over the walk-in movie: a room's posters and data, and the chat with the Count.
   Data: rooms.js posters (real numbers from bench/*.md), the Halloween dashboard (/api/stats, /events, /api/evals),
   and /api/chat through world/chat.js. Nothing here invents a number. */
(function () {
  'use strict';
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const BASE = 'https://github.com/manvendersingh21/tremor-core/blob/dev/';
  const DASH = { observatory: 'live', ledger: 'evals', ladder: 'how' };  // rooms that also show the dashboard

  function posters(r) {
    if (!r || !r.posters || !r.posters.length) return '';
    return '<div class="m-posters">' + r.posters.map((p) =>
      `<article class="m-poster"><h3>${esc(p.title)}</h3>${p.big ? `<p class="big">${esc(p.big)}</p>` : ''}${p.steps ? `<ol>${p.steps.map((s) => `<li>${esc(s)}</li>`).join('')}</ol>` : ''}` +
      p.lines.map((t) => `<p>${esc(t)}</p>`).join('') + `<p class="fn"><a href="${BASE}${esc(p.src[1])}" target="_blank" rel="noopener">${esc(p.src[0])}</a></p></article>`).join('') + '</div>';
  }

  function room(pb, d, opts) {
    const r = (window.ROOMS || []).find((x) => x.id === d.id);
    const view = DASH[d.id];
    pb.innerHTML = `<p class="m-lead">${esc(r ? r.say.join(' ') : '')}</p>` +
      (view ? `<iframe class="m-dash" title="${esc(d.title)}: live dashboard" src="${opts.site || ''}dashboard/halloween.html?view=${view}&embed=1"></iframe>` : '') + posters(r);
  }

  function chat(pb) {
    pb.classList.add('m-chat');
    pb.innerHTML = '<div class="m-chatbox"></div>';
    return window.CastleChat.mount(pb.firstChild, {
      endpoint: '/api/chat', health: '/api/health', placeholder: 'Ask the Count',
      greeting: 'Good evening. Ask me anything. Your question goes through the real ladder: the Supabase cache, then our own Akash 30B, then the Crusoe 763B. You will see each step it takes.',
    });
  }

  window.MoviePanels = { room, chat };
})();
