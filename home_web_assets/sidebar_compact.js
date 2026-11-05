(() => {
 const sidebar=document.getElementById('sidebar');if(!sidebar)return;
 const button=document.createElement('button');button.className='sidebar-expand-button';button.type='button';
 button.textContent='☰';button.title='Expand navigation';button.setAttribute('aria-label','Expand navigation');
 sidebar.prepend(button);
 // Touch users can tap the button; focus expands the same rail as keyboard use.
 button.onclick=()=>button.focus();
 sidebar.addEventListener('pointerleave',()=>{
   const active=document.activeElement;
   if(sidebar.contains(active)&&!active.matches(':focus-visible')&&!sidebar.querySelector('.workspace-menu:not([hidden])'))active.blur();
 });
 sidebar.addEventListener('keydown',event=>{
   if(event.key==='Escape'&&document.documentElement.classList.contains('sidebar-auto-collapse')){
     const main=document.querySelector('.pane');
     if(main){main.tabIndex=-1;main.focus({preventScroll:true});}
   }
 });
})();
