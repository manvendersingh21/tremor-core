/* Motion controls: pause toggle (saved), pause when the tab is hidden, light mouse parallax on desktop. No animation loop. */
(() => {
  const root = document.documentElement, btn = document.getElementById('motion-toggle'), sky = document.querySelector('.sky');
  const KEY = 'chimera-motion';
  let off = false;
  try { off = localStorage.getItem(KEY) === 'off'; } catch (_) {}
  const apply = () => { root.classList.toggle('motion-off', off); btn.textContent = off ? 'Play motion' : 'Pause motion'; };
  btn.addEventListener('click', () => {
    off = !off; apply();
    try { localStorage.setItem(KEY, off ? 'off' : 'on'); } catch (_) {}
  });
  apply();
  document.addEventListener('visibilitychange', () => root.classList.toggle('tab-hidden', document.hidden));

  // shortcut: parallax is mouse only, skipped on touch, narrow screens and reduced motion; one rAF per frame at most.
  if (!matchMedia('(min-width:821px) and (hover:hover) and (pointer:fine) and (prefers-reduced-motion:no-preference)').matches) return;
  let raf = 0, x = 0, y = 0;
  addEventListener('pointermove', (e) => {
    if (off || e.pointerType !== 'mouse') return;
    x = e.clientX / innerWidth * 2 - 1; y = e.clientY / innerHeight * 2 - 1;
    if (!raf) raf = requestAnimationFrame(() => { raf = 0; sky.style.setProperty('--px', x.toFixed(3)); sky.style.setProperty('--py', y.toFixed(3)); });
  }, { passive: true });
})();
