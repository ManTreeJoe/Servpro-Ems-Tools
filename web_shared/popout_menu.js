/* Hidden contextual command: no toolbar clutter, no removal of the source. */
window.OneLossPopout=window.OneLossPopout||(()=>{
  let dismiss;
  function mount(host,tool,context=()=>({})){
    if(!host)return;
    const target=host.querySelector('.card-quick-actions')||host;
    if(target.querySelector(':scope > .oneloss-popout-button'))return;
    const button=document.createElement('button');button.type='button';button.className='oneloss-popout-button';
    button.innerHTML='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M14 3h7v7M21 3l-11 11M10 3H3v18h18v-7"/></svg>';button.title=host.title||'Open in new window';button.setAttribute('aria-label','Open in new window');
    button.style.cssText='margin-left:auto;flex-shrink:0;box-sizing:border-box;width:32px;height:32px;display:inline-flex;align-items:center;justify-content:center;padding:0;border:1px solid var(--border,#555);border-radius:6px;background:var(--surface,#25282b);color:var(--text,#fff);font:inherit;font-size:18px;cursor:pointer';
    button.onclick=async event=>{event.stopPropagation();button.disabled=true;try{await open(tool,typeof context==='function'?context():context);}finally{button.disabled=false;}};
    const close=target.querySelector(':scope > [data-close],:scope > .audit-close');
    if(close)target.insertBefore(button,close);else target.append(button);
  }
  function mountHeaders(){
    document.querySelectorAll('header[data-popout-tool],.tool-workspace-head[data-popout-tool]').forEach(host=>mount(host,host.dataset.popoutTool,()=>{try{return JSON.parse(host.dataset.popoutContext||'{}');}catch(_){return {};}}));
    const folder=location.pathname.match(/\/([a-z_]+)_web_assets\//)?.[1];
    if(folder&&folder!=='home'&&!new URLSearchParams(location.search).has('job_workspace')){
      const header=document.querySelector('.topbar');
      if(header&&!header.closest('dialog,[role="dialog"],.modal'))mount(header,folder==='audit'?'daily_run':folder);
    }
  }
  const observer=new MutationObserver(mountHeaders);
  function start(){mountHeaders();observer.observe(document.body,{childList:true,subtree:true});}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
  async function open(tool,context={}){
    try{const result=await pywebview.api.open_popout(tool,context);if(!result?.ok)throw Error(result?.error||'Window could not open.');}
    catch(e){if(window.toastLog)window.toastLog(e.message);else window.alert(e.message);}
  }
  function menu(event,tool,context={}){
    event.preventDefault();dismiss?.();
    const trigger=event.currentTarget instanceof HTMLElement?event.currentTarget:event.target;
    const host=event.target.closest('dialog[open]')||document.body;
    const box=document.createElement('div');box.id='oneloss-popout-menu';box.setAttribute('role','menu');
    box.style.cssText='position:fixed;z-index:99999;padding:5px;border:1px solid var(--border,#555);border-radius:7px;background:var(--surface,#25282b);box-shadow:0 8px 24px #0006';
    const button=document.createElement('button');button.type='button';button.textContent='Open in new window';button.setAttribute('role','menuitem');button.style.cssText='padding:10px 15px;border:0;background:transparent;color:var(--text,#fff);cursor:pointer';box.append(button);host.append(box);
    box.style.left=Math.max(8,Math.min(event.clientX,innerWidth-box.offsetWidth-8))+'px';box.style.top=Math.max(8,Math.min(event.clientY,innerHeight-box.offsetHeight-8))+'px';
    const close=()=>{box.remove();document.removeEventListener('pointerdown',outside,true);document.removeEventListener('keydown',key,true);host.removeEventListener('close',close);dismiss=null;};
    const outside=e=>{if(!box.contains(e.target))close();},key=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close();trigger?.focus();}};
    dismiss=close;host.addEventListener('close',close);
    button.onclick=()=>{close();open(tool,context);};document.addEventListener('pointerdown',outside,true);document.addEventListener('keydown',key,true);button.focus();
  }
  document.addEventListener('contextmenu',event=>{
    if(event.defaultPrevented||event.target.closest('input,textarea,[contenteditable="true"]'))return;
    const tool=event.target.closest('.sb-item[data-key],[data-popout-tool]');
    if(tool){let context={};try{context=JSON.parse(tool.dataset.popoutContext||'{}');}catch(_){}
      menu(event,tool.dataset.popoutTool||tool.dataset.key,context);return;}
    // Tool headers are safe launch points. Generic edit dialogs are deliberately
    // excluded: reopening one cannot safely reproduce its unsaved draft.
    if(!event.target.closest('dialog,[role="dialog"],.modal')&&event.target.closest('.topbar,.brand-name')){
      const folder=location.pathname.match(/\/([a-z_]+)_web_assets\//)?.[1];
      if(folder&&folder!=='home')menu(event,folder==='audit'?'daily_run':folder);
    }
  });
  return {open,menu,mount};
})();
