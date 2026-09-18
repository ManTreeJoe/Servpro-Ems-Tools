/* One reviewed row at a time. No Trello writes and no unattended bulk approval. */
(() => {
  'use strict';
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let modal,content,status,batch,index,day,refresh,busy=false,review;
  const call=async(operation,payload={})=>{
    const r=await pywebview.api.paste_review(operation,payload);
    if(!r?.ok)throw Error(r?.error||'The request did not finish.');return r;
  };
  async function run(fn){
    if(busy)return;busy=true;content.inert=true;
    try{await fn();}catch(e){status.textContent=e.message||String(e);}
    finally{busy=false;content.inert=false;}
  }
  function initialize(){
    if(modal)return;
    modal=document.createElement('dialog');modal.className='apa-review';
    modal.setAttribute('aria-labelledby','apa-review-title');
    modal.innerHTML='<header><h2 id="apa-review-title">Paste & reconcile</h2><button type="button" data-close aria-label="Close paste review">Close</button></header><p data-status role="status" aria-live="polite"></p><div data-content></div>';
    document.body.append(modal);content=modal.querySelector('[data-content]');status=modal.querySelector('[data-status]');
    modal.querySelector('[data-close]').onclick=()=>{if(!busy){modal.close();if(refresh)refresh();}};
    modal.addEventListener('cancel',e=>{e.preventDefault();modal.querySelector('[data-close]').click();});
  }
  function inputScreen(recent){
    batch=null;status.textContent=`Working date: ${day}. Queue progress saves on this PC.`;
    content.innerHTML=`${recent?'<button data-resume>Resume last queue for this date</button>':''}<label for="apa-table-paste">Paste the APA Monitor table</label><textarea id="apa-table-paste" rows="9" placeholder="Copy the full table, including job ID, customer, claim, division and requirement."></textarea><div class="review-actions"><button data-start>Review list</button><button data-backup>Back up this month</button></div><p class="review-help">Each match needs confirmation. This does not mark jobs uploaded or audited.</p>`;
    content.querySelector('[data-start]').onclick=()=>run(async()=>{
      batch=(await call('start',{text:content.querySelector('textarea').value,day})).batch;await advance();
    });
    content.querySelector('[data-resume]')?.addEventListener('click',()=>run(async()=>{batch=recent;await advance();}));
    content.querySelector('[data-backup]').onclick=()=>run(async()=>{
      status.textContent='Backing up monthly APA files…';
      const r=await pywebview.api.backup_apa_month(day.slice(0,7));
      if(!r.ok)throw Error(r.error);
      status.textContent=`${r.report.copied} files backed up; ${r.report.unreadable} need review. Local archive: ${r.report.archive}`;
    });
    content.querySelector('textarea').focus();
  }
  async function advance(){
    index=batch.rows.findIndex(r=>r.state==='pending');
    if(index<0){
      status.textContent=`Review complete for ${batch.day}.`;
      const counts={};batch.rows.forEach(r=>counts[r.state]=(counts[r.state]||0)+1);
      content.innerHTML=`<p>${Object.entries(counts).map(([k,v])=>esc(`${v} ${k}`)).join(' · ')}</p><ul>${batch.rows.map(r=>`<li>${esc(r.customer)} · ${esc(r.division)} · ${esc(r.requirement)} — ${esc(r.state)}</li>`).join('')}</ul><button data-new>Paste another list</button>`;
      content.querySelector('[data-new]').onclick=()=>inputScreen(null);if(refresh)await refresh();return;
    }
    // Keep a retry/skip route if a network request fails before any results appear.
    content.innerHTML='<button data-retry>Retry this row</button> <button data-skip>Skip this row</button>';
    content.querySelector('[data-retry]').onclick=()=>run(advance);
    content.querySelector('[data-skip]').onclick=()=>run(()=>commit('skip'));
    status.textContent=`Finding Trello cards for ${batch.rows[index].customer}…`;
    review=await call('inspect',{batch_id:batch.id,index});drawRow();
  }
  function drawRow(){
    const r=review.row;
    status.textContent=`${index+1} of ${batch.rows.length} · APA date ${batch.day}`;
    content.innerHTML=`<h3>${esc(r.customer)}</h3><dl><dt>Claim</dt><dd>${esc(r.claim)}</dd><dt>Division</dt><dd>${esc(r.division)}</dd><dt>Upload requirement</dt><dd>${esc(r.requirement)} upload</dd><dt>Due</dt><dd>${esc(r.due)}</dd></dl>
      <label for="apa-match-search">Find the Trello card</label><div class="review-actions"><input id="apa-match-search" value="${esc(r.customer)}"><button data-search>Search again</button></div>
      <div class="review-matches">${r.candidates.length?r.candidates.map((c,i)=>`<button data-match="${i}">${esc(c.name)}<small>${esc(c.board)} · ${esc(c.list_name)}</small></button>`).join(''):'<p>No matches. Try another name or claim number, or skip this row.</p>'}</div>
      <section data-selected></section>
      ${r.existing.length?`<fieldset><legend>Already on APA</legend>${r.existing.map((e,i)=>`<label class="review-check"><input type="radio" name="existing" value="${i}" ${r.existing.length===1?'checked':''}>${esc(e.text)} — ${esc(e.lane)} (${esc(e.division_hint)})</label>`).join('')}</fieldset>`:''}
      <div class="review-actions"><button data-add disabled>${r.existing.length?'Add separate entry':'Add & next'}</button><button data-existing disabled ${r.existing.length?'':'hidden'}>Confirm existing & next</button><button data-skip>Skip</button><button data-reload>Reload row</button></div>`;
    content.querySelector('[data-reload]').onclick=()=>run(advance);
    content.querySelector('[data-search]').onclick=()=>run(async()=>{
      status.textContent='Searching…';review=await call('inspect',{batch_id:batch.id,index,query:content.querySelector('#apa-match-search').value});drawRow();
    });
    content.querySelectorAll('[data-match]').forEach(b=>b.onclick=()=>run(async()=>{
      const card=r.candidates[Number(b.dataset.match)];status.textContent='Loading selected card…';
      const selected=(await call('choose',{batch_id:batch.id,index,card_id:card.card_id})).selection;
      r.selection=selected;drawSelection(selected);
      status.textContent=`${index+1} of ${batch.rows.length} · APA date ${batch.day}`;
    }));
    content.querySelector('[data-add]').onclick=()=>run(()=>commit('add'));
    content.querySelector('[data-existing]').onclick=()=>run(()=>commit('existing'));
    content.querySelector('[data-skip]').onclick=()=>run(()=>commit('skip'));
  }
  function drawSelection(s){
    const fixed=review.row.requirement==='initial'||review.row.division==='contents';
    const area=content.querySelector('[data-selected]');
    area.innerHTML=`<h4>Selected: ${esc(s.name)}</h4><p>${esc(s.board)} · ${esc(s.trello_lane)}</p><details><summary>View Trello description to verify the claim</summary><pre>${esc(s.description||'No description')}</pre></details>
      <label for="apa-review-lane">APA lane</label><select id="apa-review-lane" ${fixed?'disabled':''}><option value="">Choose a lane</option>${review.lanes.map(l=>`<option value="${esc(l)}" ${l===s.lane?'selected':''}>${esc(l)}</option>`).join('')}</select>
      <label for="apa-review-sub">Sub</label><input id="apa-review-sub" value="${esc(s.sub)}" ${fixed?'readonly':''}>
      <p>${review.row.division==='contents'?'Contents tag will be included. ':''}New entries start pending.</p>`;
    content.querySelector('[data-add]').disabled=!review.lanes.includes(s.lane)&&fixed;
    content.querySelector('[data-existing]').disabled=!review.row.existing.length;
  }
  async function commit(action){
    const selected=content.querySelector('[name=existing]:checked');
    if(action==='existing'&&!selected)throw Error('Select the existing entry you reviewed.');
    const r=await call('commit',{batch_id:batch.id,index,action,confirmed:true,
      lane:content.querySelector('#apa-review-lane')?.value||'',sub:content.querySelector('#apa-review-sub')?.value||'',
      existing_index:selected?Number(selected.value):null,distinct:action==='add'&&review.row.existing.length>0});
    batch=r.batch;await advance();
  }
  window.ApaPasteReview={open:async(selectedDay,onRefresh)=>{
    initialize();day=selectedDay;refresh=onRefresh;modal.showModal();
    await run(async()=>inputScreen((await call('recent',{day})).batch));
  }};
})();
