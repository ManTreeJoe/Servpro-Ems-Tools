/* DEV saved filters layered onto existing boards; no placement mutation methods. */
window.JobViews=(()=>{
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let enabled=false,api,key,views=[],selected='',boards=[];
 const current=()=>views.find(v=>v.id===selected);
 function valid(v){return v&&typeof v.id==='string'&&typeof v.name==='string'&&v.name.length<=60&&['board','all'].includes(v.layout)&&['query','carrier','loss','lane','board'].every(k=>typeof v[k]==='string');}
 async function init(scope,callbacks){
  window.JobsPlanPrototype?.reset();api=callbacks;key='dev-job-views:'+scope;
  try{const saved=await pywebview.api.get_ui_state(key);views=(saved?.views||[]).filter(valid);}catch{views=[];}
  enabled=true;
 }
 function matches(c,lane){
  if(!enabled)return true;const v=current();if(!v)return true;
  return (!v.carrier||c.job_info?.carrier===v.carrier)&&(!v.loss||(c.loss_types||[]).includes(v.loss))&&(!v.lane||lane.list_id===v.lane)&&(!v.query||[c.client,c.name,c.job_info?.claim_number,c.job_info?.address,lane.name].join(' ').toLowerCase().includes(v.query.toLowerCase()));
 }
 function clear(){selected='';}
 function tabs(){return `<button class="board-tab ${selected==='all'?'active':''}" data-saved="all">All Jobs</button>`+boards.map(b=>`<button class="board-tab" data-main="${esc(b.key)}">${esc(b.name)}</button>`).join('');}
 function mount(root,data){
  if(!enabled)return;boards=data;
  const nav=root.querySelector('.board-tabs');if(!nav)return;
  if(!nav.querySelector('[data-saved="all"]'))nav.insertAdjacentHTML('afterbegin',`<button class="board-tab ${selected==='all'?'active':''}" data-saved="all">All Jobs</button>`);
  nav.insertAdjacentHTML('beforeend',views.map(v=>`<button class="board-tab ${selected===v.id?'active':''}" data-saved="${esc(v.id)}" title="Personal saved filters">${esc(v.name)}</button>`).join('')+'<button class="board-tab" data-create-view>＋ My view</button>');
  if(current())nav.querySelectorAll('[data-board-tab]').forEach(b=>b.classList.remove('active'));
  root.querySelectorAll('[data-main]').forEach(el=>el.onclick=()=>{clear();api.choose(el.dataset.main);api.redraw();});
  root.querySelectorAll('[data-saved]').forEach(el=>el.onclick=()=>{selected=el.dataset.saved;const v=current();api.choose(v?.board||boards[0]?.key);api.redraw();});
  root.querySelector('[data-create-view]').onclick=()=>edit();
  const v=current();
  if(v){nav.insertAdjacentHTML('afterend',`<div class="saved-view-tools"><strong>My view · ${esc(v.name)}</strong><small>${esc([v.carrier,v.loss,v.query,v.lane?'Selected lane':''].filter(Boolean).join(' · ')||'No additional filters')} · saved on this PC</small><button class="btn" data-edit-view>Edit filters</button><button class="btn" data-delete-view>Delete view</button></div>`);root.querySelector('[data-edit-view]').onclick=()=>edit(v);root.querySelector('[data-delete-view]').onclick=()=>edit(v,true);}
 }
 function aggregate(root,data){
  if(!enabled)return false;boards=data;const v=current();if(selected!=='all'&&v?.layout!=='all')return false;
  const seen=new Set(),rows=[];const query=api.search().trim().toLowerCase();
  for(const b of boards){if(v?.board&&b.key!==v.board)continue;for(const l of b.lanes||[])for(const c of l.cards||[]){
   if(!matches(c,l)||query&&![c.client,c.name,c.job_info?.address,c.job_info?.claim_number].join(' ').toLowerCase().includes(query))continue;
   const id=JSON.stringify([b.key,c.card_id||c.job_id||c.loss_id,l.list_id]);if(seen.has(id))continue;seen.add(id);rows.push({c,b,l});
  }}
  root.innerHTML=`<div class="board-tabs">${tabs()}</div><div class="saved-view-tools"><strong>${rows.length} loaded placements</strong><small>Linked identities are not merged in this trial. Load Old Jobs from a main board to include history. Save your list settings with ＋ My view.</small></div><div class="jobs-list-prototype"></div>`;
  window.JobsPlanPrototype.render(root.querySelector('.jobs-list-prototype'),rows,{key:selected,name:v?.name,saved:v?.table,open:api.open});
  mount(root,data);return true;
 }
 function edit(v,remove=false){
  const dialog=document.createElement('dialog');dialog.className='saved-view-dialog';
  const initial=v||{name:'',board:'',layout:'all',query:api.search(),carrier:'',loss:'',lane:''};
  const cards=boards.flatMap(b=>(b.lanes||[]).flatMap(l=>l.cards||[]));
  const options=values=>[...new Set(values.filter(Boolean))].sort().map(s=>`<option value="${esc(s)}">${esc(s)}</option>`).join('');
  dialog.innerHTML=remove?`<h2>Delete ${esc(v.name)}?</h2><p>Only your saved filters are removed. Jobs and placements stay unchanged.</p><form><footer><button type="button" class="btn" data-cancel>Cancel</button><button class="btn">Delete my view</button></footer><p role="status"></p></form>`:`<h2>${v?'Edit':'Create'} my view</h2><p>Personal filters, saved for this account and workspace on this PC. Main views are unchanged.</p><form><label>Name<input name="name" required maxlength="60"></label><label>Work queue<select name="board"><option value="">All loaded boards</option>${boards.map(b=>`<option value="${esc(b.key)}">${esc(b.name)}</option>`).join('')}</select></label><label>Layout<select name="layout"><option value="all">All Jobs list</option><option value="board">Existing board lanes</option></select></label><label>Search<input name="query" maxlength="250"></label><label>Carrier<select name="carrier"><option value="">Any carrier</option>${options(cards.map(c=>c.job_info?.carrier))}</select></label><label>Loss type<select name="loss"><option value="">Any loss type</option>${options(cards.flatMap(c=>c.loss_types||[]))}</select></label><label>Lane<select name="lane"></select></label><footer><button type="button" class="btn" data-cancel>Cancel</button><button class="btn btn-primary">Save my view</button></footer><p role="status"></p></form>`;
  document.body.append(dialog);const form=dialog.querySelector('form');
  if(!remove){for(const k of ['name','board','layout','query','carrier','loss'])form.elements[k].value=initial[k];const lanes=()=>{const b=boards.find(b=>b.key===form.elements.board.value);form.elements.lane.innerHTML='<option value="">Any lane</option>'+(b?.lanes||[]).map(l=>`<option value="${esc(l.list_id)}">${esc(l.name)}</option>`).join('');};lanes();form.elements.lane.value=initial.lane;form.elements.board.onchange=lanes;}
  dialog.querySelector('[data-cancel]').onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();
  form.onsubmit=async e=>{e.preventDefault();const status=form.querySelector('[role=status]'),button=form.querySelector('button:not([type=button])');let next;
   if(remove)next=views.filter(x=>x.id!==v.id);else{const item={...Object.fromEntries(new FormData(form)),id:v?.id||crypto.randomUUID(),table:window.JobsPlanPrototype.snapshot()};item.name=item.name.trim();if(!item.name||item.layout==='board'&&!item.board){status.textContent='Choose a name and a work queue for board layout.';return;}next=[...views.filter(x=>x.id!==item.id),item];}
   button.disabled=true;try{const result=await pywebview.api.set_ui_state(key,{views:next});if(!result?.ok)throw Error('Save failed. Your filters are still here.');views=next;selected=remove?'all':next.at(-1).id;api.choose(current()?.board||boards[0]?.key);dialog.close();api.redraw();}catch{status.textContent='Could not save your view. Retry; jobs were not changed.';button.disabled=false;}
  };dialog.showModal();
 }
 return {init,matches,clear,mount,aggregate};
})();
