/* Local gesture feedback only. Remote renders never invoke this helper. */
(function () {
  let gap = null, container = null, before = null;
  const motions = new Map();
  function settle() { motions.forEach(a => a.cancel()); motions.clear(); }
  function clear() {
    settle(); gap?.remove(); gap = container = before = null;
  }
  function show(target, selector, source, y) {
    if (!target) { clear(); return; }
    if (container === target && gap) {
      const r = gap.getBoundingClientRect();
      if (y >= r.top && y <= r.bottom) return;
    }
    settle();
    const cards = [...target.querySelectorAll(selector)].filter(el => el !== source);
    const next = cards.find(el => { const r=el.getBoundingClientRect(); return y < r.top+r.height/2; }) || null;
    if (container === target && before === next && gap) return;
    const previous = new Map(cards.map(el => [el, el.getBoundingClientRect().top]));
    gap?.remove();
    gap = document.createElement('div');
    gap.className = 'card-drop-preview';
    gap.textContent = 'Drop here';
    gap.style.height = `${Math.max(48, source?.getBoundingClientRect().height || 64)}px`;
    gap.style.cssText += ';box-sizing:border-box;flex:none;border:2px dashed var(--accent,#6ea889);border-radius:8px;background:rgba(110,168,137,.13);display:flex;align-items:center;justify-content:center;color:var(--text-muted,#9eb1a4);font-size:12px;margin:4px 0;pointer-events:none';
    target.insertBefore(gap, next || target.querySelector(':scope > .add-item-btn'));
    container=target; before=next;
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches) {
      cards.forEach(el => {
        const dy=previous.get(el)-el.getBoundingClientRect().top;
        if (dy) motions.set(el,el.animate([{transform:`translateY(${dy}px)`},{transform:'translateY(0)'}],{duration:150,easing:'ease-out'}));
      });
    }
  }
  function selection(target) { return container === target && gap ? {before} : null; }
  function land(el) {
    if (el && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
      motions.get(el)?.cancel();
      motions.set(el,el.animate([{opacity:.55,transform:'translateY(-5px)'},{opacity:1,transform:'translateY(0)'}],{duration:160,easing:'ease-out'}));
    }
  }
  window.CardDropPreview = {show, clear, selection, land};
  document.addEventListener('dragend', clear);
})();
