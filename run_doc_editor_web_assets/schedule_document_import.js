/* Import review owns no persistence. Each selected line goes through the visit editor. */
window.OneLossScheduleDocumentImport=function({read,onSelect,today}){
 const safe=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const dialog=document.createElement('dialog');dialog.id='document-import';dialog.setAttribute('aria-labelledby','document-import-title');
 dialog.innerHTML=`<header><h2 id="document-import-title">Import Run document</h2><button type="button" class="btn" data-close>Close</button></header>
 <p>Read a Word .docx file without changing it. Link each line to a job, review the visit, then Save draft. Existing visits are not overwritten.</p>
 <div class="import-controls"><label>Run date (MM/DD/YY)<input data-day value="${OneLossWeeklyCalendar.displayDate(today)}"></label><button type="button" class="btn btn-primary" data-pick>Choose document</button></div>
 <p data-message role="status"></p><div data-rows></div>`;
 document.body.append(dialog);
 const get=selector=>dialog.querySelector(selector);let preview=null,busy=false;const saved=new Set();
 function render(){
   if(!preview)return;
   const warnings=[];
   if(preview.tables?.length)warnings.push('Tables are shown below for manual review; they are not imported as visits.');
   if(preview.blockers?.includes('tracked_changes_or_textboxes_require_review'))warnings.push('Tracked changes or text boxes need review in the original document.');
   get('[data-message]').textContent=`${preview.source_filename} · ${preview.visits.length} lines · ${preview.visits.filter(r=>saved.has(r.draft_id)).length} saved. ${warnings.join(' ')}`;
   get('[data-rows]').innerHTML=preview.visits.map((row,i)=>`<article class="document-import-row"><div><strong>${safe(preview.section_labels[row.section])}</strong><p>${safe(row.raw_text)}</p><small>${row.skip_reason?safe(row.skip_reason):row.section==='upcoming'?'Choose the upcoming date in the editor':row.proposed_date?OneLossWeeklyCalendar.displayDate(row.proposed_date):'Waiting — no scheduled date'}</small></div><button type="button" class="btn" data-line="${i}" ${row.skip_reason||saved.has(row.draft_id)?'disabled':''}>${saved.has(row.draft_id)?'Saved':'Link job & review'}</button></article>`).join('')||'<p>No recognized Run sections found. Nothing was imported.</p>';
   if(preview.tables?.length)get('[data-rows]').innerHTML+=`<details><summary>Table text — manual review</summary><pre>${safe(preview.tables.map(t=>t.map(r=>r.join(' | ')).join('\n')).join('\n\n'))}</pre></details>`;
 }
 get('[data-pick]').onclick=async()=>{
   let day;try{day=OneLossWeeklyCalendar.parseDate(get('[data-day]').value);}catch{get('[data-message]').textContent='Enter the Run date as MM/DD/YY.';return;}
   busy=true;preview=null;get('[data-rows]').innerHTML='';get('[data-pick]').disabled=true;get('[data-close]').disabled=true;get('[data-message]').textContent='Reading document…';
   try{const result=await read(day);if(!result.canceled){preview=result.preview;render();}else{get('[data-message]').textContent='No document selected.';}}
   catch(error){get('[data-message]').textContent=error.message;}
   finally{busy=false;get('[data-pick]').disabled=false;get('[data-close]').disabled=false;}
 };
 get('[data-close]').onclick=()=>dialog.close();dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
 get('[data-rows]').onclick=event=>{const button=event.target.closest('[data-line]');if(!button)return;const row=preview.visits[Number(button.dataset.line)];dialog.close();onSelect({...row,filename:preview.source_filename});};
 return {open(){render();dialog.showModal();},saved(id){saved.add(id);}};
};
