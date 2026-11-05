/* Combined unread count, independent of the paginated feed. */
(() => {
  let count=null, busy=false, again=false, ready=false, live=null, liveTimer=null;
  function paint() {
    document.querySelectorAll('.sb-item[data-key="notifications"]').forEach(item=>{
      let badge=item.querySelector('.notification-badge');
      if(!badge){badge=document.createElement('span');badge.className='notification-badge';item.append(badge);}
      const label=count===null?'Unread count unavailable':`${count} unread notifications`;
      const text=count===null?'—':String(count);
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
  window.addEventListener('pywebviewready',()=>{
    ready=true;void refresh();
    if(window.OneLossScheduleRealtime && window.pywebview.api.notifications_realtime_credentials){
      live=window.OneLossScheduleRealtime({channel:'notification-board-hints',
        changes:[{event:'*',schema:'public',table:'hub_jobs_live_changes'}],
        credentials:async()=>{const result=await window.pywebview.api.notifications_realtime_credentials();if(!result?.ok)throw Error('Unavailable');return result;},
        status:()=>{},changed:()=>{
          clearTimeout(liveTimer);liveTimer=setTimeout(()=>{
            void refresh();
            document.querySelectorAll('iframe').forEach(frame=>{
              if(new URL(frame.src,location.href).pathname.includes('/notifications_web_assets/'))
                frame.contentWindow?.postMessage({type:'oneloss-notification-board-changed'},'*');
            });
          },500);
        }});
    }
  },{once:true});
  window.addEventListener('pagehide',()=>{clearTimeout(liveTimer);live?.close();},{once:true});
  window.addEventListener('focus',()=>void refresh());
  document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')void refresh();});
  window.setInterval(()=>void refresh(),30000);
  document.addEventListener('click',event=>{if(event.target.closest('.sb-item[data-key="notifications"],#refresh-btn'))void refresh();});
  window.addEventListener('message',event=>{
    if(!['oneloss-notifications-changed','oneloss-notifications-count'].includes(event.data?.type))return;
    const trusted=[...document.querySelectorAll('iframe')].some(frame=>frame.contentWindow===event.source&&['/notifications_web_assets/','/pipeline_web_assets/'].some(path=>new URL(frame.src,location.href).pathname.includes(path)));
    if(!trusted)return;
    if(event.data.type==='oneloss-notifications-count'){
      const value=event.data.count;
      if(value===null||(Number.isSafeInteger(value)&&value>=0)){count=value;paint();}
    }else void refresh();
  });
  paint();
})();
