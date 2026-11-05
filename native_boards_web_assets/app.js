'use strict';
const $ = id => document.getElementById(id);
let state, selected, archived = false, busy = false;
const dialogStatus=document.createElement('p');dialogStatus.setAttribute('role','status');$('detail').append(dialogStatus);
function element(tag, text, className) { const e=document.createElement(tag); e.textContent=text; if(className)e.className=className; return e; }
function lanes(select, value) { select.replaceChildren(...state.lanes.map(l=>{const o=element('option',l.name);o.value=l.id;return o;}));if(value)select.value=value; }
function render() {
  lanes($('new-lane'),$('new-lane').value);
  $('archive').textContent=archived?'Back to board':`Archive (${state.cards.filter(c=>c.archived).length})`;
  $('board').replaceChildren();
  for(const lane of state.lanes){
    const cards=state.cards.filter(c=>c.lane_id===lane.id && c.archived===archived);
    const column=element('section','', 'lane');column.append(element('h2',`${lane.name} · ${cards.length}`));
    for(const c of cards){const b=element('button',c.title,'card');b.onclick=()=>open(c.id);column.append(b);}
    if(!cards.length)column.append(element('p',archived?'No archived cards':'No cards yet','empty'));
    $('board').append(column);
  }
  if(selected)detail();
}
function open(id){selected=id;detail();$('detail').showModal();}
function detail(){
  const c=state.cards.find(c=>c.id===selected);if(!c)return;
  $('card-title').textContent=c.title;
  $('identity').textContent=`${c.archived?'Archived · ':''}Test card · ${c.id} · Not linked to a real job`;
  lanes($('move-lane'),c.lane_id);$('move').disabled=c.archived; $('up').disabled=c.archived;
  $('toggle-archive').textContent=c.archived?'Restore':'Archive';
  $('history').replaceChildren(...state.events.filter(e=>e.card_id===selected).map(e=>{const a=element('article','');a.append(element('time',new Date(e.at).toLocaleString()+' · '+e.actor),element('div',e.text));return a;}));
}
async function change(action,values){
  if(busy||!state)return false;busy=true;
  try{state=await window.pywebview.api.change(state.revision,action,values);render();$('status').textContent=dialogStatus.textContent='Saved locally';return true;}
  catch(e){$('status').textContent=dialogStatus.textContent=String(e.message||e);return false;}
  finally{busy=false;}
}
async function load(){try{state=await window.pywebview.api.load();render();$('status').textContent='Ready · local test data';}catch(e){$('status').textContent=String(e.message||e);}}
$('refresh').onclick=load;
$('archive').onclick=()=>{archived=!archived;render();};
$('close').onclick=()=>$('detail').close();
$('detail').addEventListener('close',()=>{selected=null;});
$('new-card').onsubmit=async e=>{e.preventDefault();if(await change('create',{text:$('title').value,lane_id:$('new-lane').value}))$('title').value='';};
$('add-lane').onsubmit=async e=>{e.preventDefault();if(await change('lane',{text:$('lane-name').value}))$('lane-name').value='';};
$('move').onclick=()=>change('move',{card_id:selected,lane_id:$('move-lane').value});
$('up').onclick=()=>change('up',{card_id:selected});
$('toggle-archive').onclick=()=>change(state.cards.find(c=>c.id===selected).archived?'restore':'archive',{card_id:selected});
$('reply').onsubmit=async e=>{e.preventDefault();if(await change('comment',{card_id:selected,text:$('comment').value}))$('comment').value='';};
window.addEventListener('pywebviewready',load);
