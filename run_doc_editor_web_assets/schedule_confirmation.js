/* Review a complete day, never the currently filtered subset of the calendar. */
window.OneLossScheduleConfirmation=function({live,onConfirmed}){
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const dialog=document.createElement('dialog');dialog.className='schedule-confirmation';
 dialog.setAttribute('aria-labelledby','confirmation-title');document.body.append(dialog);
 let review=null,day='',busy=false,version=0,pending=null,opener=null;
 const message=(text,error=false)=>{const el=dialog.querySelector('[data-message]');el.textContent=text;el.setAttribute('role',error?'alert':'status');};
 function lock(value){busy=value;dialog.querySelectorAll('button,select,input').forEach(el=>el.disabled=value);}
 function frame(){dialog.innerHTML=`<header><h2 id="confirmation-title">Confirm ${esc(OneLossWeeklyCalendar.displayDate(day))}</h2><p>Review scheduled visits for this day. Waiting work is not included. Nothing is posted to comments.</p></header><div data-entries></div><p data-message role="status"></p><footer><button class="btn" data-close>Cancel</button><button class="btn" data-reload>Reload review</button><button class="btn btn-primary" data-confirm>Confirm day</button></footer>`;}
 function selectCard(index,cid,initial=false){
  const entry=review.entries[index],card=entry.cards.find(c=>c.card_id===cid),row=dialog.querySelector(`[data-index="${index}"]`);
  row.querySelector('[data-current]').textContent=card?`${card.board_name} → ${card.lane_name}`:'Placement unchanged';
  const select=row.querySelector('[data-lane]');
  select.innerHTML='<option value="">Keep current placement</option>'+(card?card.lanes.filter(l=>l.id!==card.list_id).map(l=>`<option value="${esc(l.id)}">${esc(l.name)}</option>`).join(''):'');
  select.disabled=!card;
  select.value=initial&&!entry.confirmed&&card?.suggested_list!==card?.list_id?(card?.suggested_list||''):'';
 }
 function render(){
  dialog.querySelector('[data-entries]').innerHTML=review.entries.length?review.entries.map((e,i)=>`<section class="confirmation-row" data-index="${i}"><h3>${esc(e.title)} <small>${e.confirmed?'Confirmed':'Draft'}</small></h3><p>${esc(e.group)} · ${esc(e.activities.map(a=>a.label).join(', '))}</p>${e.note?`<p class="confirmation-note">${esc(e.note)}</p>`:''}<div class="confirmation-fields"><label>Linked card<select data-card>${e.cards.length!==1?'<option value="">Keep placement — no card selected</option>':''}${e.cards.map(c=>`<option value="${esc(c.card_id)}">${esc(c.board_name)} · ${esc(c.title||e.title)} · ${esc(c.card_id.slice(-6))}</option>`).join('')}</select></label><div><span>Current lane</span><p data-current></p></div><label>Proposed lane<select data-lane></select></label></div></section>`).join(''):'<p>No scheduled visits for this day. Choose another day on the calendar.</p>';
  review.entries.forEach((e,i)=>selectCard(i,e.cards.length===1?e.cards[0].card_id:'',true));
  dialog.querySelector('[data-confirm]').disabled=!review.entries.length;
  message(review.entries.length?`${review.entries.length} visits · Review every proposed move. Estimating masters and Recon are not moved here.`:'');
 }
 async function load(){
  const request=++version;review=null;pending=null;frame();lock(true);message('Loading day and card locations…');
  try{const response=await live.confirmationPreview(day);if(request!==version)return;review=response.review;lock(false);render();}
  catch(error){if(request!==version)return;lock(false);dialog.querySelector('[data-confirm]').disabled=true;message(error.message,true);}
 }
 function command(){return {contract_version:1,department:review.department,date:review.date,entries:review.entries.map((e,i)=>{
  const row=dialog.querySelector(`[data-index="${i}"]`),cid=row.querySelector('[data-card]').value,list=row.querySelector('[data-lane]').value,card=e.cards.find(c=>c.card_id===cid);
  return card&&list?{id:e.id,revision:e.revision,action:'move',card_id:cid,board_id:card.board_id,from_list:card.list_id,version:card.version,list_id:list}:{id:e.id,revision:e.revision,action:'keep'};
 })};}
 async function submit(){
  if(busy||!review?.entries.length)return;
  const c=command(),signature=JSON.stringify(c);
  if(!pending||pending.signature!==signature)pending={signature,command:{...c,operation_id:crypto.randomUUID()}};
  lock(true);message('Confirming day…');
  try{
   const {result}=await live.confirmDay(pending.command);pending=null;review=null;lock(false);
   dialog.querySelector('[data-entries]').replaceChildren();dialog.querySelector('[data-confirm]').hidden=true;dialog.querySelector('[data-reload]').hidden=true;dialog.querySelector('[data-close]').textContent='Done';
   message(`${result.confirmed} visits confirmed. ${result.moved} board moves saved${result.moved?'; Trello sync is queued':''}. No comments posted.`);
   onConfirmed?.();
  }catch(error){lock(false);review.entries.forEach((e,i)=>{const row=dialog.querySelector(`[data-index="${i}"]`);row.querySelector('[data-lane]').disabled=!row.querySelector('[data-card]').value;});message(error.message,true);}
 }
 dialog.addEventListener('change',event=>{if(event.target.matches('[data-card]'))selectCard(Number(event.target.closest('[data-index]').dataset.index),event.target.value);});
 dialog.addEventListener('click',event=>{if(busy)return;if(event.target.closest('[data-close]'))dialog.close();else if(event.target.closest('[data-reload]'))load();else if(event.target.closest('[data-confirm]'))submit();});
 dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
 dialog.addEventListener('close',()=>{++version;opener?.focus();});
 return {open(date){if(dialog.open)return;day=date;opener=document.activeElement;dialog.showModal();load();}};
};
