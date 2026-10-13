/* Card membership combines Trello assignments and explicit OneLoss choices. */
async function openJobMembers(cardId) {
  const previous=document.activeElement, dialog=document.createElement('dialog');
  dialog.className='job-members-dialog';
  dialog.innerHTML=`<header><h2>Job members</h2><button type="button" data-close aria-label="Close members">×</button></header>
    <p>Trello members are included automatically for this card. OneLoss choices apply only here and never change Trello or job permissions.</p>
    <label class="member-search">Find a teammate<input type="search" placeholder="Search people" disabled></label>
    <div data-people></div><label class="member-mute"><input type="checkbox" data-mute disabled> Mute this card for me (including mentions)</label>
    <p role="status" data-status>Loading OneLoss members…</p><button type="button" data-retry hidden>Retry</button>`;
  document.body.append(dialog);let busy=false,people=[],unmatched=[];
  const status=dialog.querySelector('[data-status]'),retry=dialog.querySelector('[data-retry]'),search=dialog.querySelector('[type=search]'),mute=dialog.querySelector('[data-mute]');
  const lock=value=>{busy=value;dialog.querySelectorAll('input,button:not([data-close])').forEach(el=>el.disabled=value);};
  function close(){if(!busy)dialog.close();}
  dialog.querySelector('[data-close]').onclick=close;
  dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
  dialog.addEventListener('close',()=>{dialog.remove();previous?.focus();});
  function render(){
    const host=dialog.querySelector('[data-people]');host.replaceChildren();
    const filtered=people.filter(p=>`${p.name} ${p.username}`.toLowerCase().includes(search.value.toLowerCase()));
    if(!filtered.length){host.textContent='No matching OneLoss teammates with access to this card.';}
    for(const person of filtered){
      const label=document.createElement('label');label.className='member-person';
      const check=document.createElement('input');check.type='checkbox';check.checked=!!person.member;
      const name=document.createElement('span');name.textContent=person.name;
      const handle=document.createElement('small');handle.textContent='@'+person.username+' · '+(person.source||'OneLoss');name.append(handle);label.append(check,name);host.append(label);
      check.onchange=async()=>{const value=check.checked;lock(true);status.textContent='Saving membership…';
        try{const result=await pywebview.api.set_personal_job_member(cardId,person.id,value);if(!result?.ok)throw Error(result?.error||'Membership was not confirmed.');person.member=value;person.source='OneLoss';handle.textContent='@'+person.username+' · OneLoss';status.textContent='OneLoss choice saved for this card. Trello is unchanged.';}
        catch(e){check.checked=!!person.member;status.textContent=e.message;retry.hidden=false;}
        finally{lock(false);}
      };
    }
    for(const person of unmatched.filter(p=>`${p.name} ${p.username||''}`.toLowerCase().includes(search.value.toLowerCase()))){
      const row=document.createElement('div');row.className='member-person';
      const name=document.createElement('span'),note=document.createElement('small');name.textContent=person.name;
      note.textContent=(person.username?'@'+person.username+' · ':'')+'From Trello · Needs account match';
      name.append(note);row.append(name);host.append(row);
    }
  }
  async function load(){lock(true);retry.hidden=true;status.textContent='Loading OneLoss members…';
    try{const result=await pywebview.api.personal_job_members(cardId);if(!dialog.isConnected)return;if(!result?.ok)throw Error(result?.error||'Members could not load.');people=result.people||[];unmatched=result.unmatched||[];mute.checked=!!result.muted;render();status.textContent='Uses the latest saved Trello membership. Unchecking someone overrides it in OneLoss only.';lock(false);}
    catch(e){status.textContent=e.message;retry.hidden=false;retry.disabled=false;busy=false;}
  }
  mute.onchange=async()=>{const value=mute.checked;lock(true);status.textContent='Saving your preference…';
    try{const result=await pywebview.api.mute_personal_job(cardId,value);if(!result?.ok)throw Error(result?.error||'Preference was not confirmed.');status.textContent=value?'This card is muted for you.':'Notifications enabled for you.';}
    catch(e){mute.checked=!value;status.textContent=e.message;retry.hidden=false;}finally{lock(false);}
  };
  search.oninput=render;retry.onclick=load;dialog.showModal();await load();
}
