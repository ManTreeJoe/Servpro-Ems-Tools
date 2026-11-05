/* Keep menus in their comment DOM for delegated actions, but out of layout. */
(() => {
  const selector = '.comment-actions-menu';
  function close(menu, restoreFocus=false) {
    menu.open = false;
    const panel = menu.querySelector(':scope > div');
    if (panel?.matches(':popover-open')) panel.hidePopover();
    menu.querySelector('summary')?.setAttribute('aria-expanded','false');
    if (restoreFocus) menu.querySelector('summary')?.focus();
  }
  function place(menu) {
    const trigger = menu.querySelector('summary'), panel = menu.querySelector(':scope > div');
    if (!trigger || !panel) return;
    trigger.setAttribute('aria-expanded',String(menu.open));
    if (!menu.open) { if (panel.matches(':popover-open')) panel.hidePopover(); return; }
    document.querySelectorAll(selector+'[open]').forEach(other => {if(other!==menu)close(other);});
    // The top layer escapes the scroll panel's clipping without reparenting.
    if (panel.showPopover) {panel.setAttribute('popover','manual');if(!panel.matches(':popover-open'))panel.showPopover();}
    const anchor=trigger.getBoundingClientRect(), gap=4, edge=8;
    panel.style.maxHeight=Math.max(40,innerHeight-edge*2)+'px';panel.style.overflowY='auto';
    const box=panel.getBoundingClientRect();
    panel.style.left=Math.max(edge,Math.min(anchor.right-box.width,innerWidth-box.width-edge))+'px';
    const top=anchor.bottom+gap+box.height<=innerHeight-edge ? anchor.bottom+gap : anchor.top-box.height-gap;
    panel.style.top=Math.max(edge,top)+'px';
  }
  document.addEventListener('toggle',event=>{if(event.target.matches?.(selector))place(event.target);},true);
  document.addEventListener('click',event=>{
    document.querySelectorAll(selector+'[open]').forEach(menu=>{
      if(!menu.contains(event.target)||event.target.closest('button'))close(menu);
    });
  });
  document.addEventListener('keydown',event=>{
    if(event.key!=='Escape')return;
    const menu=document.querySelector(selector+'[open]');
    if(menu){event.preventDefault();event.stopImmediatePropagation();close(menu,true);}
  },true);
  document.addEventListener('scroll',event=>{
    document.querySelectorAll(selector+'[open]').forEach(menu=>{
      if(!menu.querySelector(':scope > div')?.contains(event.target))close(menu);
    });
  },true);
  window.addEventListener('resize',()=>document.querySelectorAll(selector+'[open]').forEach(menu=>close(menu)));
})();
