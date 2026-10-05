/* One bulk import confirmation; corrections happen on calendar entries afterward. */
window.OneLossScheduleDocumentImport=function({read,apply,onImported,today}){
 const safe=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const dialog=document.createElement('dialog');dialog.id='document-import';dialog.setAttribute('aria-labelledby','document-import-title');
 dialog.innerHTML=`<header><h2 id="document-import-title">Import Run document</h2><button type="button" class="btn" data-close>Close</button></header>
 <p>Import the entire Run. Strong matches link automatically; unmatched lines remain visible with Needs link. You can edit or correct links afterward. The original document and Trello cards are not changed.</p>
 <div class="import-controls"><label>Run date (MM/DD/YY)<input data-day value="${OneLossWeeklyCalendar.displayDate(today)}"></label><button type="button" class="btn btn-primary" data-pick>Choose document</button></div>
 <p data-message role="status"></p><button type="button" class="btn btn-primary" data-import-all hidden>Import all</button><div data-rows></div>`;
 document.body.append(dialog);
 const get=selector=>dialog.querySelector(selector);let preview=null,busy=false;
 function render(){
   if(!preview)return;
   const warnings=[];
   if(preview.tables?.length)warnings.push('Tables are shown below for manual review; they are not imported as visits.');
   if(preview.blockers?.includes('tracked_changes_or_textboxes_require_review'))warnings.push('Tracked changes or text boxes need review in the original document.');
   const entries=preview.bulk_entries||[],linked=entries.filter(c=>c.visit.job_id).length;
   get('[data-message]').textContent=`${preview.source_filename} · ${entries.length} entries · ${linked} automatic matches · ${entries.length-linked} need links · ${(preview.skipped||[]).length} crossed-out lines skipped. ${warnings.join(' ')}`;
   get('[data-import-all]').hidden=!entries.length;get('[data-import-all]').disabled=false;
   get('[data-rows]').innerHTML=entries.map(row=>`<article class="document-import-row"><div><strong>${safe(row.entry_title)}</strong><p>${safe(row.visit.notes)}</p><small>${safe(row.visit.group)} · ${row.visit.date?OneLossWeeklyCalendar.displayDate(row.visit.date):'Undated'} ${safe(row.review_note)}</small></div><span>${row.visit.job_id?'Auto-linked':'Needs link'}</span></article>`).join('')||'<p>No active Run lines to import.</p>';
   if(preview.tables?.length)get('[data-rows]').innerHTML+=`<details><summary>Table text — manual review</summary><pre>${safe(preview.tables.map(t=>t.map(r=>r.join(' | ')).join('\n')).join('\n\n'))}</pre></details>`;
 }
 get('[data-pick]').onclick=async()=>{
   let day;try{day=OneLossWeeklyCalendar.parseDate(get('[data-day]').value);}catch{get('[data-message]').textContent='Enter the Run date as MM/DD/YY.';return;}
   busy=true;preview=null;get('[data-import-all]').hidden=true;get('[data-rows]').innerHTML='';get('[data-pick]').disabled=true;get('[data-close]').disabled=true;get('[data-message]').textContent='Reading document and matching jobs…';
   try{const result=await read(day);if(!result.canceled){preview=result.preview;render();}else{get('[data-message]').textContent='No document selected.';}}
   catch(error){get('[data-message]').textContent=error.message;}
   finally{busy=false;get('[data-pick]').disabled=false;get('[data-close]').disabled=false;}
 };
 get('[data-close]').onclick=()=>dialog.close();dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
 get('[data-import-all]').onclick=async()=>{
   if(busy||!preview)return;busy=true;[...dialog.querySelectorAll('button,input')].forEach(b=>b.disabled=true);get('[data-message]').textContent='Importing all entries…';
   try{const result=await apply(preview.import_key);get('[data-message]').textContent=`Imported ${result.result.added} entries · ${result.result.needs_link} need links · ${result.result.already_imported} already imported. Open any calendar entry to edit it or change its link.`;get('[data-import-all]').hidden=true;await onImported();}
   catch(error){get('[data-message]').textContent=error.message+' You can retry this import safely.';}
   finally{busy=false;[...dialog.querySelectorAll('button,input')].forEach(b=>b.disabled=false);}
 };
 return {open(){render();dialog.showModal();}};
};
