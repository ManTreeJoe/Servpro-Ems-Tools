window.JobChecklistEditor={open(cardId,lists,onDone){
 const previous=document.activeElement,host=document.createElement('div');host.className='modal-scrim audit-overlay';
 host.innerHTML='<section class="import-workspace-card" role="dialog" aria-modal="true" aria-label="Edit job checklists"><header><h2>Edit job checklists</h2><button class="btn" data-done>Done</button></header><main style="padding:20px;overflow:auto"><p>Changes sync to this section’s Trello card only. Shared templates are unchanged.</p><form data-create><label>New checklist <input name="name" maxlength="500" placeholder="e.g. Subcontractors" required></label><button class="btn" type="submit">Add checklist</button></form><div data-lists></div></main><footer><p role="status" data-status></p></footer></section>';
 document.body.append(host);let busy=false,changed=false,uncertain=false;
 const q=s=>host.querySelector(s),status=t=>q('[data-status]').textContent=t;
 async function save(operation,name,list='',item=''){
  if(busy||uncertain)return;busy=true;host.querySelectorAll('button,input').forEach(e=>e.disabled=true);status('Saving to Trello…');
  try{const r=await pywebview.api.edit_job_checklist(cardId,operation,name,list,item);if(!r?.ok){uncertain=!!r?.uncertain;throw Error(r?.error||'Could not save.');}lists=r.checklists;changed=true;render();status('Saved to Trello.');}
  catch(e){status(e.message||'Could not confirm the save.');}
  finally{busy=false;host.querySelectorAll('button,input').forEach(e=>e.disabled=uncertain);q('[data-done]').disabled=false;}
 }
 function form(label,value,operation,list='',item=''){
  const f=document.createElement('form');f.style.cssText='display:flex;gap:8px;margin:8px 0;align-items:center';
  const input=document.createElement('input');input.value=value;input.maxLength=500;input.required=true;input.setAttribute('aria-label',label);input.style.flex='1';
  const b=document.createElement('button');b.className='btn';b.type='submit';b.textContent=operation==='add'?'Add item':'Save name';
  f.append(input,b);f.onsubmit=e=>{e.preventDefault();void save(operation,input.value,list,item);};return f;
 }
 function render(){const target=q('[data-lists]');target.replaceChildren();for(const list of lists){
  const section=document.createElement('section');section.style.cssText='margin-top:20px;border-top:1px solid var(--border);padding-top:12px';
  const title=document.createElement('h3');title.textContent=list.name;section.append(title,form('Checklist name',list.name,'rename',list.id));
  for(const item of list.items||[])section.append(form('Item name',item.name,'rename_item',list.id,item.id));
  section.append(form('New checklist item','','add',list.id));target.append(section);
 }}
 function close(){if(busy)return;host.remove();document.removeEventListener('keydown',key,true);previous?.focus();if(changed||uncertain)onDone();}
 function key(e){if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();close();}if(e.key==='Tab'){const nodes=[...host.querySelectorAll('button,input')].filter(n=>!n.disabled),i=nodes.indexOf(document.activeElement);if(e.shiftKey&&i===0){e.preventDefault();nodes.at(-1).focus();}else if(!e.shiftKey&&i===nodes.length-1){e.preventDefault();nodes[0].focus();}}}
 q('[data-create]').onsubmit=e=>{e.preventDefault();void save('create',e.currentTarget.elements.name.value);};q('[data-done]').onclick=close;
 document.addEventListener('keydown',key,true);render();q('[data-create] input').focus();
}};
