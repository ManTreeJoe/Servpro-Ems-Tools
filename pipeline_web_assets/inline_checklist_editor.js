/* Job-scoped inline edits: never rebuild the surrounding job or comment draft. */
window.InlineChecklistEditor={mount(root,cardId,updated){
 let active=null,busy=false;
 root.addEventListener('click',event=>{
  const trigger=event.target.closest('[data-edit-check-item],[data-add-check-item],[data-new-checklist]');
  if(!trigger||busy)return;event.preventDefault();event.stopPropagation();
  if(active){active.querySelector('input')?.focus();return;}
  const list=trigger.closest('[data-checklist-id]'),item=trigger.dataset.editCheckItem;
  const creating=trigger.hasAttribute('data-new-checklist');
  const row=trigger.closest('.check-item-line');
  const form=document.createElement('form');form.className='check-item-form';
  const input=document.createElement('input');input.maxLength=500;input.required=true;
  input.value=row?.querySelector('[data-check-name]')?.dataset.checkName||'';
  const wasNA=/^\[N\/A\]\s*/i.test(input.value);
  if(item)input.value=input.value.replace(/^\[N\/A\]\s*/i,'');
  const naLabel=document.createElement('label');naLabel.className='check-item-na';
  const na=document.createElement('input');na.type='checkbox';na.checked=wasNA;
  naLabel.append(na,document.createTextNode('Does not apply'));
  na.title='Labels the item [N/A] and checks it off in Trello. Turning this off reopens it.';
  input.placeholder=creating?'Checklist name, e.g. Subcontractors':'Enter checklist item';input.setAttribute('aria-label',creating?'New checklist name':item?'Edit checklist item':'New checklist item');
  const save=document.createElement('button');save.type='submit';save.className='btn btn-primary';save.textContent=item?'Save':'Add';
  const cancel=document.createElement('button');cancel.type='button';cancel.className='btn';cancel.textContent='Cancel';
  const status=document.createElement('small');status.setAttribute('role','status');
  const close=()=>{if(busy)return;form.remove();active=null;trigger.focus();};cancel.onclick=close;
  form.append(input);if(item)form.append(naLabel);form.append(save,cancel,status);(row||trigger).after(form);active=form;input.focus();input.select();
  form.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close();}};
  form.onsubmit=async e=>{
   e.preventDefault();if(busy||!input.value.trim())return;
   busy=true;na.disabled=input.disabled=save.disabled=cancel.disabled=true;status.textContent='Saving to Trello…';
   const prior=[...root.querySelectorAll('[data-checklist-id]')].map(el=>el.dataset.checklistId);
   try{
    const operation=creating?'create':item?(na.checked?'mark_na':wasNA?'restore_applicable':'rename_item'):'add';
    const result=await pywebview.api.edit_job_checklist(cardId,operation,input.value,list?.dataset.checklistId||'',item||'');
    if(!result?.ok){status.textContent=result?.error||'Could not save. Your text is kept.';if(result?.uncertain){save.dataset.uncertain='1';}return;}
    const id=result.checklist_id||list?.dataset.checklistId||result.checklists.find(cl=>!prior.includes(cl.id))?.id;
    form.remove();active=null;updated(result.checklists,id);
    const refreshed=[...root.querySelectorAll('[data-checklist-id]')].find(el=>el.dataset.checklistId===id);
    (refreshed?.querySelector('[data-add-check-item]')||root.querySelector('[data-new-checklist]'))?.focus();
   }catch(_){status.textContent='Could not confirm the change. Refresh the card before retrying; your text is kept.';save.dataset.uncertain='1';}
   finally{busy=false;na.disabled=input.disabled=cancel.disabled=false;save.disabled=!!save.dataset.uncertain;}
  };
 });
}};
