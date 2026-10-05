/* Read-only Run observations, isolated from live drafts. Only job links can change. */
window.OneLossScheduleHistory=function(live){
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const display=OneLossWeeklyCalendar.displayDate;
 const panel=document.createElement('dialog');panel.id='run-history';panel.setAttribute('aria-label','Run history');
 panel.innerHTML=`<header><h2>Run history</h2><button class="btn" data-close>Close history</button></header><p>Read-only daily records, including waiting work. These Runs do not prove work was completed.</p><div class="history-range"><label>From (MM/DD/YY)<input data-start value="07/01/26"></label><label>Through (MM/DD/YY)<input data-end></label><button class="btn" data-load>Load history</button></div><p data-status role="status"></p><div data-calendar></div>`;
 document.body.append(panel);
 const detail=document.createElement('dialog');detail.id='history-document';detail.setAttribute('aria-label','Historical Run');
 detail.innerHTML='<header><h2>Historical Run</h2><button class="btn" data-close>Back to history</button></header><p data-status role="status"></p><div data-body></div>';document.body.append(detail);
 const link=document.createElement('dialog');link.id='history-link';link.setAttribute('aria-label','Correct history job link');
 link.innerHTML='<h2>Correct job link</h2><p data-raw></p><label>Find a job<input type="search" data-search placeholder="Job name or address"></label><div data-results></div><p data-message role="status"></p><footer><button class="btn" data-unlink>Remove link</button><button class="btn" data-close>Cancel</button></footer>';document.body.append(link);
 const get=(root,key)=>root.querySelector(`[data-${key}]`);
 let calendar,docs=[],entries=[],activeDoc,activeRow,sequence=0,busy=false;
 [panel,detail,link].forEach(dialog=>get(dialog,'close').onclick=()=>{if(!busy)dialog.close();});
 link.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
 function sourceRows(){
  const groups=[...new Set(entries.map(r=>r.section))];
  get(detail,'body').innerHTML=`<article class="run-paper"><header><h2>Servpro Daily Run · ${display(activeDoc.run_date)}</h2></header><p>${esc(activeDoc.filename)} · Read only</p>${groups.map(section=>`<section><h4>${esc(section)}</h4><ol>${entries.filter(r=>r.section===section).map(r=>`<li><div class="history-line">${r.struck?'<s>':''}${esc(r.raw_text)}${r.struck?'</s> <small>(Crossed out in source)</small>':''}</div><button type="button" class="history-link" data-link="${esc(r.id)}">${r.job_id?'Linked: '+esc(r.jobs?.display_name||'Job'):'Not linked'} · Correct link</button></li>`).join('')}</ol></section>`).join('')}</article>`;
 }
 async function openDocument(id){
  activeDoc=docs.find(d=>d.id===id);if(!activeDoc)return;
  detail.showModal();get(detail,'body').replaceChildren();get(detail,'status').textContent='Loading Run…';
  try{entries=(await live.historyRows(id)).rows;sourceRows();get(detail,'status').textContent=entries.length?`${entries.length} source lines. Source text cannot be edited.`:'No source lines in this document.';}
  catch(e){get(detail,'status').textContent=e.message+' Close and reopen to retry.';}
 }
 get(detail,'body').onclick=e=>{
  const button=e.target.closest('[data-link]');if(!button)return;
  activeRow=entries.find(r=>r.id===button.dataset.link);sequence++;
  get(link,'raw').textContent=activeRow.raw_text;get(link,'search').value='';get(link,'results').replaceChildren();get(link,'message').textContent='Only the job link changes; the historical Run stays unchanged.';link.showModal();get(link,'search').focus();
 };
 async function saveLink(job){
  if(busy)return;busy=true;sequence++;
  link.querySelectorAll('button,input').forEach(el=>el.disabled=true);get(link,'message').textContent='Saving link…';
  try{const result=await live.historyLink(activeRow,job?.id||null);activeRow.job_id=job?.id||null;activeRow.jobs=job?{display_name:job.title}:null;activeRow.revision=result.revision;sourceRows();link.close();}
  catch(e){get(link,'message').textContent=e.message;}
  finally{busy=false;link.querySelectorAll('button,input').forEach(el=>el.disabled=false);}
 }
 get(link,'unlink').onclick=()=>saveLink(null);
 get(link,'search').oninput=async()=>{
  const q=get(link,'search').value.trim(),version=++sequence;get(link,'results').replaceChildren();if(q.length<2)return;
  get(link,'message').textContent='Searching…';
  try{const jobs=await live.search(q);if(version!==sequence||!link.open)return;
   get(link,'message').textContent=jobs.length?'Select the correct job.':'No matching jobs.';
   get(link,'results').replaceChildren(...jobs.map(job=>{const b=document.createElement('button');b.className='btn';b.textContent=job.title+' · '+(job.address||'');b.onclick=()=>saveLink(job);return b;}));
  }catch(e){if(version===sequence)get(link,'message').textContent=e.message;}
 };
 async function load(){
  get(panel,'load').disabled=true;get(panel,'status').textContent='Loading history…';calendar?.destroy();get(panel,'calendar').replaceChildren();
  try{
   const start=OneLossWeeklyCalendar.parseDate(get(panel,'start').value),end=OneLossWeeklyCalendar.parseDate(get(panel,'end').value);
   docs=(await live.history(start,end)).documents;
   get(panel,'status').textContent=`${docs.length} Run documents. Select a Run to see all its sections and correct job links. Multiple versions remain separate.`;
   calendar=OneLossWeeklyCalendar.mount(get(panel,'calendar'),{date:docs[0]?.run_date||end,archive:true,onEdit:openDocument,
    renderLegacy:({selected,records})=>`<article class="run-paper"><h2>Runs for ${display(selected)}</h2>${records.filter(r=>r.date===selected).map(r=>`<p><button class="btn" data-edit="${esc(r.id)}">Open ${esc(r.title)}</button></p>`).join('')||'<p>No imported Run for this day.</p>'}</article>`});
   calendar.update({records:docs.map(d=>({id:d.id,date:d.run_date,queue:'scheduled',title:d.filename,activities:[{label:'Read-only Run',people:[]}]}))});
  }catch(e){get(panel,'status').textContent=e.message+' Use Load history to retry.';}
  finally{get(panel,'load').disabled=false;}
 }
 get(panel,'load').onclick=load;
 return {open(){const now=new Date();const iso=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;get(panel,'end').value=display(iso);panel.showModal();load();}};
};
