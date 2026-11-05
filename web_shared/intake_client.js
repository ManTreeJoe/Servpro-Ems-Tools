/* Choose a new client by default; reuse always requires an explicit selection. */
window.IntakeClient={choose(fields){return new Promise(resolve=>{
 const d=document.createElement('dialog');d.className='client-transfer-dialog';d.setAttribute('aria-label','Choose client for new job');
 d.innerHTML=`<form><h2>Client for this job</h2><p>Choose a new client or select an existing client. This loss remains a separate job.</p>
 <div><label><input type="radio" name="client-mode" value="new" checked> Create a new client</label> <label><input type="radio" name="client-mode" value="existing"> Use an existing client</label></div>
 <fieldset data-new><legend>New client details</legend><label>Client / company name<input data-name maxlength="300" required></label><label>Email<input data-email type="email" maxlength="320"></label><label>Phone<input data-phone maxlength="100"></label><label>Address<input data-address maxlength="1000"></label></fieldset>
 <fieldset data-existing hidden><legend>Find an existing client</legend><label>Search clients<input data-search type="search"></label><label>Client<select data-client><option value="">Choose a client</option></select></label></fieldset>
 <p role="status">Checking for existing clients…</p><footer><button type="button" data-cancel>Back</button><button type="submit">Create client and job</button></footer></form>`;
 document.body.append(d);d.showModal();const $=s=>d.querySelector(s),select=$('select'),status=$('[role=status]');let clients=[],ready=false;
 const finish=value=>{d.close();d.remove();resolve(value);};
 $('[data-cancel]').onclick=()=>finish(null);d.addEventListener('cancel',e=>{e.preventDefault();finish(null);});
 $('[data-name]').value=fields.insured_name||fields.name||'';for(const key of ['email','phone','address'])$('[data-'+key+']').value=fields[key]||'';
 function changed(){const isNew=$('[name=client-mode]:checked').value==='new';$('[data-new]').hidden=!isNew;$('[data-existing]').hidden=isNew;$('[data-name]').required=isNew;select.required=!isNew;
  $('button[type=submit]').disabled=!ready||(!isNew&&!select.value);$('button[type=submit]').textContent=isNew?'Create client and job':'Use client and create job';
  const chosen=clients.find(c=>c.client_id===select.value);status.textContent=!ready?'Checking for existing clients…':isNew?'A new client will be created, even if a similar name exists.':chosen?(chosen.match_reasons?.join(' · ')||'Selected manually'):'Select an existing client.';}
 function paint(){const value=select.value,q=$('[data-search]').value.toLowerCase();select.replaceChildren(new Option('Choose a client',''));for(const c of clients.filter(c=>c.display_name.toLowerCase().includes(q)||c.client_id===value))select.add(new Option(c.display_name+(c.match_reasons?.length?' — '+c.match_reasons.join(', '):''),c.client_id));select.value=value;changed();}
 d.querySelectorAll('[name=client-mode]').forEach(r=>r.onchange=changed);select.onchange=changed;$('[data-search]').oninput=paint;
 $('form').onsubmit=e=>{e.preventDefault();if(!ready)return;const isNew=$('[name=client-mode]:checked').value==='new';if(!isNew&&!select.value)return;finish(isNew?{mode:'new',details:{name:$('[data-name]').value.trim(),email:$('[data-email]').value.trim(),phone:$('[data-phone]').value.trim(),address:$('[data-address]').value.trim()}}:{mode:'existing',client_id:select.value});};
 $('button[type=submit]').disabled=true;
 pywebview.api.client_match_options(fields).then(r=>{if(!d.isConnected)return;if(!r?.ok)throw new Error(r?.error||'Clients could not load. Go back and retry.');clients=r.clients||[];ready=true;paint();$('[data-name]').focus();}).catch(e=>{status.textContent=e.message;$('button[type=submit]').disabled=true;select.disabled=true;});
 });}};
