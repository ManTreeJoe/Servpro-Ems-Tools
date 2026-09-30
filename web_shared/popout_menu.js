/* Hidden contextual command: no toolbar clutter, no removal of the source. */
window.OneLossPopout=(()=>{
  async function open(tool,context={}){
    try{const result=await pywebview.api.open_popout(tool,context);if(!result?.ok)throw Error(result?.error||'Window could not open.');}
    catch(e){if(window.toastLog)window.toastLog(e.message);else window.alert(e.message);}
  }
  function menu(event,tool,context={}){
    event.preventDefault();document.getElementById('oneloss-popout-menu')?.remove();
    const box=document.createElement('div');box.id='oneloss-popout-menu';box.setAttribute('role','menu');
    box.style.cssText='position:fixed;z-index:99999;padding:5px;border:1px solid var(--border,#555);border-radius:7px;background:var(--surface,#25282b);box-shadow:0 8px 24px #0006';
    const button=document.createElement('button');button.textContent='Open in new window';button.setAttribute('role','menuitem');button.style.cssText='padding:10px 15px;border:0;background:transparent;color:var(--text,#fff);cursor:pointer';box.append(button);document.body.append(box);
    box.style.left=Math.max(8,Math.min(event.clientX,innerWidth-box.offsetWidth-8))+'px';box.style.top=Math.max(8,Math.min(event.clientY,innerHeight-box.offsetHeight-8))+'px';
    const close=()=>{box.remove();document.removeEventListener('pointerdown',outside,true);document.removeEventListener('keydown',key,true);};
    const outside=e=>{if(!box.contains(e.target))close();},key=e=>{if(e.key==='Escape'){e.stopPropagation();close();}};
    button.onclick=()=>{close();open(tool,context);};document.addEventListener('pointerdown',outside,true);document.addEventListener('keydown',key,true);button.focus();
  }
  document.addEventListener('contextmenu',event=>{const tool=event.target.closest('.sb-item[data-key]');if(tool)menu(event,tool.dataset.key);});
  return {open,menu};
})();
