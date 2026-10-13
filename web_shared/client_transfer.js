/* One explicit transfer flow shared by job cards and Clients. */
window.ClientTransfer = {async open(reference, cardId='', onSaved=()=>{}) {
 const api=window.pywebview?.api;
 const dialog=document.createElement('dialog'); dialog.className='client-transfer-dialog';
 dialog.setAttribute('aria-label','Transfer job to client');
 dialog.innerHTML='<form><h2>Transfer to client</h2><p data-job></p><p data-current></p><p>Only the client relationship changes. Job history, cards, photos and folders stay intact.</p><label>Find a client<input data-search type="search" placeholder="Search saved clients"></label><label>Destination client<select data-clients required></select></label><details><summary>Create a client</summary><label>Client name<input data-new maxlength="300"></label><button type="button" data-create>Create client</button></details><p data-confirm></p><p role="status" data-status>Loading saved client relationship…</p><footer><button type="button" data-cancel>Cancel</button><button type="submit" data-save disabled>Confirm transfer</button></footer></form>';
 document.body.append(dialog); dialog.showModal();
 const $=s=>dialog.querySelector(s), status=$('[data-status]'); let context, busy=false;
 dialog.querySelectorAll('input,select,[data-create]').forEach(el=>el.disabled=true);
 const close=()=>{if(!busy){dialog.close();dialog.remove();}};
 $('[data-cancel]').onclick=close;
 dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
 const error=e=>status.textContent=e?.message||String(e);
 function changed(){
  const select=$('[data-clients]'), value=select.value;
  $('[data-save]').disabled=busy||!value||value===(context.job.client_id||'__none__');
  $('[data-confirm]').textContent=value ? `Move “${context.job.display_name}” to ${value==='__none__'?'no client (unlinked)':select.selectedOptions[0].textContent}?` : '';
 }
 function options(selected=''){
  const select=$('[data-clients]'),query=$('[data-search]').value.toLowerCase();select.replaceChildren(new Option('Choose a client',''));
  select.add(new Option('No client — unlink','__none__'));
  context.clients.filter(c=>c.display_name.toLowerCase().includes(query)||c.client_id===selected).forEach(c=>select.add(new Option(c.display_name,c.client_id)));
  select.value=selected;changed();
 }
 function lock(value){busy=value;dialog.querySelectorAll('button,input,select').forEach(el=>el.disabled=value);changed();}
 $('[data-search]').oninput=()=>options($('[data-clients]').value);
 $('[data-clients]').onchange=changed;
 $('[data-create]').onclick=async()=>{
  const name=$('[data-new]').value.trim(); if(!name)return;
  lock(true);status.textContent='Creating client…';
  try{const r=await api.create_client_account(name,context.department);if(!r?.ok)throw new Error(r?.error||'Client was not created.');
   if(!context.clients.some(c=>c.client_id===r.client.client_id))context.clients.push(r.client);
   options(r.client.client_id);status.textContent='Client ready. Confirm the transfer below.';
  }catch(e){error(e);}finally{lock(false);}
 };
 $('form').onsubmit=async e=>{
  e.preventDefault();if(busy||$('[data-save]').disabled)return;
  const destination=$('[data-clients]').value;lock(true);status.textContent='Saving client relationship…';
  try{const r=await api.transfer_job_client(context.job.job_id,destination==='__none__'?'':destination,context.job.client_revision);
   if(!r?.ok)throw new Error(r?.error||'Transfer not confirmed. Reopen to check the saved client before retrying.');
   busy=false;close();await onSaved(r);
  }catch(e){error(e);}finally{if(dialog.isConnected)lock(false);}
 };
 try{context=await api.client_ownership_context(reference,cardId);if(!context?.ok)throw new Error(context?.error||'Client relationship unavailable.');
  if(!dialog.isConnected)return;
  $('[data-job]').textContent=context.job.display_name;
  const current=context.clients.find(c=>c.client_id===context.job.client_id);
  $('[data-current]').textContent='Current client: '+(current?.display_name||(context.job.client_id?'Unavailable client':'Not linked'));
  dialog.querySelectorAll('input,select,[data-create]').forEach(el=>el.disabled=false);
  options(context.job.client_id||'__none__');status.textContent='';
 }catch(e){error(e);dialog.querySelectorAll('input,select,[data-create]').forEach(el=>el.disabled=true);}
}};
