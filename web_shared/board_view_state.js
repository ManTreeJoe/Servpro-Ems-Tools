/* Preserve presentation state, never job data or save ordering. */
(function () {
  function focusSelector(root) {
    const el=document.activeElement;
    if (!el || !root.contains(el)) return null;
    if (el.id) return '#'+CSS.escape(el.id);
    const attributes=[...el.attributes].filter(a=>a.name.startsWith('data-') && a.name!=='data-index');
    if (!attributes.length) return null;
    const card=el.closest('[data-card-id]');
    const prefix=card && card!==el ? `[data-card-id="${CSS.escape(card.dataset.cardId)}"] ` : '';
    const selector=prefix+el.tagName.toLowerCase()+attributes.map(a=>`[${a.name}="${CSS.escape(a.value)}"]`).join('');
    return root.querySelectorAll(selector).length===1 ? selector : null;
  }
  function render(root,key,scrollers,paint) {
    if (!root) return paint();
    const same=root._boardViewKey===key;
    const positions=same ? new Map(scrollers().map(([id,el])=>[id,{left:el.scrollLeft,top:el.scrollTop}])) : new Map();
    const selector=same ? focusSelector(root) : null;
    const focused=document.activeElement;
    paint();
    root._boardViewKey=key;
    if (!same) {
      for (const [,el] of scrollers()) {el.scrollLeft=0;el.scrollTop=0;}
      return;
    }
    // Synchronous restoration: no frame at the top and no smooth scrolling.
    for (const [id,el] of scrollers()) {
      const position=positions.get(id);
      if (position) {el.scrollLeft=position.left;el.scrollTop=position.top;}
    }
    if (selector && !focused.isConnected && document.activeElement===document.body) {
      const matches=root.querySelectorAll(selector);
      if(matches.length===1) matches[0].focus({preventScroll:true});
    }
  }
  window.BoardViewState={render};
})();
