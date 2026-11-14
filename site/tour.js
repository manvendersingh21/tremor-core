/* Castle tour. Rooms and posters come from rooms.js (window.ROOMS). Hash routes: #entrance, #hall, #room/<id>. */
(() => {
  const ROOMS = window.ROOMS || [];
  const BASE = 'https://github.com/manvendersingh21/tremor-core/blob/dev/';
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const body = document.body, drac = $('dracula'), bt = $('bubble-text'), live = $('bubble-live');
  const btnPrev = $('btn-prev'), btnNext = $('btn-next'), btnSkip = $('btn-skip');
  const gate = $('gate'), grid = $('room-posters'), stage = $('stage');
  const ENTRANCE = ['Good evening. Not every word deserves the castle.', 'Press Enter, or click the gate, and I will open it.'];
  const HALL = ['Welcome to the Great Hall. Choose a door. Each room tells one part of the story.'];

  /* ---- Dracula speech ---- */
  let typer = null, full = '';
  function say(text) {
    clearInterval(typer); typer = null; full = text; live.textContent = text;
    if (reduce) { bt.textContent = text; return; }
    let i = 0; bt.textContent = ''; drac.classList.add('speaking');
    typer = setInterval(() => {
      bt.textContent = text.slice(0, ++i);
      if (i >= text.length) { clearInterval(typer); typer = null; drac.classList.remove('speaking'); }
    }, 22);
  }
  function finishTyping() {
    if (!typer) return false;
    clearInterval(typer); typer = null; bt.textContent = full; drac.classList.remove('speaking'); return true;
  }

  /* ---- script: the lines Dracula says in the current view ---- */
  let sc = null;
  function setScript(s) { sc = Object.assign({ i: 0 }, s); show(); }
  function show() {
    say(sc.lines[sc.i]);
    if (sc.onStep) sc.onStep(sc.i);
    const last = sc.i === sc.lines.length - 1;
    btnPrev.disabled = sc.i === 0;
    btnNext.textContent = last ? (sc.endLabel || 'Next') : 'Next';
    btnNext.disabled = last && !sc.onEnd;
    btnSkip.disabled = !sc.onSkip;
  }
  function next() {
    if (!sc) return;
    if (finishTyping()) return;
    if (sc.i < sc.lines.length - 1) { sc.i++; show(); } else if (sc.onEnd) sc.onEnd();
  }
  function prev() { if (sc && sc.i > 0) { sc.i--; show(); } }
  btnNext.addEventListener('click', next);
  btnPrev.addEventListener('click', prev);
  btnSkip.addEventListener('click', () => sc && sc.onSkip && sc.onSkip());

  /* ---- entrance ---- */
  let opening = false;
  function openGate() {
    if (opening) return;
    opening = true; gate.classList.add('open'); say('Come in. The hall is lit.');
    setTimeout(() => { opening = false; location.hash = '#hall'; }, reduce ? 0 : 1300);
  }
  gate.addEventListener('click', openGate);
  $('enter').addEventListener('click', (e) => { e.preventDefault(); openGate(); });

  /* ---- hall ---- */
  $('doors').innerHTML = ROOMS.map((r) =>
    `<a class="door" href="#room/${esc(r.id)}"><span class="plaque"><strong>${esc(r.title)}</strong><span>${esc(r.door)}</span></span></a>`).join('');
  $('doors').addEventListener('click', (e) => {
    const a = e.target.closest('a.door');
    if (!a || reduce || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    e.preventDefault(); a.classList.add('opening');
    setTimeout(() => { a.classList.remove('opening'); location.hash = a.getAttribute('href'); }, 550);
  });

  /* ---- rooms and posters ---- */
  function posterEl(p) {
    const el = document.createElement('article');
    el.className = 'poster';
    const steps = p.steps ? `<ol class="steps">${p.steps.map((s) => `<li>${esc(s)}</li>`).join('')}</ol>` : '';
    el.innerHTML = `<h3>${esc(p.title)}</h3>${p.big ? `<p class="big">${esc(p.big)}</p>` : ''}${steps}` +
      p.lines.map((t) => `<p>${esc(t)}</p>`).join('') +
      `<p class="fn"><a href="${BASE}${esc(p.src[1])}">${esc(p.src[0])}</a></p>`;
    return el;
  }
  function hang(p, delay) {
    const el = posterEl(p); grid.appendChild(el);
    if (reduce) { el.classList.add('hung'); return; }
    const carry = document.createElement('div'); carry.className = 'carry'; carry.setAttribute('aria-hidden', 'true');
    carry.innerHTML = '<div class="cb"><svg viewBox="0 0 64 32"><use href="#bat"/></svg></div>'.repeat(Math.min(3, p.bats || 2));
    el.appendChild(carry);
    const r = el.getBoundingClientRect(), sx = -r.right - 90, sy = -r.top - 220;
    el.animate([
      { transform: `translate(${sx}px,${sy}px) rotate(-8deg)`, opacity: 0 },
      { transform: `translate(${sx * 0.55}px,${sy * 0.2 + 80}px) rotate(5deg)`, opacity: 1, offset: 0.45 },
      { transform: `translate(${sx * 0.15}px,${sy * 0.02 - 20}px) rotate(-3deg)`, opacity: 1, offset: 0.8 },
      { transform: 'none', opacity: 1 }
    ], { duration: 1600, delay, easing: 'ease-in-out', fill: 'backwards' }).onfinish = () => {
      el.classList.add('hung');
      carry.animate([{ transform: 'none', opacity: 1 }, { transform: 'translate(240px,-280px)', opacity: 0 }],
        { duration: 900, easing: 'ease-in' }).onfinish = () => carry.remove();
    };
  }
  function enterRoom(r) {
    $('room-title').textContent = r.title;
    grid.textContent = '';
    const hungN = new Set();
    const upTo = (i) => r.posters.forEach((p, k) => {
      if (p.at <= i && !hungN.has(k)) { hungN.add(k); hang(p, hungN.size > 1 ? 0 : 200); }
    });
    setScript({
      lines: r.say, endLabel: 'Leave the room', onEnd: () => { location.hash = '#hall'; },
      onStep: upTo,
      onSkip: () => { upTo(99); sc.i = sc.lines.length - 1; show(); finishTyping(); }
    });
    document.title = `${r.title} | CHIMERA`;
  }

  /* ---- routing ---- */
  let first = true;
  function route() {
    const h = location.hash.replace(/^#/, '');
    const id = h.startsWith('room/') ? h.slice(5) : h.startsWith('r-') ? h.slice(2) : null;
    const room = id && ROOMS.find((r) => r.id === id);
    if (id && !room) { location.replace('#hall'); return; }
    const view = room ? 'room' : h === 'hall' ? 'hall' : 'entrance';
    body.dataset.view = view;
    gate.classList.remove('open'); opening = false;
    if (room) enterRoom(room);
    else if (view === 'hall') { setScript({ lines: HALL }); document.title = 'The Great Hall | CHIMERA'; }
    else { setScript({ lines: ENTRANCE, endLabel: 'Open the gate', onEnd: openGate, onSkip: openGate }); document.title = 'CHIMERA: a castle where each LLM call finds the cheapest tier'; }
    if (!first) { window.scrollTo(0, 0); stage.focus({ preventScroll: true }); }
    first = false;
  }
  $('btn-hall').addEventListener('click', () => { location.hash = '#hall'; });
  addEventListener('hashchange', route);

  addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const v = body.dataset.view;
    if (e.key === 'Escape' && v === 'room') location.hash = '#hall';
    else if (e.key === 'ArrowRight' && !/INPUT|TEXTAREA/.test(e.target.tagName)) next();
    else if (e.key === 'ArrowLeft' && !/INPUT|TEXTAREA/.test(e.target.tagName)) prev();
    else if (e.key === 'Enter' && v === 'entrance' && e.target === document.body) openGate();
  });

  route();
})();
