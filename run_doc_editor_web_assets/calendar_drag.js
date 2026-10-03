/* Pointer feedback only. The calendar host owns the actual scheduling change. */
(function(global){
  'use strict';
  global.bindCalendarDrag=function(host,onDrop){
    let active=null,ignoreClickUntil=0;
    function clear(){
      if(!active)return;
      active.ghost?.remove();active.slot?.remove();
      active.card.classList.remove('is-dragging');
      host.querySelectorAll('.is-drop-target').forEach(el=>el.classList.remove('is-drop-target'));
      active=null;
    }
    function down(event){
      const card=event.target.closest('[data-edit][draggable="true"]');
      if(event.button!==0 || !card || card.disabled || active)return;
      const rect=card.getBoundingClientRect();
      active={card,id:event.pointerId,x:event.clientX,y:event.clientY,offsetX:event.clientX-rect.left,offsetY:event.clientY-rect.top};
    }
    function move(event){
      const a=active;if(!a || a.id!==event.pointerId || a.landing)return;
      if(!a.ghost){
        if(Math.hypot(event.clientX-a.x,event.clientY-a.y)<6)return;
        const rect=a.card.getBoundingClientRect();
        a.ghost=a.card.cloneNode(true);a.ghost.removeAttribute('data-edit');a.ghost.removeAttribute('draggable');
        a.ghost.classList.add('wc-pointer-ghost');a.ghost.setAttribute('aria-hidden','true');a.ghost.tabIndex=-1;
        a.ghost.style.width=`${rect.width}px`;host.append(a.ghost);
        a.slot=document.createElement(a.card.closest('.run-paper')?'li':'div');a.slot.className='wc-drop-slot';a.slot.style.height=`${rect.height}px`;
        a.slot.textContent='Drop here';a.card.classList.add('is-dragging');
      }
      event.preventDefault();
      a.ghost.style.left=`${event.clientX-a.offsetX}px`;a.ghost.style.top=`${event.clientY-a.offsetY}px`;
      const hit=document.elementFromPoint(event.clientX,event.clientY),target=hit?.closest('[data-drop-date]');
      host.querySelectorAll('.is-drop-target').forEach(el=>el.classList.remove('is-drop-target'));
      a.target=target && host.contains(target)?target:null;
      if(!a.target){a.slot.remove();return;}
      target.classList.add('is-drop-target');
      const list=target.querySelector('[data-drop-list], .wc-day-items')||target;
      const cards=[...list.querySelectorAll('[data-edit][draggable="true"]')].filter(card=>card!==a.card);
      const before=cards.find(card=>event.clientY<card.getBoundingClientRect().top+card.offsetHeight/2);
      list.insertBefore(a.slot,before?.closest('li')||before||null);
      a.beforeId=before?.dataset.edit||null;
      if(a.card.closest('.run-paper')){
        if(event.clientY<70)window.scrollBy(0,-24);
        else if(event.clientY>innerHeight-70)window.scrollBy(0,24);
      }
      const bounds=list.getBoundingClientRect();
      if(event.clientY<bounds.top+45)list.scrollTop-=18;
      else if(event.clientY>bounds.bottom-45)list.scrollTop+=18;
    }
    async function up(event){
      const a=active;if(!a || event.pointerId!==a.id || a.landing)return;
      if(!a.ghost){clear();return;}
      ignoreClickUntil=Date.now()+500;
      const valid=event.type==='pointerup' && a.target && a.slot.isConnected;
      const destination=(valid?a.slot:a.card).getBoundingClientRect(),origin=a.ghost.getBoundingClientRect();
      a.landing=true;
      const duration=matchMedia('(prefers-reduced-motion: reduce)').matches?0:180;
      await a.ghost.animate([{transform:'translate(0,0)'},{transform:`translate(${destination.left-origin.left}px,${destination.top-origin.top}px)`}],{duration,easing:'cubic-bezier(.2,.8,.2,1)',fill:'forwards'}).finished.catch(()=>{});
      if(active!==a)return;
      const id=a.card.dataset.edit,day=a.target?.dataset.dropDate;
      const placement={queue:a.target?.dataset.dropQueue,group:a.target?.dataset.dropGroup,beforeId:a.beforeId};
      clear();if(valid)onDrop(id,day,placement);
    }
    function native(event){if(active)event.preventDefault();}
    function click(event){if(Date.now()<ignoreClickUntil && event.target.closest('[data-edit]')){event.preventDefault();event.stopImmediatePropagation();ignoreClickUntil=0;}}
    function key(event){if(event.key==='Escape'){ignoreClickUntil=Date.now()+500;clear();}}
    host.addEventListener('pointerdown',down);host.addEventListener('dragstart',native,true);host.addEventListener('click',click,true);
    document.addEventListener('pointermove',move,{passive:false});document.addEventListener('pointerup',up);document.addEventListener('pointercancel',up);document.addEventListener('keydown',key);
    return {clear,destroy(){clear();host.removeEventListener('pointerdown',down);host.removeEventListener('dragstart',native,true);host.removeEventListener('click',click,true);document.removeEventListener('pointermove',move);document.removeEventListener('pointerup',up);document.removeEventListener('pointercancel',up);document.removeEventListener('keydown',key);}};
  };
})(globalThis);
