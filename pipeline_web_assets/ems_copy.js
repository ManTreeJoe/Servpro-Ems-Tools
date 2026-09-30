/* Deliberate second-board creation. Never move the original, never auto-retry POST. */
async function openEmsCopyCreateModal(client, sourceId, onCreated) {
  const modal=document.createElement('div');modal.className='modal-scrim audit-overlay';
  modal.innerHTML=`<div class="modal-box compact-dialog ems-copy-dialog" role="dialog" aria-modal="true" aria-label="Copy EMS job to board">
    <header class="modal-head"><div class="modal-title">Copy to board</div><button class="audit-close" data-close aria-label="Close">×</button></header>
    <div class="modal-body job-log-form"><p class="wide" data-summary>Checking linked EMS cards…</p>
    <label class="wide">Destination section<select data-copy-section disabled></select></label>
    <p class="wide">The original stays where it is. Copies the title and job details and links the same EMS job. Old comments, checklists and Job Logs are not duplicated.</p>
    <p class="wide" data-copy-status role="status"></p>
    <div class="job-log-form-actions"><button class="btn btn-primary" data-create disabled>Create linked copy</button><button class="btn" data-open hidden>Open existing card</button><button class="btn" data-close>Cancel</button></div></div></div>`;
  const prior=document.activeElement;let busy=false;
  function close(){if(busy)return;document.removeEventListener('keydown',key,true);modal.remove();prior?.focus();}
  function key(e){if(e.key==='Escape'){e.stopImmediatePropagation();close();}}
  document.addEventListener('keydown',key,true);modal.querySelectorAll('[data-close]').forEach(b=>b.onclick=close);document.body.append(modal);
  const status=modal.querySelector('[data-copy-status]'),button=modal.querySelector('[data-create]'),select=modal.querySelector('select'),open=modal.querySelector('[data-open]');
  function showLink(result){if(result.url){open.hidden=false;open.onclick=()=>pywebview.api.open_url(result.url);}else if(result.id){open.hidden=false;open.onclick=()=>pywebview.api.open_url('https://trello.com/c/'+result.id);}}
  try{
    const preview=await pywebview.api.preview_ems_card_copy(client,sourceId);
    if(!modal.isConnected)return;if(!preview?.ok)throw Error(preview?.error||'Could not check the destination.');
    modal.querySelector('[data-summary]').textContent=`${preview.name} → ${preview.target_name}`;
    if(preview.existing){status.textContent='This job already has a linked card on that board. No new copy is needed.';showLink(preview.existing);return;}
    const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent='Choose a section…';select.append(placeholder);
    for(const lane of preview.lists||[]){const option=document.createElement('option');option.value=lane.id;option.textContent=lane.name;select.append(option);}
    select.disabled=false;select.onchange=()=>button.disabled=!select.value;select.focus();
    if(!preview.lists?.length)status.textContent='No open destination sections are available.';
  }catch(e){status.textContent=e.message;return;}
  button.onclick=async()=>{
    if(busy||!select.value)return;busy=true;button.disabled=true;select.disabled=true;status.textContent='Creating and linking the copy…';
    try{
      const result=await pywebview.api.create_ems_card_copy(client,sourceId,select.value);
      if(!result?.ok){showLink(result||{});throw Error(result?.error||'Copy was not confirmed.');}
      busy=false;close();await onCreated();
    }catch(e){status.textContent=e.message;button.textContent='Check / finish copy';}
    finally{busy=false;if(modal.isConnected){button.disabled=false;select.disabled=false;}}
  };
}
