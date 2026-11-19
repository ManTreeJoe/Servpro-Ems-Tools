window.addEventListener('pywebviewready', async () => {
  const access = await pywebview.api.employee_access_status();
  if (!access.is_admin) return;
  const host = document.createElement('section');
  host.setAttribute('data-settings-scope','admin');
  const title = document.createElement('h2'); title.textContent='Team access';
  const intro = document.createElement('p'); intro.textContent='Approve Microsoft accounts and assign franchise access. Viewer reads; editor updates; administrator manages access.';
  const message = document.createElement('p'); message.setAttribute('role','status');
  const list = document.createElement('div');
  const refresh = document.createElement('button'); refresh.className='btn';refresh.textContent='Refresh requests';
  host.append(title,intro,refresh,message,list);
  (document.querySelector('main') || document.body).append(host);
  async function load() {
    refresh.disabled=true;
    const result = await pywebview.api.employee_admin_snapshot();
    refresh.disabled=false;
    if(!result.ok){message.textContent=result.error;return;}
    message.textContent=''; list.replaceChildren();
    for(const user of result.users){
      const form=document.createElement('form');
      Object.assign(form.style,{padding:'18px',margin:'12px 0',border:'1px solid var(--border, #555)',borderRadius:'8px'});
      const heading=document.createElement('h3');heading.textContent=user.email;
      const status=document.createElement('p');status.textContent=user.status+(user.emergency?' · Recovery administrator':'');
      const role=document.createElement('select');role.setAttribute('aria-label',`Role for ${user.email}`);
      for(const [value,label] of [['viewer','Viewer'],['editor','Editor'],['admin','Administrator']]){
        const option=document.createElement('option');option.value=value;option.textContent=label;role.append(option);
      }
      role.value=user.role||'viewer';
      const franchises=document.createElement('fieldset');const legend=document.createElement('legend');legend.textContent='Franchise access';franchises.append(legend);
      for(const franchise of result.franchises){
        const label=document.createElement('label');label.style.display='block';
        const input=document.createElement('input');input.type='checkbox';input.value=franchise.code;input.checked=user.departments.includes(franchise.code);
        label.append(input,document.createTextNode(franchise.label));franchises.append(label);
      }
      form.append(heading,status,role,franchises);
      if(!user.emergency){
        const save=document.createElement('button');save.className='btn';save.textContent='Approve and save';
        const remove=document.createElement('button');remove.className='btn';remove.type='button';remove.textContent=user.status==='pending'?'Reject':'Suspend access';
        async function decide(action){
          for(const control of form.elements)control.disabled=true;
          const selected=[...franchises.querySelectorAll('input:checked')].map(input=>input.value);
          const result=await pywebview.api.employee_decide_user(user.user_id,action,role.value,selected,user.revision);
          if(result.ok)await load();else{message.textContent=result.error;for(const control of form.elements)control.disabled=false;}
        }
        form.onsubmit=event=>{event.preventDefault();void decide('approve');};
        remove.onclick=()=>void decide(user.status==='pending'?'reject':'suspend');
        form.append(save,remove);
      }else{role.disabled=true;franchises.disabled=true;}
      list.append(form);
    }
  }
  refresh.onclick=()=>void load();void load();
}, {once:true});
