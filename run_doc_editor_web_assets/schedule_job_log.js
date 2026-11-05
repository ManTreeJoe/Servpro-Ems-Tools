/* Dev preview only. Server-linked saves are deliberately unavailable. */
window.ScheduleJobLog = function ({live}) {
  let generation=0,dialog=null;
  const close=()=>{generation++;dialog?.close();dialog?.remove();dialog=null;};
  async function open(visit,current=()=>true){
    close();const token=generation;
    const result=await live.workItemPreview(visit.id,visit.revision);
    if(token!==generation||!current())return;
    if(!result.preview_only||result.save_available!==false)throw Error('Unsupported linked work server contract. Reopen Schedule.');
    const node=document.createElement('dialog');dialog=node;
    node.setAttribute('aria-label','Linked Schedule and Job Log preview');
    node.style.width='min(700px,calc(100% - 32px))';
    const heading=document.createElement('h2');heading.textContent=result.job.title;node.append(heading);
    const status=document.createElement('p');status.setAttribute('role','status');status.textContent=result.blocked_reason;node.append(status);
    const explanation=document.createElement('p');explanation.textContent='Planned work is shared between the two views. Performed work stays separate. This preview creates no visit or log.';node.append(explanation);
    const fields=document.createElement('fieldset');const legend=document.createElement('legend');legend.textContent='Planned work';fields.append(legend);
    function input(label,value,type='text'){
      const wrap=document.createElement('label');wrap.style.cssText='display:grid;gap:4px;margin:10px 0';wrap.append(document.createTextNode(label));
      const control=document.createElement(type==='textarea'?'textarea':'input');
      if(type!=='textarea')control.type=type;
      control.value=value||'';wrap.append(control);fields.append(wrap);return control;
    }
    const planned=result.item.planned;
    input('Planned date',planned.date,'date');input('Planned arrival window',planned.arrival);
    planned.activities.forEach(activity=>{input('Planned activity',activity.label);input('Assigned crew',activity.people.join(', '));});
    input('Planning notes',planned.notes,'textarea');node.append(fields);
    const actual=document.createElement('fieldset');const actualLegend=document.createElement('legend');actualLegend.textContent='Performed work';actual.append(actualLegend);
    const actualInfo=document.createElement('p');actualInfo.textContent='No performed date, times or completion are inferred from this plan. Existing performed history will be preserved by the linked save transaction.';actual.append(actualInfo);node.append(actual);
    const footer=document.createElement('footer');footer.style.cssText='display:flex;justify-content:flex-end;gap:8px;margin-top:16px';
    const dismiss=document.createElement('button');dismiss.type='button';dismiss.className='btn';dismiss.textContent='Close preview';dismiss.onclick=close;
    const save=document.createElement('button');save.type='button';save.className='btn btn-primary';save.textContent='Save linked work';save.disabled=true;
    footer.append(dismiss,save);node.append(footer);node.addEventListener('close',()=>{generation++;node.remove();if(dialog===node)dialog=null;});
    document.body.append(node);node.showModal();dismiss.focus();
  }
  window.addEventListener('pagehide',close);
  return {open,close};
};
