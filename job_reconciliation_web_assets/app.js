'use strict';
const $=id=>document.getElementById(id);
const el=(tag,text)=>{const e=document.createElement(tag);e.textContent=text;return e;};
let review=null,busy=false,retired=null,linkReview=null,inventory=[],jobInventory=[];
function controls(){for(const id of ['target','source','review','refresh','confirmation','verify'])$(id).disabled=busy;
 for(const id of ['mode','link-target','link-section','link-card','card-search','link-review','link-refresh','link-confirmation'])$(id).disabled=busy;
 $('link-save').disabled=busy||!linkReview?.can_apply||$('link-confirmation').value!=='SAVE';
 $('merge').disabled=busy||!review?.can_apply||$('confirmation').value!=='MERGE';}
function clear(){review=null;$('preview').hidden=true;$('success').hidden=true;$('confirmation').value='';controls();}
async function run(fn){if(busy)return;busy=true;controls();try{await fn();}catch(e){$('status').textContent=String(e.message||e);}finally{busy=false;controls();}}
async function load(){clear();clearLink();await run(async()=>{const jobs=await window.pywebview.api.jobs();jobInventory=jobs;
 for(const id of ['target','source','link-target']){$(id).replaceChildren(el('option','Choose a job…'));$(id).firstChild.value='';
  for(const j of jobs){const o=el('option',`${j.display_name} · ${j.claim_number||'No claim'} · ${j.job_id.slice(0,8)}`);o.value=j.job_id;$(id).append(o);}}
 inventory=await window.pywebview.api.cards();renderCards();renderConnections();
 $('status').textContent=jobs.length?`${jobs.length} Dev jobs available. Select the job and action to review.`:'No accessible Dev jobs found.';
 applyOpeningContext();
 });}
function render(p){$('facts').replaceChildren();const a=p.snapshot.target,b=p.snapshot.source;
 for(const key of Object.keys(a)){const tr=document.createElement('tr');if(JSON.stringify(a[key])!==JSON.stringify(b[key]))tr.className='different';
  tr.append(el('th',key.replaceAll('_',' ')),el('td',a[key]==null?'—':typeof a[key]==='object'?JSON.stringify(a[key]):String(a[key])),el('td',b[key]==null?'—':typeof b[key]==='object'?JSON.stringify(b[key]):String(b[key])));$('facts').append(tr);}
 $('records').replaceChildren();
 for(const [key,rows] of Object.entries(p.snapshot)){if(!Array.isArray(rows)||!rows.length)continue;
  const d=document.createElement('details');d.append(el('summary',`${key} · ${rows.length} records across both jobs`),el('pre',JSON.stringify(rows,null,2)));$('records').append(d);}
 if(!$('records').children.length)$('records').append(el('p','No linked records in this preview.'));
 $('blockers').replaceChildren(...(p.blockers.length?p.blockers:['No blocking conflicts found.']).map(x=>el('li',x)));
 $('confirm').hidden=!p.can_apply;$('preview').hidden=false;}
$('choose').onsubmit=e=>{e.preventDefault();if(busy)return;clear();
 if(!$('target').value||$('target').value===$('source').value){$('status').textContent='Choose two different jobs.';return;}
 run(async()=>{$('status').textContent='Checking current facts and linked records…';review=await window.pywebview.api.preview($('target').value,$('source').value);render(review);$('status').textContent=review.can_apply?'Review both columns before confirming.':'Merge blocked. Resolve the listed conflicts, then review again.';});};
for(const id of ['target','source'])$(id).onchange=clear;
$('confirmation').oninput=controls;$('refresh').onclick=load;
$('confirm').onsubmit=e=>{e.preventDefault();if(busy||!review?.can_apply||$('confirmation').value!=='MERGE')return;
 run(async()=>{$('status').textContent='Saving one atomic merge…';const r=await window.pywebview.api.confirm(review.review_id,'MERGE');
  if(!r.ok)throw Error('Merge outcome was not confirmed. Retry this same review.');retired=r.retired_job_id;review=null;$('preview').hidden=true;
  $('success').hidden=false;$('verified').textContent='';$('result').textContent=`Kept job ${r.job_id}. Retired ${retired}.`;$('status').textContent='Saved. Verify the surviving record below.';
 });};
