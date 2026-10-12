/* Task summaries first; exact-card evidence is a read-only drilldown. */
window.AuditTimingDashboard=(()=>{
 let data=null,generation=0,selected=null,responseSummary='';
 const host=()=>document.querySelector('#audit-timing');
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const duration=(n,precision)=>n==null?'Not recorded':precision==='date'?`${n/1440} calendar days`:window.AuditFieldControls.elapsed(n);
 const titles={field:'Field note posting',coordinator:'Coordinator response',ems_work:'EMS work',contents_work:'Contents work',ems_billing:'EMS billing',contents_billing:'Contents billing'};
 const stamp=v=>v?window.AuditFieldControls.stamp(v):'Not recorded';
 titles.contact='Contact insured';titles.arrival='On-site arrival';
 const outcome=(c,id)=>c.outcomes?.[id]||(id==='coordinator'?c.response:'unknown');
 function selectTask(id){
  const m=data.metrics.find(m=>m.id===id);if(!m)return;
  selected=id;
  const panel=host().querySelector('.audit-time-response');
  panel.setAttribute('aria-label',`${titles[id]||m.label} summary`);
  if(m.target_minutes!=null){
   const counts=m.outcomes,known=counts.on_time+counts.late,total=known+counts.unknown,target=duration(m.target_minutes,'timestamp');
   panel.innerHTML=`<h3>${esc(titles[id]||m.label)}</h3><p>${esc(m.label)}</p><div class="audit-time-rate"><strong>${known?`${counts.on_time} of ${known}`:'—'}</strong><span>within ${esc(target)}<br><small>${known?`${Math.round(counts.on_time/known*100)}% of recorded timings`:'No recorded timings yet'}</small></span></div><div class="audit-time-stack" role="img" aria-label="${counts.on_time} within target, ${counts.late} late, ${counts.unknown} unknown">${['on_time','late','unknown'].map(k=>`<i class="${k}" style="width:${total?counts[k]/total*100:0}%"></i>`).join('')}</div><div class="audit-task-outcomes">${[['on_time',`Within ${target}`],['late',`Over ${target}`],['unknown','Missing / invalid times']].map(([k,label])=>`<button data-task-outcome="${k}"><span><i class="${k}"></i>${esc(label)}</span><strong>${counts[k]} →</strong></button>`).join('')}</div><p>Typical duration: ${esc(duration(m.median,m.precision))}</p><p>The clock runs from ${esc(m.label)}. Missing or invalid timestamps are excluded from the target percentage.</p>`;
  }else if(id==='coordinator')panel.innerHTML=responseSummary;
  else{
   const total=m.known+m.unknown,percent=total?Math.round(m.known/total*100):0;
   panel.innerHTML=`<h3>${esc(titles[id]||m.label)}</h3><p>${esc(m.label)}</p>
    <div class="audit-time-rate"><strong>${m.known} of ${total}</strong><span>with recorded timing<br><small>${total?`${percent}% of cards`:'No cards yet'}</small></span></div>
    <div class="audit-time-stack" role="img" aria-label="${m.known} recorded, ${m.unknown} missing or not applicable"><i class="recorded" style="width:${total?m.known/total*100:0}%"></i><i class="unknown" style="width:${total?m.unknown/total*100:0}%"></i></div>
    <div class="audit-task-outcomes"><button data-task-outcome="recorded"><span><i class="recorded"></i>Recorded timings</span><strong>${m.known} →</strong></button><button data-task-outcome="unknown"><span><i class="unknown"></i>Missing / invalid or N/A</span><strong>${m.unknown} →</strong></button></div>
    <p class="audit-selected-median">Typical duration: ${esc(duration(m.median,m.precision))}</p><p>Median of ${m.known} recorded timings. Missing dates are not counted as zero. No performance target set.</p><p>Select a count to review the jobs and linked dates.</p>`;
  }
  panel.scrollTop=0;
  panel.querySelectorAll('[data-task-outcome]').forEach(b=>b.onclick=()=>breakdown(id,b.dataset.taskOutcome));
  host().querySelectorAll('[data-timing-task]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.timingTask===id)));
 }
 function breakdown(id,initial='recorded'){
  const m=data.metrics.find(m=>m.id===id);if(!m)return;
  const dialog=document.createElement('dialog');dialog.className='audit-task-dialog';dialog.setAttribute('aria-label',`${titles[id]||m.label} breakdown`);
  dialog.innerHTML=`<div class="section-head"><div><h2>${esc(titles[id]||m.label)}</h2><p>${esc(m.label)} · Pacific time</p></div><button data-close aria-label="Close breakdown">×</button></div><p>${m.known} recorded · ${m.unknown} missing / invalid or not applicable. ${id==='coordinator'?'Target: within 1 hour after the field note is posted.':'No performance target set.'}</p><div class="audit-task-filters"><label>Show<select data-task-filter><option value="recorded">Recorded timings</option><option value="unknown">Missing / invalid</option><option value="all">All cards</option>${id==='coordinator'?'<option value="on_time">Within 1 hour</option><option value="late">Over 1 hour</option>':''}</select></label><label>Find a card<input type="search" data-task-query placeholder="Name or card ID"></label></div><div data-task-results></div>`;
  const filter=dialog.querySelector('select'),query=dialog.querySelector('input');filter.value=initial;
  if(m.target_minutes!=null){
   const target=duration(m.target_minutes,'timestamp');
   dialog.querySelector('.section-head+p').textContent=`${m.known} recorded · ${m.unknown} missing / invalid or not applicable. Target: within ${target}. Clock: ${m.label}.`;
   for(const [value,label] of [['on_time',`Within ${target}`],['late',`Over ${target}`]]){
    const old=filter.querySelector(`option[value="${value}"]`);if(old)old.textContent=label;else filter.add(new Option(label,value));
   }
   filter.value=initial;
  }
  function render(){
   const rows=data.cards.filter(c=>{const n=c.values[id];return (filter.value==='all'||filter.value==='recorded'&&n!=null||filter.value==='unknown'&&n==null||['on_time','late'].includes(filter.value)&&outcome(c,id)===filter.value)&&`${c.name} ${c.id}`.toLowerCase().includes(query.value.toLowerCase());}).sort((a,b)=>(b.values[id]??-1)-(a.values[id]??-1)||a.name.localeCompare(b.name));
   const [startLabel,endLabel]=m.label.split(' → ');
   dialog.querySelector('[data-task-results]').innerHTML=`<p role="status">${rows.length} cards</p><div class="audit-task-cards">${rows.map(c=>{
    const e=c.endpoints?.[id]||{},n=c.values[id];
    return `<article><div class="section-head"><button class="job-link" data-timing-card="${esc(c.id)}">${esc(c.name)} ↗</button><strong>${esc(duration(n,m.precision))}</strong></div><dl><div><dt>${esc(startLabel)}</dt><dd>${esc(stamp(e.start))}</dd></div><div><dt>${esc(endLabel)}</dt><dd>${esc(stamp(e.end))}</dd></div></dl><small>${n==null?'Not counted: one or both dates are missing, invalid, reversed, or not applicable.':id==='coordinator'?(c.response==='late'?'Over 1 hour':'Within 1 hour'):'Recorded duration · no target set'}</small></article>`;
   }).join('')||'<p>No cards in this breakdown.</p>'}</div>`;
   if(m.target_minutes!=null)dialog.querySelectorAll('.audit-task-cards article').forEach((article,i)=>{
    const c=rows[i];article.querySelector('small').textContent=c.values[id]==null?'Not counted: missing, invalid, reversed, or not applicable.':`${outcome(c,id)==='late'?'Over':'Within'} ${duration(m.target_minutes,'timestamp')}`;
   });
   dialog.querySelectorAll('[data-timing-card]').forEach(b=>b.onclick=()=>{
    const card=data.cards.find(c=>c.id===b.dataset.timingCard);
    dialog.close();parent.postMessage({type:'linguar-open-job',cardId:card.id,focus:card.name},location.origin);
   });
  }
  filter.onchange=render;query.oninput=render;
  dialog.querySelector('[data-close]').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>dialog.remove());host().append(dialog);render();dialog.showModal();
 }
 function paint(){
  const root=host();if(!root||!data)return;
  const counts=data.response,known=counts.on_time+counts.late,max=Math.max(1,...data.metrics.map(m=>m.median||0));
  root.innerHTML=`<div class="section-head"><div><h2>Timing by task</h2><p>${esc(data.location)} · All dates · ${data.total} cards with shared audit records or linked comments</p></div><button data-timing-refresh>Refresh timing</button></div>
   <div class="audit-time-grid">
    <section class="audit-time-response" aria-label="Coordinator response timing"><h3>Coordinator response target</h3><p>Field note posted → coordinator note sent</p>
     <div class="audit-time-rate"><strong>${known?`${counts.on_time} of ${known}`:'—'}</strong><span>within 1 hour<br><small>${known?`${Math.round(counts.on_time/known*100)}% of recorded responses`:'No recorded responses yet'}</small></span></div>
     <div class="audit-time-stack" role="img" aria-label="${counts.on_time} within one hour, ${counts.late} over one hour, ${counts.unknown} unknown">${['on_time','late','unknown'].map(k=>`<i class="${k}" style="width:${data.total?counts[k]/data.total*100:0}%"></i>`).join('')}</div>
     <div class="audit-task-outcomes">${[['on_time','Within 1 hour'],['late','Over 1 hour'],['unknown','Missing / invalid times']].map(([k,label])=>`<button data-task-outcome="${k}"><span><i class="${k}"></i>${label}</span><strong>${counts[k]} →</strong></button>`).join('')}</div>
     <p>${known?`${counts.on_time} within target ÷ ${known} recorded responses. `:''}${counts.unknown} missing / invalid times are excluded from the percentage.</p><p>The clock starts when the field note is posted, not when the inspection happens. Select a breakdown to check the linked dates.</p>
    </section>
    <section class="audit-time-comparison" aria-label="Task duration comparison"><div class="section-head"><h3>Typical duration by task</h3><small>Median · click a task for cards</small></div><div class="audit-time-bars">${data.metrics.map(m=>`<button class="audit-time-row audit-task-row" data-timing-task="${m.id}"><span><b>${esc(titles[m.id]||m.label)}</b><small>${esc(m.label)}</small></span><span class="audit-time-track" aria-hidden="true"><i class="recorded" style="width:${(m.median||0)/max*100}%"></i></span><strong>${esc(duration(m.median,m.precision))}</strong><small>${m.known} recorded · ${m.unknown} unknown / N/A</small></button>`).join('')}</div><small>Common scale from 0 · median of recorded durations, not total time. Work and billing use calendar dates; note timings use exact elapsed time.</small></section>
   </div><p class="audit-time-footnote">Latest saved facts per card, including unreviewed drafts. Linked corrections take precedence. Missing dates are not zero. Task samples may overlap and are not unique losses. Independent of the board filters below.</p>`;
  root.querySelector('[data-timing-refresh]').onclick=load;
  const panel=root.querySelector('.audit-time-response');
  responseSummary=panel.innerHTML;
  panel.setAttribute('aria-label','Selected task details');
  panel.innerHTML='<h3>Explore a task</h3><p>Select a stage on the right to see its typical duration, related jobs, and available performance targets here.</p><p>All stages stay visible while you review.</p>';
  root.querySelector('.audit-time-comparison .section-head small').textContent='Median · select a task to review on the left';
  root.querySelectorAll('[data-timing-task]').forEach(b=>b.onclick=()=>selectTask(b.dataset.timingTask));
  if(selected)selectTask(selected);
 }
 async function load(){
  const token=++generation,root=host();if(!root)return;
  data=null;root.setAttribute('aria-busy','true');
  root.innerHTML='<h2>Timing by task</h2><p role="status">Loading shared timing…</p><div class="audit-time-skeleton" aria-hidden="true"></div>';
  let timer;
  try{
   const result=await Promise.race([pywebview.api.load_audit_timing(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Shared timing is taking too long. Retry when your connection recovers.')),30000);})]);
   if(token!==generation)return;if(!result.ok)throw Error(result.error);data=result;paint();
  }catch(e){if(token!==generation)return;root.innerHTML=`<h2>Timing by task</h2><p role="alert">${esc(e.message||'Shared timing could not load.')}</p><button data-timing-retry>Retry timing</button>`;root.querySelector('button').onclick=load;
  }finally{clearTimeout(timer);if(token===generation)root.removeAttribute('aria-busy');}
 }
 return {load,cancel(){generation++;host()?.querySelector('dialog')?.close();}};
})();
