/* Membership is shared job state; mute belongs only to the signed-in person. */
async function openJobMembers(cardId) {
  const previous=document.activeElement, dialog=document.createElement('dialog');
  dialog.className='job-members-dialog';
  dialog.innerHTML=`<header><h2>Job members</h2><button type="button" data-close aria-label="Close members">×</button></header>
    <p>Members receive new OneLoss comment updates across this job’s linked cards. Adding someone does not change their job permissions.</p>
    <label class="member-search">Find a teammate<input type="search" placeholder="Search people" disabled></label>
    <div data-people></div><label class="member-mute"><input type="checkbox" data-mute disabled> Mute this job for me (including mentions)</label>
    <p role="status" data-status>Loading OneLoss members…</p><button type="button" data-retry hidden>Retry</button>`;
  document.body.append(dialog);let busy=false,people=[];
  const status=dialog.querySelector('[data-status]'),retry=dialog.querySelector('[data-retry]'),search=dialog.querySelector('[type=search]'),mute=dialog.querySelector('[data-mute]');
  const lock=value=>{busy=value;dialog.querySelectorAll('input,button:not([data-close])').forEach(el=>el.disabled=value);};
  function close(){if(!busy)dialog.close();}
  dialog.querySelector('[data-close]').onclick=close;
  dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
  dialog.addEventListener('close',()=>{dialog.remove();previous?.focus();});
  function render(){
    const host=dialog.querySelector('[data-people]');host.replaceChildren();
    const filtered=people.filter(p=>`${p.name} ${p.username}`.toLowerCase().includes(search.value.toLowerCase()));
    if(!filtered.length){host.textContent='No matching teammates with access to this job.';return;}
    for(const person of filtered){
      const label=document.createElement('label');label.className='member-person';
      const check=document.createElement('input');check.type='checkbox';check.checked=!!person.member;
      const name=document.createElement('span');name.textContent=person.name;
      const handle=document.createElement('small');handle.textContent='@'+person.username;name.append(handle);label.append(check,name);host.append(label);
      check.onchange=async()=>{const value=check.checked;lock(true);status.textContent='Saving membership…';
        try{const result=await pywebview.api.set_personal_job_member(cardId,person.id,value);if(!result?.ok)throw Error(result?.error||'Membership was not confirmed.');person.member=value;status.textContent='Membership saved.';}
        catch(e){check.checked=!!person.member;status.textContent=e.message;retry.hidden=false;}
        finally{lock(false);}
      };
    }
  }
  async function load(){lock(true);retry.hidden=true;status.textContent='Loading OneLoss members…';
    try{const result=await pywebview.api.personal_job_members(cardId);if(!dialog.isConnected)return;if(!result?.ok)throw Error(result?.error||'Members could not load.');people=result.people||[];mute.checked=!!result.muted;render();status.textContent='Saved across PCs. Trello memberships are separate.';lock(false);}
    catch(e){status.textContent=e.message;retry.hidden=false;retry.disabled=false;busy=false;}
  }
  mute.onchange=async()=>{const value=mute.checked;lock(true);status.textContent='Saving your preference…';
    try{const result=await pywebview.api.mute_personal_job(cardId,value);if(!result?.ok)throw Error(result?.error||'Preference was not confirmed.');status.textContent=value?'This job is muted for you.':'Notifications enabled for you.';}
    catch(e){mute.checked=!value;status.textContent=e.message;retry.hidden=false;}finally{lock(false);}
  };
  search.oninput=render;retry.onclick=load;dialog.showModal();await load();
}
