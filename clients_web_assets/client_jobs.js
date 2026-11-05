/* Explicit client creation and multi-job assignment; no folder/name inference. */
window.ClientJobs = (()=>{
 function dialog(title){
  const previous=document.activeElement, el=document.createElement('dialog');
  el.className='client-transfer-dialog client-jobs-dialog';el.setAttribute('aria-label',title);
  const heading=document.createElement('h2');heading.textContent=title;el.append(heading);
  document.body.append(el);el.showModal();
  let busy=false;
  const close=()=>{if(busy)return;el.close();el.remove();if(previous?.isConnected)previous.focus();};
  el.addEventListener('cancel',e=>{e.preventDefault();close();});
  return {el,close,lock(value){busy=value;el.querySelectorAll('button,input').forEach(c=>c.disabled=value);}};
 }
 async function create(done){
  const d=dialog('New client');
  d.el.insertAdjacentHTML('beforeend','<form><label>Client or company name<input name="name" maxlength="300" required autocomplete="organization"></label><p>Creates an account in your current office. You can link its existing jobs next. A matching saved client will be reused.</p><p role="status"></p><footer><button type="button" data-cancel>Cancel</button><button type="submit">Create client</button></footer></form>');
  d.el.querySelector('[data-cancel]').onclick=d.close;const input=d.el.querySelector('input'),status=d.el.querySelector('[role=status]');input.focus();
  d.el.querySelector('form').onsubmit=async e=>{
   e.preventDefault();if(!input.value.trim())return;d.lock(true);status.textContent='Creating client…';
   try{const r=await pywebview.api.create_directory_client(input.value);if(!r?.ok)throw new Error(r?.error||'Creation not confirmed. Reopen the directory to check.');d.lock(false);d.close();await done(r.client);}
   catch(error){status.textContent=error.message;d.lock(false);}
  };
 }
 async function link(client,done){
  const d=dialog('Link jobs to '+client.name), selected=new Map();let jobs=[],blocked=false;
  d.el.insertAdjacentHTML('beforeend','<p>Search all saved jobs in this office, including older jobs. Linking changes only the client relationship—not the cards, files or job history.</p><label>Find jobs<input type="search" placeholder="Name, address, or date"></label><div class="client-job-results"></div><p data-count>0 selected</p><p role="status">Loading jobs…</p><footer><button type="button" data-cancel>Cancel</button><button type="button" data-link disabled>Link selected jobs</button></footer>');
  const $=s=>d.el.querySelector(s), status=$('[role=status]'), results=$('.client-job-results'), save=$('[data-link]');
  $('[data-cancel]').onclick=()=>{d.close();done();};const input=$('input');input.disabled=true;
  function paint(){
   const query=input.value.trim().toLowerCase();results.replaceChildren();
   const matches=jobs.filter(j=>[j.display_name,j.address,j.date_of_loss,j.date_received,j.current_client].join(' ').toLowerCase().includes(query));
   for(const job of matches){
    const row=document.createElement('label');row.className='client-job-choice';
    const check=document.createElement('input');check.type='checkbox';check.checked=selected.has(job.job_id);check.disabled=blocked||job.client_id===client.client_id;
    const text=document.createElement('span'),name=document.createElement('strong'),meta=document.createElement('small');name.textContent=job.display_name;
    meta.textContent=[job.date_of_loss||job.date_received,job.address,job.lifecycle_stage||job.status||'Status not saved',job.client_id===client.client_id?'Already linked':job.client_id?'Transfer from: '+job.current_client:'Not linked'].filter(Boolean).join(' · ');
    text.append(name,meta);row.append(check,text);results.append(row);
    check.onchange=()=>{check.checked?selected.set(job.job_id,job):selected.delete(job.job_id);counts();};
   }
   if(!matches.length)results.textContent='No matching saved jobs.';counts();
  }
  function counts(){const moved=[...selected.values()].filter(j=>j.client_id).length;$('[data-count]').textContent=`${selected.size} selected${moved?' · '+moved+' will transfer from another client':''}`;save.disabled=blocked||!selected.size||selected.size>100;}
  input.oninput=paint;
  save.onclick=async()=>{
   if(save.disabled)return;
   const moving=[...selected.values()].filter(j=>j.client_id);
   if(moving.length&&!window.confirm(`Transfer ${moving.length} selected job(s) from their current clients to ${client.name}?`))return;
   d.lock(true);status.textContent='Linking selected jobs…';
   try{
    const r=await pywebview.api.link_client_jobs(client.client_id,[...selected.values()].map(j=>({job_id:j.job_id,client_revision:j.client_revision})));
    if(!r?.ok){blocked=true;status.textContent=`${r?.linked?.length||0} job(s) confirmed linked. ${r?.error||'Result not confirmed. Close and reopen before retrying.'}`;d.lock(false);paint();return;}
    d.lock(false);d.close();await done();
   }catch(_){blocked=true;d.lock(false);paint();status.textContent='Could not confirm the result. Close and reopen to review before retrying.';}
  };
  try{const r=await pywebview.api.client_job_candidates(client.client_id);if(!r?.ok)throw new Error(r?.error||'Jobs unavailable. Close and try again.');if(!d.el.isConnected)return;jobs=r.jobs;input.disabled=false;status.textContent='Choose up to 100 jobs per batch.';paint();input.focus();}
  catch(error){status.textContent=error.message;}
 }
 return {create,link};
})();
