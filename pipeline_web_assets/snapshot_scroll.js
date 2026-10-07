/* The height-fitted Snapshot card has no document scroller of its own. */
(() => {
  if (new URLSearchParams(location.search).get('snapshot_card') !== '1') return;
  document.addEventListener('wheel', event => {
    if (event.defaultPrevented || event.ctrlKey || event.metaKey) return;
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    // Editors and dialogs retain their own scrolling, including at their edges.
    if (target.closest('textarea,select,[contenteditable="true"]')) return;
    const dialog = target.closest('[role="dialog"],dialog,.modal-scrim');
    if (dialog && !dialog.matches('.audit-card,.audit-overlay')) return;
    for (let node = target; node && node !== document.body; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (/(auto|scroll)/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 1 &&
          ((event.deltaY < 0 && node.scrollTop > 0) || (event.deltaY > 0 && node.scrollTop + node.clientHeight < node.scrollHeight - 1))) return;
      if (/(auto|scroll)/.test(style.overflowX) && node.scrollWidth > node.clientWidth + 1 &&
          ((event.deltaX < 0 && node.scrollLeft > 0) || (event.deltaX > 0 && node.scrollLeft + node.clientWidth < node.scrollWidth - 1))) return;
    }
    event.preventDefault();
    window.parent.postMessage({type:'snapshot-card-scroll',x:event.deltaX,y:event.deltaY,mode:event.deltaMode},location.origin);
  }, {passive:false});
})();
