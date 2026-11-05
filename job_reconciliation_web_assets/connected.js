'use strict';
// Contextual presentation over the same reviewed, server-authorized operations.
const connectedPopup=new URLSearchParams(location.search).get('popup')==='1';
if(connectedPopup){
 document.body.classList.add('connected-popup');
 $('connected-panel').hidden=false;
 function button(label,fn){const b=el('button',label);b.type='button';b.onclick=()=>{if(!busy)fn();};return b;}
 function back(){if(busy)return;clearLink();clear();$('merge-panel').hidden=true;$('link-panel').hidden=false;
 $('connection-search').hidden=true;$('connection-choice').hidden=true;$('connected-sections').hidden=false;}
 function searchSection(section){back();$('link-section').value=section;$('connection-search-title').textContent=`Connect ${section} card`;
 $('connection-search').hidden=false;$('connected-sections').hidden=true;$('connection-query').value='';results();$('connection-query').focus();}
 window.renderConnectedPanel=()=>{
 const job=jobInventory.find(j=>j.job_id===$('link-target').value);
 $('connected-job').textContent=job?.display_name||'Choose the correct job first';
 document.body.classList.toggle('context-resolved',!!job);
 if(!job)return;
 $('connected-sections').replaceChildren();
 for(const section of ['EMS','Contents','Recon']){
 const row=el('section','');row.className='connected-section';const heading=el('div','');heading.className='connected-heading';heading.append(el('h2',section),button('Connect a card',()=>searchSection(section)));row.append(heading);
 const matches=inventory.flatMap(c=>c.links.filter(l=>l.job_id===job.job_id&&sectionName(l.link_type)===section).map(l=>({c,l})));
 if(!matches.length)row.append(el('p','No card connected'));
 for(const {c,l} of matches){let historical=false;try{historical=JSON.parse(l.metadata_json||'{}').historical===true;}catch{}
 const line=el('div','');line.className='connected-card';line.append(el('strong',c.name),el('small',historical?'Historical connection':c.closed?'Archived card':'Current connection'));row.append(line);}
 $('connected-sections').append(row);
 }
 };
 function results(){
 const q=$('connection-query').value.trim().toLowerCase();$('connection-choice').hidden=true;clearLink();clear();$('merge-panel').hidden=true;
 const matches=inventory.filter(c=>{const claims=c.links.map(l=>jobInventory.find(j=>j.job_id===l.job_id)?.claim_number||'').join(' ');return (c.name+' '+claims).toLowerCase().includes(q);});
 $('connection-results').replaceChildren();
 if(!matches.length)$('connection-results').append(el('p','No matching saved cards. Try another name or claim number.'));
 for(const c of matches){const owners=[...new Set(c.links.map(l=>l.job_id))];const b=button('',()=>choose(c,owners));b.className='connection-result';
 b.append(el('strong',c.name),el('span',owners.length?'Connected to '+owners.map(ownerName).join(', '):'Not connected to a job'));
 const info=[...new Set(c.links.map(l=>sectionName(l.link_type)))].join(', ');b.append(el('small',[info,c.closed?'Archived':''].filter(Boolean).join(' · ')));$('connection-results').append(b);}
 }
 function choose(c,owners){
 clearLink();clear();$('connection-choice').hidden=false;$('connection-choice').replaceChildren(el('h3',c.name));
 $('link-card').value=c.card_id;
 const target=$('link-target').value;
 if(owners.length===1&&owners[0]===target&&c.links.some(l=>l.job_id===target&&sectionName(l.link_type)===$('link-section').value)){
 $('connection-choice').append(el('p','Already connected to this job and section. No change needed.'));return;}
 const action=owners.length?'move':'link';$('mode').value=action;
 $('connection-choice').append(el('p',owners.length?'Currently connected to '+owners.map(ownerName).join(', ')+'. Transfer only this card connection, or review combining the jobs.':'Connect this card to the selected section. No new job will be created.'));
 if(owners.length<=1)$('connection-choice').append(button(owners.length?'Review transfer':'Review connection',()=>{$('link-choose').requestSubmit();}));
 for(const owner of owners.filter(id=>id!==target))$('connection-choice').append(button('Review merge with '+ownerName(owner),()=>{
 $('target').value=target;$('source').value=owner;$('merge-panel').hidden=false;$('link-preview').hidden=true;$('choose').requestSubmit();}));
 $('connection-choice').scrollIntoView({block:'nearest'});
 }
 $('connection-query').oninput=()=>{if(!busy)results();};$('connection-cancel').onclick=back;
 window.connectedLinkSaved=()=>{$('connection-search').hidden=true;$('connection-choice').hidden=true;$('connected-sections').hidden=false;};
 document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!busy){window.parent.postMessage({type:'ems-close-connected-cards'},location.origin);}});
 renderConnectedPanel();
}
