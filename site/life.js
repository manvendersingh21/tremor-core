/* Motion: light mouse parallax on desktop. No animation loop. */
(() => {
  const sky = document.querySelector('.sky');
  try { localStorage.removeItem('chimera-motion'); } catch (_) {} // clear old saved pause

  // shortcut: parallax is mouse only, skipped on touch and narrow screens; one rAF per frame at most.
  if (!matchMedia('(min-width:821px) and (hover:hover) and (pointer:fine)').matches) return;
  let raf = 0, x = 0, y = 0;
  addEventListener('pointermove', (e) => {
    if (e.pointerType !== 'mouse') return;
    x = e.clientX / innerWidth * 2 - 1; y = e.clientY / innerHeight * 2 - 1;
    if (!raf) raf = requestAnimationFrame(() => { raf = 0; sky.style.setProperty('--px', x.toFixed(3)); sky.style.setProperty('--py', y.toFixed(3)); });
  }, { passive: true });
})();
