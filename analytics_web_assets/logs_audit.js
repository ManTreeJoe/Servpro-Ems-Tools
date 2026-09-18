/* Structured weekly audit. No external writes before the explicit preview confirmation. */
(() => {
 'use strict';
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let dialog, body, status, filters={}, queue, selected, activeForm, savedForm='', busy=false, operation;
 function formFields(){const fields=Object.fromEntries(new FormData(activeForm));for(const input of activeForm.querySelectorAll('[type=checkbox]'))fields[input.name]=input.checked;return fields;}
 const hasUnsavedChanges=()=>Boolean(activeForm)&&JSON.stringify(formFields())!==savedForm;
 const scanned=new Set();
 const filingDivisions=['EMS','Contents','EMS + Contents','Recon','Service call / no charge'];
 const api=async(name,...args)=>{const r=await window.pywebview.api[name](...args);if(!r?.ok)throw Error(r?.error||'Request did not complete.');return r;};
 function error(e){status.textContent=e.message||String(e);}
 async function run(fn){if(busy)return;busy=true;body.inert=true;try{await fn();}catch(e){error(e);}finally{busy=false;body.inert=false;}}
 function init(){
  if(dialog)return;
  dialog=document.createElement('dialog');dialog.id='logs-audit';dialog.setAttribute('aria-label','Weekly Logs audit');
  dialog.innerHTML='<div class="section-head"><h2>Logs audit</h2><button type="button" data-close aria-label="Close Logs audit">×</button></div><p data-status role="status"></p><div data-body></div>';
  document.body.append(dialog);body=dialog.querySelector('[data-body]');status=dialog.querySelector('[data-status]');
  dialog.querySelector('[data-close]').onclick=()=>{if(busy)return;if(hasUnsavedChanges()&&!confirm('Close this form? Unsaved changes will be lost.'))return;dialog.close();};
  dialog.addEventListener('cancel',e=>{if(busy||activeForm){e.preventDefault();dialog.querySelector('[data-close]').click();}});
 }
 function field(label,key,value='',type='text'){
  return `<label>${esc(label)}<input name="${key}" type="${type}" value="${esc(value)}"></label>`;
 }
 function pick(label,key,values,value=''){
  return `<label>${esc(label)}<select name="${key}"><option value="">Not recorded</option>${values.map(v=>`<option ${v===value?'selected':''}>${esc(v)}</option>`).join('')}</select></label>`;
 }
 function note(label,key,value=''){return `<label>${esc(label)}<textarea name="${key}" rows="3">${esc(value)}</textarea></label>`;}
 function checked(label,key,value){return `<label class="audit-check"><input type="checkbox" name="${key}" ${value?'checked':''}>${esc(label)}</label>`;}
 async function showQueue(){
  queue=await api('logs_queue');activeForm=null;selected=null;operation=null;
  status.textContent=`${queue.cards.length} current cards · To Be Preserved only · Drafts saved on this PC. No automatic moves.`;
  body.innerHTML='<div class="actions"><input type="search" data-search placeholder="Find a job" aria-label="Find audit job"><button data-refresh>Refresh queue</button><button data-scan>Gather evidence for all</button></div><p data-progress></p><div class="table-wrap"><table><thead><tr><th>Job</th><th>Audit draft</th><th></th></tr></thead><tbody data-cards></tbody></table></div><details><summary>Publication history / recovery</summary><div data-history></div></details>';
  const rows=()=>{const q=body.querySelector('[data-search]').value.toLowerCase();body.querySelector('[data-cards]').innerHTML=queue.cards.filter(c=>c.name.toLowerCase().includes(q)).map(c=>`<tr><td>${esc(c.name)}</td><td>${queue.drafts[c.id]?'Draft saved':scanned.has(c.id)?'Evidence gathered — not audited':'Not reviewed'}</td><td><button data-card="${esc(c.id)}">Audit job</button></td></tr>`).join('')||'<tr><td colspan="3">No matching cards.</td></tr>';};
  rows();body.querySelector('[data-search]').oninput=rows;
  const excel=document.createElement('button');excel.textContent='Export weekly Excel copy';
  excel.title='Exports saved forms for this review period, including moved cards. Choose your template, then a new filename.';
  body.querySelector('.actions').append(excel);
  excel.onclick=()=>run(async()=>{status.textContent='Choose the original Weekly Audit template, then where to save the filled copy.';const r=await api('logs_export_excel',filters.start,filters.end);status.textContent=r.cancelled?'Export cancelled.':`Exported ${r.count} saved reviews. Draft status and sources are included; no Trello changes.`;});
  const batch=document.createElement('button');batch.textContent='Review saved drafts for this period';body.querySelector('.actions').append(batch);
  batch.onclick=()=>run(async()=>{
   const prepared=[],failures=[];
   for(const card of queue.cards){
    const f=queue.drafts[card.id]?.fields;
    if(!f || f.period_start!==filters.start || f.period_end!==filters.end)continue;
    try{prepared.push((await api('logs_preview',card.id)).operation);}catch(e){failures.push(card.name+': '+e.message);}
   }
   showBatch(prepared,failures);
  });
  body.querySelector('[data-refresh]').onclick=()=>run(showQueue);
  body.querySelector('[data-cards]').onclick=e=>{const b=e.target.closest('[data-card]');if(b)run(()=>openCard(b.dataset.card));};
  body.querySelector('[data-scan]').onclick=()=>run(async()=>{
   let failed=0;const issues=[];
   for(let i=0;i<queue.cards.length;i++){
    const c=queue.cards[i];body.querySelector('[data-progress]').textContent=`Reading ${i+1}/${queue.cards.length}: ${c.name}`;
    try{await api('logs_inspect',c.id);scanned.add(c.id);}catch(e){failed++;issues.push(`${c.name}: ${e.message}`);}
   }
   body.querySelector('[data-progress]').textContent=`Evidence read for ${queue.cards.length-failed} cards; ${failed} failed. Each still needs the form and user confirmation. ${issues.join(' • ')}`;rows();
  });
  body.querySelector('[data-history]').innerHTML=queue.operations.slice().reverse().map(o=>`<p>${esc(o.name)} → ${esc(o.destination_name)} · ${esc(o.status)} ${!['done','superseded'].includes(o.status)?`<button data-retry="${esc(o.id)}">Review / retry</button>`:''}</p>`).join('')||'<p>No publications yet.</p>';
  body.querySelector('[data-history]').onclick=e=>{const b=e.target.closest('[data-retry]');if(b)showPreview(queue.operations.find(o=>o.id===b.dataset.retry));};
 }
 async function openCard(id){
  const r=await api('logs_inspect',id,filters.start,filters.end);selected=r;scanned.add(id);const ev=r.evidence;
  const f={period_start:filters.start,period_end:filters.end,decision:'hold',...r.draft?.fields};
  if(r.ar?.revision!==r.draft?.ar?.revision){f.ar_resolution='';f.billing_checked=false;f.all_confirmed=false;}
  const suggestions=r.suggestions||{};
  for(const [key,s] of Object.entries(suggestions))if(s.value!=null && !Object.prototype.hasOwnProperty.call(r.draft?.fields||{},key))f[key]=s.value;
  const reviewFiling=!filingDivisions.includes(f.scope)||suggestions.scope?.conflict;
  // Confirmation is tied to the currently inspected evidence, never carried over after a change.
  if(r.draft?.revision!==ev.revision)for(const k of ['front_checked','field_checked','estimating_checked','billing_checked','identity_checked','all_confirmed'])f[k]=false;
  status.textContent=ev.card.name+(r.carried_forward?' · Previous findings carried forward; confirm this period.':' · Review evidence before confirming.');
  body.innerHTML=`<div class="actions"><button data-back>Queue</button><button data-open>Open job</button></div>
   <div class="audit-layout"><section><h3>Card evidence</h3><details><summary>Description</summary><pre>${esc(ev.card.desc||'No description')}</pre></details>
   <details><summary>Checklists (${ev.checklists.length})</summary>${ev.checklists.map(c=>`<h4>${esc(c.name)}</h4><ul>${(c.checkItems||[]).map(i=>`<li>${i.state==='complete'?'✓':'○'} ${esc(i.name)}</li>`).join('')}</ul>`).join('')}</details>
   <label>Search notes<input data-note-search type="search" placeholder="Billed, initial, paid, check…"></label><div data-notes></div></section>
   <form data-audit><h3>Weekly audit form</h3><div class="review-fields">
   ${field('Period from','period_start',f.period_start,'date')}${field('Through','period_end',f.period_end,'date')}
   ${field('Job Date (received)','job_date',f.job_date,'date')}<input type="hidden" name="scope" value="${esc(f.scope||'')}">
   ${field('EMS estimator (or N/A)','ems_estimator',f.ems_estimator)}${field('Contents estimator (if applicable)','contents_estimator',f.contents_estimator)}
   ${pick('Initial note sent on time?','initial_note',['Yes','No','N/A'],f.initial_note)}${field('Coordinator who missed it','missed_by',f.missed_by)}
   ${field('Inspection completed (date, time, timezone)','inspection_completed_at',f.inspection_completed_at)}
   ${field('Initial note sent (date, time, timezone)','initial_note_sent_at',f.initial_note_sent_at)}
   ${field('Timing source / comment reference','timing_source',f.timing_source)}
   ${pick('WC / file status','file_status',['Closed','Open','Needs Merge','N/A'],f.file_status)}
   </div>${checked('Front checks reviewed','front_checked',f.front_checked)}
   <h4>EMS billing</h4><div class="review-fields">${field('Work started','ems_start',f.ems_start,'date')}${field('Ready for billing','ems_ready',f.ems_ready,'date')}${field('Billing completed','ems_billed',f.ems_billed,'date')}</div><p data-ems-days></p>
   <h4>Contents billing (leave blank if not applicable)</h4><div class="review-fields">${field('Original Contents card started','contents_start',f.contents_start,'date')}${field('Ready for billing','contents_ready',f.contents_ready,'date')}${field('Billing completed','contents_billed',f.contents_billed,'date')}</div><p data-contents-days></p>
   ${note('Estimator Notes','estimator_notes',f.estimator_notes)}${checked('Estimating review complete','estimating_checked',f.estimating_checked)}
   ${note('Field / lead findings','field_notes',f.field_notes)}${checked('Field evidence reviewed (or not applicable)','field_checked',f.field_checked)}
   ${note('Explicit billed evidence / source note','billing_evidence',f.billing_evidence)}${pick('Verified billing status','billing_status',['Billed','Not billed','Unclear'],f.billing_status)}
   ${note('Conflicting billing evidence (blank if resolved)','billing_conflict',f.billing_conflict)}
   ${note('AR conflict resolution / supporting source','ar_resolution',f.ar_resolution)}
   <section data-ar><h4>AR evidence</h4><button type="button" data-find-ar>Find AR card</button><p data-ar-status>No AR match confirmed. This does not block clear Logs billing evidence.</p><div data-ar-results></div></section>
   ${field('Recon / other scope billed date','other_billed',f.other_billed,'date')}
   ${note('Payment notes — receipt date, scope, partial balance','payment_notes',f.payment_notes)}
   ${checked('Billing / applicable AR evidence reviewed','billing_checked',f.billing_checked)}
   ${note('Audit Notes / Open Action Needed','audit_notes',f.audit_notes)}
   ${reviewFiling?`<section data-filing-review><p>The source does not identify one clear division for filing. Review the card before choosing which billing dates apply.</p><label>Division for filing<select data-filing-division aria-label="Division for filing"><option value="">Choose division for filing</option>${filingDivisions.map(value=>`<option ${value===f.scope?'selected':''}>${esc(value)}</option>`).join('')}</select></label></section>`:''}
   <div class="review-fields">${pick('Disposition','decision',['hold','billed','questions'],f.decision)}${field('Confirmed billed month','billed_month',f.billed_month,'month')}
   <label>Destination lane<select name="destination"><option value="">Leave in place</option>${r.lanes.map(l=>`<option value="${esc(l.id)}" ${l.id===f.destination?'selected':''}>${esc(l.name)}</option>`).join('')}</select></label></div>
   ${checked('Correct card, claim and scope confirmed','identity_checked',f.identity_checked)}${checked('I reviewed the full form and confirm the recorded findings','all_confirmed',f.all_confirmed)}
   <div class="actions"><button type="button" data-save>Save draft</button><button type="button" class="primary" data-preview>Preview audit & disposition</button></div></form></div>`;
  activeForm=body.querySelector('[data-audit]');activeForm.onsubmit=e=>e.preventDefault();
  activeForm.elements.initial_note.disabled=true;
  const timingHint=document.createElement('small');activeForm.elements.initial_note.closest('label').append(timingHint);
  const updateTiming=()=>{
   const a=activeForm.elements.inspection_completed_at.value,b=activeForm.elements.initial_note_sent_at.value;
   const pattern=/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/;
   const minutes=pattern.test(a)&&pattern.test(b)?(new Date(b)-new Date(a))/60000:NaN;
   const valid=Number.isFinite(minutes)&&minutes>=0;
   activeForm.elements.initial_note.value=valid?(minutes<=60?'Yes':'No'):'';
   timingHint.textContent=valid?`${Math.round(minutes)} minutes after completion · limit 60 minutes`:'Unverified — completion and sent timestamps required. Example: 2026-09-17T14:30:00-07:00';
  };
  for(const key of ['inspection_completed_at','initial_note_sent_at'])activeForm.elements[key].addEventListener('input',updateTiming);
  updateTiming();
  const renderAR=(ar,comparison,confirmed)=>{
   const area=body.querySelector('[data-ar-results]');area.replaceChildren();
   body.querySelector('[data-ar-status]').textContent=(confirmed?'Confirmed: ':'Candidate: ')+ar.card.name+' · '+comparison.summary;
   const description=document.createElement('pre');description.textContent=ar.card.desc||'No description';area.append(description);
   for(const comment of ar.comments){const details=document.createElement('details'),summary=document.createElement('summary'),text=document.createElement('pre');summary.textContent=comment.date.slice(0,10)+' · '+comment.author;text.textContent=comment.text;details.append(summary,text);area.append(details);}
   if(!confirmed){const button=document.createElement('button');button.type='button';button.textContent='Confirm this AR card (same job, division and unit)';button.onclick=()=>run(async()=>{const review=await api('logs_ar_review',id,ar.card.id,true);activeForm.elements.billing_checked.checked=false;activeForm.elements.all_confirmed.checked=false;activeForm.elements.ar_resolution.value='';if(review.comparison.conflicts.length){activeForm.elements.billing_conflict.value=review.comparison.summary;activeForm.elements.decision.value='questions';}renderAR(review.evidence,review.comparison,true);});area.prepend(button);}
  };
  if(r.ar)renderAR(r.ar,r.ar_comparison,true);
  body.querySelector('[data-find-ar]').onclick=()=>run(async()=>{
   const found=await api('logs_ar_candidates',id);const area=body.querySelector('[data-ar-results]');area.replaceChildren();
   body.querySelector('[data-ar-status]').textContent=`${found.candidates.length} candidates from ${found.searched_count} AR cards. Inspect before confirming.`;
   for(const candidate of found.candidates){const button=document.createElement('button');button.type='button';button.textContent=candidate.card.name+' · '+candidate.reason;button.onclick=()=>run(async()=>{const review=await api('logs_ar_review',id,candidate.card.id,false);renderAR(review.evidence,review.comparison,false);});area.append(button);}
  });
  const createLane=document.createElement('button');createLane.type='button';createLane.textContent='Create missing billed-month lane';
  activeForm.elements.destination.closest('label').append(createLane);
  createLane.onclick=()=>run(async()=>{
   const month=activeForm.elements.billed_month.value;
   if(!month){status.textContent='Choose the confirmed billed month first.';return;}
   if(!confirm(`Create the ${month} billed lane on THE LOGS - EMS? This changes Trello but does not post an audit or move any cards.`))return;
   const result=await api('logs_create_month_lane',month,true),select=activeForm.elements.destination;
   if(!Array.from(select.options).some(o=>o.value===result.lane.id)){const option=document.createElement('option');option.value=result.lane.id;option.textContent=result.lane.name;select.append(option);}
   select.value=result.lane.id;status.textContent='Billed-month lane is available. The card has not moved.';
  });
  // Keep the form primary; original evidence is available without competing columns.
  const layout=body.querySelector('.audit-layout'), evidence=layout.querySelector('section');
  const library=document.createElement('details');library.className='audit-library';
  library.innerHTML='<summary>All original comments & checklists</summary>';
  library.append(evidence);layout.append(library);
  const nodes=Array.from(activeForm.children);const heading=nodes.shift();heading.remove();
  const boundaries=[0,nodes.findIndex(n=>n.matches('h4')),nodes.findIndex(n=>n.querySelector('[name=field_notes]')),nodes.findIndex(n=>n.querySelector('[name=billing_evidence]'))];
  const actionBar=nodes.pop();actionBar.classList.add('audit-footer');
  const nav=document.createElement('div');nav.className='audit-tabs';nav.setAttribute('role','tablist');nav.setAttribute('aria-label','Audit sections');
  const titles=['Front & job','Estimating','Field','Billing & finish'];const panels=[];
  for(let i=0;i<titles.length;i++){
   const panel=document.createElement('section');panel.id='audit-panel-'+i;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby','audit-tab-'+i);panel.hidden=i!==0;
   panel.innerHTML='<h3>'+titles[i]+'</h3>';
   for(const n of nodes.slice(boundaries[i],i+1<titles.length?boundaries[i+1]:nodes.length))panel.append(n);
   activeForm.append(panel);panels.push(panel);
   const button=document.createElement('button');button.type='button';button.id='audit-tab-'+i;button.textContent=titles[i];button.setAttribute('role','tab');button.setAttribute('aria-controls',panel.id);button.setAttribute('aria-selected',String(i===0));button.tabIndex=i===0?0:-1;
   button.onclick=()=>{panels.forEach((p,j)=>p.hidden=j!==i);Array.from(nav.children).forEach((b,j)=>{b.setAttribute('aria-selected',String(j===i));b.tabIndex=j===i?0:-1;});dialog.scrollTop=0;};nav.append(button);
  }
  nav.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const buttons=Array.from(nav.children),index=buttons.indexOf(document.activeElement);const next=e.key==='Home'?0:e.key==='End'?3:(index+(e.key==='ArrowRight'?1:3))%4;buttons[next].click();buttons[next].focus();};
  activeForm.prepend(nav);activeForm.append(actionBar);
  for(const [key,s] of Object.entries(suggestions)){
   const input=activeForm.elements[key];if(!input || input.type==='hidden')continue;
   const label=input.closest('label');const badge=document.createElement('small');badge.className='audit-provenance';
   const saved=Object.prototype.hasOwnProperty.call(r.draft?.fields||{},key);
   badge.textContent=s.manual?'Manual check required':s.differs_from_saved?'Source differs from saved finding — review':s.conflict?'Conflicting values — review sources':saved?'Saved entry':s.value!=null?'Suggested from source — confirm':s.sources.length?'Evidence found — needs review':'Not found in source';
   label.append(badge);input.addEventListener('input',()=>{badge.textContent='Edited by you — sources retained';});
   if(saved && s.value!=null && input.value!==s.value){
    const use=document.createElement('button');use.type='button';use.textContent='Use source suggestion';
    use.onclick=()=>{input.value=s.value;input.dispatchEvent(new Event('input',{bubbles:true}));badge.textContent='Source suggestion applied — confirm';use.remove();};label.after(use);
   }
   if(s.sources.length){
    const details=document.createElement('details');details.className='audit-source';
    const summary=document.createElement('summary');summary.textContent=`View sources (${s.sources.length})`;details.append(summary);
    for(const src of s.sources){const h=document.createElement('strong');h.textContent=src.title;const text=document.createElement('pre');text.textContent=src.text;details.append(h,text);}
    const group=document.createElement('div');group.className='audit-field';label.before(group);group.append(label,details);
   }
  }
  const timingDetails=document.createElement('details');timingDetails.className='audit-timing';
  timingDetails.innerHTML='<summary>Initial note timing evidence</summary><div class="review-fields"></div>';
  const timingFields=timingDetails.querySelector('div');
  for(const key of ['inspection_completed_at','initial_note_sent_at','timing_source']){const input=activeForm.elements[key];timingFields.append(input.closest('.audit-field')||input.closest('label'));}
  (activeForm.elements.initial_note.closest('.audit-field')||activeForm.elements.initial_note.closest('label')).after(timingDetails);
  dialog.scrollTop=0;
  const changes=r.changes;
  if(changes){const summary=document.createElement('p');summary.textContent=`Since prior saved review: ${changes.comments.length} new/edited notes${changes.removed_comments?.length?' · '+changes.removed_comments.length+' removed notes':''}${changes.description?' · description changed':''}${changes.checklists?' · checklists changed':''}.`;library.prepend(summary);}
  const newIds=new Set(changes?.comments||[]);
  const notes=()=>{const q=body.querySelector('[data-note-search]').value.toLowerCase();body.querySelector('[data-notes]').innerHTML=ev.comments.filter(a=>a.text.toLowerCase().includes(q)).map(a=>`<details><summary>${newIds.has(a.id)?'New/edited · ':''}${a.date.slice(0,10)>=f.period_start&&a.date.slice(0,10)<=f.period_end?'This period · ':''}${esc(a.date.slice(0,10))} · ${esc(a.author)} · ${esc(a.text.replace(/\s+/g,' ').slice(0,85))}</summary><pre>${esc(a.text)}</pre></details>`).join('')||'<p>No matching notes.</p>';};notes();body.querySelector('[data-note-search]').oninput=notes;
  const days=()=>{for(const p of ['ems','contents']){const a=activeForm.elements[p+'_start'].value,b=activeForm.elements[p+'_billed'].value;body.querySelector('[data-'+p+'-days]').textContent=a&&b?`${Math.round((new Date(b)-new Date(a))/86400000)} days from start to billed`:'Days: unknown — start and billed dates required';}};days();activeForm.addEventListener('input',days);
  const propose=()=>{
   const el=activeForm.elements,scope=el.scope.value;
   let decision='questions';
   if(!el.billing_conflict.value.trim() && el.billing_status.value==='Not billed')decision='hold';
   if(!el.billing_conflict.value.trim() && el.billing_status.value==='Billed'){
    const keys=scope==='EMS'?['ems_billed']:scope==='Contents'?['contents_billed']:scope==='EMS + Contents'?['ems_billed','contents_billed']:['other_billed'];
    const dates=keys.map(k=>el[k].value);
    if(dates.every(Boolean)){decision='billed';el.billed_month.value=dates.sort().at(-1).slice(0,7);}
   }
   el.decision.value=decision;
   const lane=decision==='billed'?r.lanes.find(l=>l.month===el.billed_month.value):decision==='questions'?r.lanes.find(l=>l.name.trim().toUpperCase()==='QUESTIONS'):null;
   el.destination.value=lane?.id||'';
   status.textContent=`Proposed disposition: ${decision==='hold'?'leave in place':decision==='questions'?'Questions':'billed month '+el.billed_month.value}. Review before confirming.`;
  };
  for(const key of ['billing_status','billing_conflict','scope','ems_billed','contents_billed','other_billed'])activeForm.elements[key].addEventListener('change',propose);
  body.querySelector('[data-filing-division]')?.addEventListener('change',event=>{
   activeForm.elements.scope.value=event.target.value;
   for(const key of ['billing_checked','identity_checked','all_confirmed'])activeForm.elements[key].checked=false;
   propose();
  });
  body.querySelector('[data-back]').onclick=()=>{if(!hasUnsavedChanges()||confirm('Return to queue? Unsaved changes will be lost.'))run(showQueue);};
  body.querySelector('[data-open]').onclick=()=>parent.postMessage({type:'linguar-open-job',focus:ev.card.name,cardId:ev.card.id},location.origin);
  savedForm=JSON.stringify(formFields());
  const save=async()=>{const fields=formFields();const saved=await api('logs_save',ev.card.id,ev.revision,fields);selected.draft=saved.draft;savedForm=JSON.stringify(fields);status.textContent='Audit draft saved on this PC. Trello unchanged.';};
  body.querySelector('[data-save]').onclick=()=>run(save);
  body.querySelector('[data-preview]').onclick=()=>run(async()=>{
   if(!filingDivisions.includes(activeForm.elements.scope.value)){
    nav.lastElementChild.click();body.querySelector('[data-filing-division]')?.focus();
    status.textContent='Choose the division for filing before previewing this audit.';return;
   }
   await save();const p=await api('logs_preview',ev.card.id);showPreview(p.operation);
  });
 }
 function showPreview(op){
  operation=op;activeForm=null;
  status.textContent=op.status==='done'?'Publication completed.':op.status==='superseded'?'Replaced by a newly reviewed audit.':`Review before publishing · ${op.status}`;
  body.innerHTML=`<h3>${esc(op.name)} → ${esc(op.destination_name)}</h3><pre>${esc(op.comment)}</pre><p>${op.decision==='hold'?'Posts the audit note and leaves the card in place.':'Posts the audit note, then moves this exact card.'} Payment is recorded separately.</p><div class="actions"><button data-publish class="primary" ${['done','superseded'].includes(op.status)?'disabled':''}>${op.status==='preview'?'Confirm audit & disposition':'Retry / verify publication'}</button>${op.status==='preview'?'<button data-discard>Discard preview</button>':''}<button data-queue>Queue</button></div>`;
  body.querySelector('[data-publish]').onclick=()=>run(async()=>{const r=await api('logs_publish',op.id,true);showPreview(r.operation);});
  body.querySelector('[data-discard]')?.addEventListener('click',()=>run(async()=>{await api('logs_cancel_preview',op.id);await openCard(op.card_id);}));
  body.querySelector('[data-queue]').onclick=()=>run(showQueue);
 }
 function showBatch(ops,failures){
  activeForm=null;status.textContent='Review each note and destination, then select the jobs to confirm. Nothing has been posted.';
  body.innerHTML='<h3>Confirm reviewed jobs</h3><div data-batch-items></div><p data-batch-errors></p><div class="actions"><button data-confirm-batch>Confirm selected</button><button data-discard-batch>Discard unstarted previews</button><button data-queue>Queue</button></div>';
  body.querySelector('[data-batch-items]').innerHTML=ops.map((o,i)=>`<section><label class="audit-check"><input type="checkbox" data-batch-index="${i}" ${o.status==='done'?'disabled':''}>${esc(o.name)} → ${esc(o.destination_name)} · ${esc(o.status)}</label><details><summary>Read proposed audit comment</summary><pre>${esc(o.comment)}</pre></details><p data-result="${i}"></p></section>`).join('')||'<p>No publishable drafts for this period.</p>';
  body.querySelector('[data-batch-errors]').textContent=failures.join(' • ');
  body.querySelector('[data-queue]').onclick=()=>run(showQueue);
  body.querySelector('[data-discard-batch]').onclick=()=>run(async()=>{for(const o of ops)if(o.status==='preview')await api('logs_cancel_preview',o.id);await showQueue();});
  body.querySelector('[data-confirm-batch]').onclick=()=>run(async()=>{
   const selected=Array.from(body.querySelectorAll('[data-batch-index]:checked:not(:disabled)'));
   if(!selected.length){status.textContent='Select at least one reviewed job.';return;}
   for(const input of selected){const i=Number(input.dataset.batchIndex);try{const r=await api('logs_publish',ops[i].id,true);ops[i]=r.operation;input.disabled=true;input.checked=false;body.querySelector(`[data-result="${i}"]`).textContent='Completed';}catch(e){body.querySelector(`[data-result="${i}"]`).textContent=e.message;status.textContent='Batch paused. Completed jobs remain completed; review the failed job before retrying.';return;}}
   status.textContent='Selected audits completed.';
  });
 }
 window.LogsAuditUI={open:async f=>{init();filters=f;dialog.showModal();await run(showQueue);}};
})();
