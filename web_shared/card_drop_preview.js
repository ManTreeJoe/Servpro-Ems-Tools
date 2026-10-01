/* Local gesture feedback only. Remote renders never invoke this helper. */
(function () {
  let gap = null, container = null, before = null;
  const motions = new Map();
  const grabs = new WeakMap();
  function grab(el,event){if(!el)return;const r=el.getBoundingClientRect();grabs.set(el,{x:event.clientX-r.left,y:event.clientY-r.top});}
  function origin(el,event){if(!el||!Number.isFinite(event.clientX)||!Number.isFinite(event.clientY))return null;const r=el.getBoundingClientRect(),g=grabs.get(el)||{x:r.width/2,y:r.height/2};return {left:event.clientX-g.x,top:event.clientY-g.y,width:r.width,height:r.height};}
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
  function land(el,from) {
    if (el && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
      if(!from)return;
      const to=el.getBoundingClientRect();
      if(!to.width||!to.height)return;
      // A fixed clone can travel across lane overflow boundaries. It carries
      // no interactions, and its lifetime is independent of dragend cleanup.
      const flyer=el.cloneNode(true);flyer.removeAttribute('id');flyer.querySelectorAll('[id]').forEach(n=>n.removeAttribute('id'));
      for(const node of [flyer,...flyer.querySelectorAll('*')])for(const attr of [...node.attributes])if(attr.name.startsWith('data-'))node.removeAttribute(attr.name);
      flyer.classList.add('card-drop-flyer');
      flyer.setAttribute('aria-hidden','true');flyer.inert=true;
      flyer.classList.remove('dragging','drag-ready');
      Object.assign(flyer.style,{position:'fixed',left:to.left+'px',top:to.top+'px',width:to.width+'px',height:to.height+'px',margin:'0',pointerEvents:'none',zIndex:'10000',transformOrigin:'top left',boxSizing:'border-box'});
      document.body.append(flyer);
      // A fast save can replace the destination element before settling ends.
      const guard=document.createElement('style');
      const selector=el.dataset.cardId?`.kcard[data-card-id="${CSS.escape(el.dataset.cardId)}"]`:el.dataset.section&&el.dataset.index!=null?`.item[data-section="${CSS.escape(el.dataset.section)}"][data-index="${CSS.escape(el.dataset.index)}"]`:'';
      if(selector){guard.textContent=selector+'{visibility:hidden!important}';document.head.append(guard);}
      const old=el.style.visibility;el.style.visibility='hidden';
      const animation=flyer.animate([{transform:`translate(${from.left-to.left}px,${from.top-to.top}px) scale(${from.width/to.width},${from.height/to.height})`},{transform:'translate(0,0) scale(1)'}],{duration:240,easing:'cubic-bezier(.22,.75,.25,1)'});
      const cleanup=()=>{flyer.remove();guard.remove();el.style.visibility=old;};animation.finished.then(cleanup,cleanup);
    }
  }
  window.CardDropPreview = {show, clear, selection, land, grab, origin};
  document.addEventListener('dragend', clear);
})();
