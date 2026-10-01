/* Shared, non-blocking feedback for awaited tool API calls. Does not own streamed progress. */
(() => {
  'use strict';
  const wrapNative = document.currentScript?.dataset.bridge !== 'off';
  const pending = new Set(), controls = new WeakMap();
  let host, lastControl = null, interactedAt = 0, foregroundUntil = 0;
  let scheduled = false, ownsFeedback = false;
  // Only actual indicators, not arbitrary text containing "loading".
  const nativeSelector = '[data-loading-indicator],#snapshot-form-loading,.loading-ring,.ui-spinner,.cmt-refresh-spinner,.spinner,.snapshot-skeleton,.job-card-skeleton,#board-loading,.skeleton-line,.ems-skel,.settings-loading,.context-loading,.field-note-loading,.save-state.saving,.dept-splash-spin,#progress-bar,[role="progressbar"][aria-busy="true"]';
  function visible(el) {
    if (!el.getClientRects().length) return false;
    if (el.checkVisibility && !el.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return false;
    const rect=el.getBoundingClientRect();
    return rect.bottom>0 && rect.right>0 && rect.top<innerHeight && rect.left<innerWidth;
  }
  function nativeActive() {
    return [...document.querySelectorAll(nativeSelector)].some(el=>!host?.contains(el) && visible(el));
  }
  function childActive() {
    return [...document.querySelectorAll('iframe')].some(frame=>{
      try { return visible(frame) && frame.contentWindow.LoadingFeedback?.active(); }
      catch (_) { return false; } // Unrelated cross-origin frames are not ours to inspect.
    });
  }
  function schedule() {
    if (scheduled) return;
    scheduled=true;requestAnimationFrame(()=>{scheduled=false;render();});
  }
  const housekeeping = /(^|_)(health|heartbeat|telemetry|usage|appearance|preferences|unread_count|focus_window|set_last_panel|save_draft|draft_save|save_snapshot_draft)(_|$)/;
  const background = /(^background_|^companycam_import_status$|^board_view_shared_refresh$|^refresh_job_card_workspace$|^sync_snapshot_queue$|^sync_queue$|^job_comment_reactions$|^comment_reactions$)/;
  function label(name) {
    if (/search|find|match/.test(name)) return 'Searching…';
    if (/save|set_|pin|apply|mark|post|create|move|rename|delete|archive|update/.test(name)) return 'Saving changes…';
    if (/import|pull|download/.test(name)) return 'Loading files…';
    if (/generate|export|print/.test(name)) return 'Preparing…';
    return 'Loading…';
  }
  function ensure() {
    if (host?.isConnected) return;
    if (!document.body) return;
    if (!document.getElementById('oneloss-loading-style')) {
      const style=document.createElement('style'); style.id='oneloss-loading-style';
      style.textContent=`
        #oneloss-loading-feedback{position:fixed;inset:0 0 auto;z-index:2147483000;pointer-events:none;height:3px;}
        #oneloss-loading-feedback[hidden]{display:none!important}
        #oneloss-loading-feedback .olf-rail{height:3px;background:var(--border,#46525e);overflow:hidden;}
        #oneloss-loading-feedback .olf-fill{height:100%;width:30%;background:var(--accent,#77b9de);animation:olf-slide 1.25s ease-in-out infinite;}
        #oneloss-loading-feedback .olf-label{position:absolute;right:12px;top:8px;display:flex;align-items:center;gap:8px;padding:6px 10px;border:1px solid var(--border,#46525e);border-radius:6px;background:var(--surface,#202428);color:var(--text,#f3f5f7);font:12px/1.4 system-ui,sans-serif;box-shadow:0 2px 8px #0003;}
        html.oneloss-native-loading .ems-prog{visibility:hidden;}
        @keyframes olf-slide{from{transform:translateX(-100%)}to{transform:translateX(440%)}}
        @media(prefers-reduced-motion:reduce){#oneloss-loading-feedback .olf-fill{animation:none;width:100%;opacity:.55}}
      `;
      document.head.append(style);
    }
    host=document.createElement('div');host.id='oneloss-loading-feedback';host.hidden=true;
    host.innerHTML='<div class="olf-rail" aria-hidden="true"><div class="olf-fill"></div></div><div class="olf-label" role="status" aria-live="polite"><span data-olf-text></span></div>';
    document.body.append(host);
  }
  function render() {
    ensure(); if (!host) return;
    const ready=[...pending].filter(item=>item.visible);
    const native=nativeActive(), child=childActive();
    document.documentElement.classList.toggle('oneloss-native-loading',native || child);
    const streamed=[...document.querySelectorAll('.ems-prog.on')].some(visible);
    const hidden=!ready.length || document.hidden || native || child || streamed;
    if (host.hidden!==hidden) host.hidden=hidden;
    if (ready.length) {
      const text=ready.some(item=>Date.now()-item.started>20000) ? 'Still working…' :
        ready.length>1 ? 'Working…' : ready[0].label;
      const label=host.querySelector('[data-olf-text]');
      if(label.textContent!==text)label.textContent=text;
    }
    const owned=!document.hidden && (native || child || streamed || !hidden);
    if(owned!==ownsFeedback){ownsFeedback=owned;try{if(parent!==window)parent.LoadingFeedback?.refresh();}catch(_){}}
  }
  function busy(control, add) {
    if (!control) return;
    let record=controls.get(control);
    if (add) {
      if (!record) {record={count:0, aria:control.getAttribute('aria-busy')};controls.set(control,record);}
      record.count++;
      control.setAttribute('aria-busy','true');
    } else if (record && --record.count===0) {
      record.aria===null ? control.removeAttribute('aria-busy') : control.setAttribute('aria-busy',record.aria);
      control.classList.remove('olf-control');controls.delete(control);
    }
  }
  function track(name, promise, options={}) {
    if (!promise || typeof promise.then!=='function') return promise;
    const recent=Date.now()-interactedAt<1200;
    if (!options.force && (housekeeping.test(name) || background.test(name)
        || (!recent && !pending.size && Date.now()>foregroundUntil))) return promise;
    const control=options.control || (recent && lastControl?.isConnected ? lastControl : null);
    const item={started:Date.now(),label:options.label || label(name),visible:false};
    pending.add(item);
    const timer=setTimeout(()=>{item.visible=true;busy(control,true);render();},250);
    const longTimer=setTimeout(render,20050);
    const settle=()=>{clearTimeout(timer);clearTimeout(longTimer);pending.delete(item);foregroundUntil=Date.now()+300;if(item.visible)busy(control,false);render();};
    promise.then(settle,settle);
    return promise; // Preserve result, rejection, and identity; never hide an error.
  }
  for (const type of ['click','submit','change','input','keydown']) document.addEventListener(type,event=>{
    if (type==='keydown' && !['Enter',' '].includes(event.key)) return;
    interactedAt=Date.now();lastControl=event.target.closest?.('button,[role="button"]') || null;
  },true);
  document.addEventListener('visibilitychange',render);
  window.addEventListener('pywebviewready',()=>{foregroundUntil=Date.now()+1500;});
  window.LoadingFeedback={track,refresh:schedule,active:()=>ownsFeedback};
  const observe=()=>{new MutationObserver(records=>{
    if(records.some(r=>r.target!==document.documentElement && !host?.contains(r.target)))schedule();
  }).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class','hidden','style','open','aria-busy']});schedule();};
  if(document.body)observe();else document.addEventListener('DOMContentLoaded',observe,{once:true});
  window.addEventListener('resize',schedule);
  document.addEventListener('scroll',schedule,true);
  // Iframes are wrapped by iframe_shim. Standalone DEV/pop-out windows use the native bridge.
  if (wrapNative && window.parent===window) window.addEventListener('pywebviewready',()=>{
    const api=window.pywebview?.api;
    if (!api || window.__loadingFeedbackWrapped) return;
    window.__loadingFeedbackWrapped=true;
    window.pywebview.api=new Proxy(api,{get(target,prop){
      const value=Reflect.get(target,prop);
      if(typeof value!=='function')return value;
      return (...args)=>track(String(prop),value.apply(target,args));
    }});
  });
})();