$('verify').onclick=()=>run(async()=>{const r=await window.pywebview.api.verify(retired);$('verified').textContent=JSON.stringify(r.job,null,2);$('status').textContent='Verified: the retired ID resolves to this saved job.';});
function clearLink(){linkReview=null;$('link-preview').hidden=true;$('link-confirmation').value='';controls();}
function ownerName(id){return jobInventory.find(j=>j.job_id===id)?.display_name||id;}
let openingContextApplied=false;
function applyOpeningContext(){
 if(openingContextApplied)return;
 const raw=new URLSearchParams(location.search).get('focus');if(!raw)return;
 let context;try{context=JSON.parse(raw);}catch{return;}
 if(!context||typeof context!=='object')return;
 openingContextApplied=true;
 const card=inventory.find(c=>c.card_id===context.card_id);
 const owners=[...new Set((card?.links||[]).map(l=>l.job_id))];
 let job=jobInventory.find(j=>j.job_id===context.job_id);
 if(!job&&owners.length===1)job=jobInventory.find(j=>j.job_id===owners[0]);
 // A canonical key is exact identity; a display name is not.
 if(!job&&!context.card_id)job=jobInventory.find(j=>j.canon_key===context.client);
 if(job){$('link-target').value=job.job_id;$('target').value=job.job_id;}
 const section={EMS:'EMS',CONTENTS:'Contents',RECON:'Recon'}[String(context.section||'').toUpperCase()];
 if(section)$('link-section').value=section;
 if(card){$('link-card').value=card.card_id;$('mode').value=card.links.length?'move':'link';}
 $('link-help').textContent=$('mode').value==='move'?'Review this card’s current association or choose another card to connect. Both jobs remain separate.':'Attach a saved, unowned card. No new job is created.';
 renderConnections();
 $('status').textContent=job?`Opened for ${job.display_name}. Nothing has been changed.`:
 owners.length>1?'This card has multiple job owners. Choose the correct job or review a merge. Nothing has changed.':
 'The current card has no verified job connection in Dev. Choose its destination job; nothing has changed.';
}
function sectionName(kind){return {trello_card:'EMS',trello_card_contents:'Contents',trello_card_recon:'Recon'}[kind]||kind;}
function renderCards(){const query=$('card-search').value.trim().toLowerCase();
 const cards=inventory.filter(c=>(c.name+' '+c.card_id).toLowerCase().includes(query));
 $('link-card').replaceChildren(el('option','Choose a card…'));$('link-card').firstChild.value='';
 for(const c of cards){const owners=[...new Set(c.links.map(l=>ownerName(l.job_id)))];
 const option=el('option',`${c.name}${c.closed?' · Archived':''} · ${owners.length?owners.join(', '):'Unlinked'}`);option.value=c.card_id;$('link-card').append(option);}
 $('card-count').textContent=cards.length?`${cards.length} saved cards found`:'No saved Dev cards match. Reload or try another name.';
}
function renderConnections(){const target=$('link-target').value;const rows=[];
 for(const c of inventory)for(const l of c.links.filter(l=>l.job_id===target)){
 let historical=false;try{historical=!!JSON.parse(l.metadata_json||'{}').historical;}catch{}
 rows.push(el('li',`${sectionName(l.link_type)} · ${c.name}${historical?' · Historical':''}${c.closed?' · Archived':''} · ${c.card_id}`));}
 $('current-links').replaceChildren(...(rows.length?rows:[el('li',target?'No saved card connections found.':'Select a job to see its connections.')]));
 window.renderConnectedPanel?.();
 window.renderDuplicatePanel?.();
}
$('mode').onchange=()=>{clear();clearLink();const merging=$('mode').value==='merge';$('merge-panel').hidden=!merging;$('link-panel').hidden=merging;
 $('link-help').textContent=$('mode').value==='move'?'Transfer an existing association. Both jobs remain separate. Review the current owner before saving.':'Attach a saved, unowned card. No new job is created.';
 $('status').textContent='Choose the records, then review the proposed change.';};
$('link-target').onchange=()=>{clearLink();renderConnections();};
$('link-section').onchange=clearLink;$('link-card').onchange=clearLink;
$('card-search').oninput=()=>{clearLink();renderCards();};
$('link-confirmation').oninput=controls;$('link-refresh').onclick=load;
$('link-choose').onsubmit=e=>{e.preventDefault();if(busy)return;clearLink();run(async()=>{
 $('status').textContent='Checking the current owner and destination…';
 linkReview=await window.pywebview.api.preview_link($('link-target').value,$('link-card').value,$('link-section').value,$('mode').value);
 const s=linkReview.snapshot;$('link-summary').replaceChildren(
 el('p',`Card: ${s.card.name} · ${s.card.id}`),
 el('p',`Current owner: ${s.owners.length?s.owners.map(o=>o.name+' · '+o.job_id).join('; '):'Unlinked'}`),
 el('p',`Destination: ${s.target.display_name} · ${s.target.job_id} · ${s.section}`));
 const details=document.createElement('details');details.append(el('summary','View saved card information'),el('pre',s.card.description||'No saved description.'));$('link-summary').append(details);
 $('link-blockers').replaceChildren(...linkReview.blockers.map(x=>el('li',x)));$('link-confirm').hidden=!linkReview.can_apply;$('link-preview').hidden=false;
 $('status').textContent=linkReview.can_apply?'Review the change, then type SAVE.':'Nothing changed. See the review notes below.';
 });};
$('link-confirm').onsubmit=e=>{e.preventDefault();if(busy||!linkReview?.can_apply||$('link-confirmation').value!=='SAVE')return;
 run(async()=>{const result=await window.pywebview.api.confirm_link(linkReview.review_id,'SAVE');
 if(!result.ok)throw Error('Save was not confirmed. Retry this same review.');
 clearLink();$('status').textContent='Link saved in Dev. Trello and other job records were not changed.';
 try{inventory=await window.pywebview.api.cards();renderConnections();renderCards();window.connectedLinkSaved?.();}
 catch(e){$('status').textContent='Link saved, but refreshing connections failed. Reload to verify the saved state.';}
 });};
window.addEventListener('pywebviewready',load);if(window.pywebview?.api)load();
