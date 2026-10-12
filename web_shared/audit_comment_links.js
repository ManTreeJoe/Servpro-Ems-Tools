/* Shared exact-comment evidence menu. Ordinary pinning remains independent. */
window.AuditCommentLinks=(()=>{
 const el=(tag,text)=>{const n=document.createElement(tag);if(text)n.textContent=text;return n;};
 const date=iso=>window.AuditFieldControls.date(iso);
 function inspectionSuggestion(text){
  const clean=String(text||'').replace(/\*/g,'');
  const dates=[...clean.matchAll(/(?:inspection (?:performed|date)|(?:^|\n)\s*date)\s*:?\s*(?:(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday),?\s*)?(\d{1,2})\/(\d{1,2})\/(\d{4}|\d{2})\b/gi)];
  const times=[...clean.matchAll(/(?:time of inspection|inspection time|arrival time)\s*:?\s*(\d{1,2}):(\d{2})\s*(AM|PM)?\b/gi)];
  let day='',time='';
  if(dates.length===1){const d=dates[0];day=`${d[1].padStart(2,'0')}/${d[2].padStart(2,'0')}/${d[3].length===2?'20'+d[3]:d[3]}`;if(!window.AuditFieldControls.isoDate(day))day='';}
  if(times.length===1){const t=times[0];let hour=Number(t[1]);const minute=Number(t[2]);
   if(t[3]&&hour>=1&&hour<=12)hour=hour%12+(t[3].toUpperCase()==='PM'?12:0);
   else if(t[3]||hour<13||hour>23)hour=-1;
   if(hour>=0&&minute<60)time=`${String(hour).padStart(2,'0')}:${t[2]}`;
  }
  return {day,time};
 }
 async function request(card,command){const r=await pywebview.api.audit_comment_links(card,command);if(!r?.ok)throw Error(r?.error||'Audit link could not be saved.');return r;}
 function badge(row,links,id,targets){
  const text=Object.entries(links.items||{}).filter(([key,item])=>item?.comment_id===id).map(([key])=>'Linked: '+(targets[key]?.[0]||key));
  if(row.querySelector('[data-audit-link-badges]')?.textContent===text.join(''))return;
  row.querySelector('[data-audit-link-badges]')?.remove();
  const area=el('small');area.dataset.auditLinkBadges='';
  for(const [key,item] of Object.entries(links.items||{}))if(item?.comment_id===id)area.append(el('span','Linked: '+(targets[key]?.[0]||key)));
  row.append(area);
 }
 function edit(context,state,target,previous){
  const {card,comment,onChange}=context,existing=state.links.items[target],linked=existing?.comment_id===comment.id;
  const dialog=el('dialog');dialog.className='audit-link-editor';
  const heading=el('h3',linked?'Edit audit link':'Link comment to audit');
  const excerpt=el('p',comment.text);excerpt.className='audit-link-excerpt';
  const form=el('form'),label=el('label','Audit item'),choice=el('select');choice.setAttribute('aria-label','Audit item');
  for(const [key,[name]] of Object.entries(state.targets))choice.add(new Option(name,key));choice.value=target;label.append(choice);
  const help=el('p'),fields=el('div'),error=el('p');error.setAttribute('role','alert');
  const day=el('input');day.placeholder='MM/DD/YYYY';day.setAttribute('aria-label','Event date');day.inputMode='numeric';
  const time=el('input');time.type='time';time.setAttribute('aria-label','Event time');
  const zone=el('select');zone.setAttribute('aria-label','Event timezone');
  for(const [v,t] of [['Pacific','Pacific (automatic)'],['-07:00','PDT'],['-08:00','PST']])zone.add(new Option(t,v));
  const dayLabel=el('label','Event date (MM/DD/YYYY)');dayLabel.append(day);const timeLabel=el('label','Time');timeLabel.append(time);const zoneLabel=el('label','Timezone');zoneLabel.append(zone);
  fields.append(dayLabel,timeLabel,zoneLabel);
  const inspectionBox=el('fieldset'),inspectionLegend=el('legend','Inspection performed — from the note');
  const inspectionDay=el('input'),inspectionTime=el('input'),confirmed=el('input');
  inspectionDay.placeholder='MM/DD/YYYY';inspectionDay.setAttribute('aria-label','Inspection date');
  inspectionTime.type='time';inspectionTime.setAttribute('aria-label','Inspection time');confirmed.type='checkbox';
  const confirmation=el('label','Save this confirmed inspection time (Pacific)');confirmation.prepend(confirmed);
  const suggestion=inspectionSuggestion(comment.text),savedInspection=state.links.items.inspection_at;
  const savedParts=savedInspection?.comment_id===comment.id?window.AuditFieldControls.pacificParts(savedInspection.value):null;
  inspectionDay.value=savedParts?date(savedParts.day):suggestion.day;inspectionTime.value=savedParts?savedParts.time:suggestion.time;
  inspectionBox.append(inspectionLegend,el('p','Suggested from the note, not its posting timestamp. Confirm the date, year, and AM/PM. Blank fields need your input.'),inspectionDay,inspectionTime,confirmation);
  let originalValue='',originalControls='';
  function fill(){const timestamp=state.targets[choice.value][1]==='timestamp';
   const posting=['field_note_posted_at','initial_note_sent_at'].includes(choice.value);
   const value=(choice.value===target&&linked?existing.value:timestamp&&posting?comment.date:'')||'';
   const p=window.AuditFieldControls.pacificParts(value);
   day.value=p.day?date(p.day):'';time.value=p.time;zone.value=p.zone;
   originalValue=value;originalControls=JSON.stringify([day.value,time.value,zone.value]);
   timeLabel.hidden=zoneLabel.hidden=!timestamp;
   help.textContent=timestamp?'Uses this comment’s posting time. Verify that this is the correct note; you may correct the time below.':'Confirm when the work or billing actually happened—not when this comment was posted.';
   inspectionBox.hidden=choice.value!=='field_note_posted_at';
   if(choice.value==='field_note_posted_at')dayLabel.firstChild.textContent='Field note posted — date (MM/DD/YYYY)';
   else dayLabel.firstChild.textContent='Event date (MM/DD/YYYY)';
   if(choice.value==='inspection_at')help.textContent='Enter when the inspection was performed, as written in the note—not when the comment was posted.';
   if(['incoming_loss_at','insured_contacted_at','on_site_at'].includes(choice.value))help.textContent='Confirm the actual event date and time from the evidence. The comment posting time is not substituted.';
  }choice.onchange=fill;fill();
  const actions=el('div'),save=el('button','Save link'),cancel=el('button','Cancel');save.type='submit';cancel.type='button';cancel.onclick=()=>dialog.close();actions.append(cancel,save);
  const remove=el('button','Unlink');remove.type='button';if(linked)actions.prepend(remove);
  let busy=false;
  async function submit(unlink){if(busy)return;error.textContent='';
   const iso=window.AuditFieldControls.isoDate(day.value),timestamp=state.targets[choice.value][1]==='timestamp';
   const unchanged=originalControls===JSON.stringify([day.value,time.value,zone.value]);
   const value=timestamp&&unchanged?originalValue:timestamp&&iso&&time.value?window.AuditFieldControls.timestamp(iso,time.value,zone.value):timestamp?'':iso;
   if(!unlink&&!value){error.textContent='Enter a valid MM/DD/YYYY date and, for note times, a time and timezone.';return;}
   let inspection;
   if(!unlink&&choice.value==='field_note_posted_at'&&confirmed.checked){
    const d=window.AuditFieldControls.isoDate(inspectionDay.value);
    inspection=d&&inspectionTime.value?window.AuditFieldControls.timestamp(d,inspectionTime.value,'Pacific'):'';
    if(!inspection){error.textContent='Confirm a valid inspection date and time in Pacific time.';return;}
   }
   const occupied=state.links.items[choice.value];
   if(!unlink&&occupied&&occupied.comment_id!==comment.id&&!confirm('Replace the existing comment linked to this audit item? Its history will be retained.'))return;
   busy=true;save.disabled=remove.disabled=cancel.disabled=true;
   try{const r=await request(card,{comment_id:comment.id,target:unlink?target:choice.value,value,inspection,expected:state.links.version,remove:unlink,previous:previous|| (linked?target:null)});
    onChange?.(r.links,r.targets);dialog.close();
   }catch(e){error.textContent=e.message;}finally{busy=false;save.disabled=remove.disabled=cancel.disabled=false;}
  }
  form.onsubmit=e=>{e.preventDefault();void submit(false);};remove.onclick=()=>void submit(true);
  dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});dialog.addEventListener('close',()=>dialog.remove());
  form.append(label,help,fields,inspectionBox,error,actions);dialog.append(heading,excerpt,form);document.body.append(dialog);dialog.showModal();
 }
 async function menu(event,context){
  event.preventDefault();event.stopPropagation();
  document.querySelector('.audit-link-menu')?.remove();
  const box=el('div');box.className='audit-link-menu';box.setAttribute('role','menu');box.append(el('small','Link to audit…'));
  (event.target.closest('dialog[open]')||document.body).append(box);
  box.style.left=Math.max(8,Math.min(event.clientX,innerWidth-280))+'px';box.style.top=Math.max(8,Math.min(event.clientY,innerHeight-360))+'px';
  const loading=el('p','Loading audit links…');box.append(loading);
  const close=()=>{box.remove();document.removeEventListener('pointerdown',outside,true);document.removeEventListener('keydown',key,true);};
  const outside=e=>{if(!box.contains(e.target))close();},key=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close();}};
  document.addEventListener('pointerdown',outside,true);document.addEventListener('keydown',key,true);
  try{const state=await request(context.card);if(!box.isConnected)return;loading.remove();
   for(const [target,[title]] of Object.entries(state.targets)){
    const linked=state.links.items[target]?.comment_id===context.comment.id;
    const button=el('button',(linked?'Edit link: ':'')+title);button.type='button';button.setAttribute('role','menuitem');
    button.onclick=()=>{close();edit(context,state,target,linked?target:null);};box.append(button);
   }box.querySelector('button')?.focus();
  }catch(e){loading.textContent=e.message;}
 }
 function bind(host,resolve,onChange){
  const states=new Map(),pending=new Set();
  function paint(){for(const row of host.querySelectorAll('.logs-review-comment,[data-comment-id]')){
   const c=resolve(row);if(!c?.card||!c.comment?.id)continue;const s=states.get(c.card);
   if(s)badge(row,s.links,c.comment.id,s.targets);
   else if(!pending.has(c.card)){pending.add(c.card);request(c.card).then(r=>{states.set(c.card,r);paint();}).catch(()=>{});}
  }}
  const observer=new MutationObserver(()=>paint());observer.observe(host,{childList:true,subtree:true});paint();
  host.addEventListener('contextmenu',e=>{const context=resolve(e.target);if(context?.card&&context.comment?.id)void menu(e,{...context,onChange:(links,targets)=>{states.set(context.card,{links,targets});paint();onChange?.(links,targets);}});});
 }
 function protectForm(form,links){for(const [key,link] of Object.entries(links?.items||{})){
  const input=form.elements[key];if(!input)continue;
  const group=input.closest('.audit-clock-field,.audit-date-field');if(!group)continue;
  for(const control of group.querySelectorAll('input:not([type=hidden]),select,button'))control.disabled=!!link;
  group.querySelector('[data-link-explanation]')?.remove();
  if(link){const note=el('small','Linked comment · right-click that comment to edit or unlink this date.');note.dataset.linkExplanation='';group.append(note);}
 }}
 return {bind,menu,badge,protectForm,inspectionSuggestion};
})();
