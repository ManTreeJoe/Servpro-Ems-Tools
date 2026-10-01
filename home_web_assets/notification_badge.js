/* Account-wide Trello unread count, independent of the paginated feed. */
(() => {
  let count=null, busy=false, again=false, ready=false;
  function paint() {
    document.querySelectorAll('.sb-item[data-key="notifications"]').forEach(item=>{
      let badge=item.querySelector('.notification-badge');
      if(!badge){badge=document.createElement('span');badge.className='notification-badge';item.append(badge);}
      const label=count===null?'Trello unread count unavailable':`${count} unread Trello notifications`;
      const text=count===null?'—':count>99?'99+':String(count);
      if(badge.textContent!==text)badge.textContent=text;
      badge.title=label;badge.setAttribute('aria-label',label);
      item.setAttribute('aria-label',`Open Notifications · ${label}`);
    });
  }
  async function refresh() {
    if(!ready || document.visibilityState === 'hidden')return;
    if(busy){again=true;return;}busy=true;
    try{const result=await window.pywebview.api.notifications_unread_count();
      count=result?.ok&&Number.isSafeInteger(result.count)&&result.count>=0?result.count:null;
    }catch{count=null;}finally{busy=false;paint();if(again){again=false;void refresh();}}
  }
  new MutationObserver(paint).observe(document.getElementById('sb-nav'),{childList:true,subtree:true});
  window.addEventListener('pywebviewready',()=>{ready=true;void refresh();},{once:true});
  window.addEventListener('focus',()=>void refresh());
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')void refresh();});
  window.setInterval(()=>void refresh(),30000);
  document.addEventListener('click',event=>{if(event.target.closest('.sb-item[data-key="notifications"],#refresh-btn'))void refresh();});
  window.addEventListener('message',event=>{
    if(event.data?.type!=='oneloss-notifications-changed')return;
    const trusted=[...document.querySelectorAll('iframe')].some(frame=>frame.contentWindow===event.source&&new URL(frame.src,location.href).pathname.includes('/notifications_web_assets/'));
    if(trusted)void refresh();
  });
  paint();
})();
