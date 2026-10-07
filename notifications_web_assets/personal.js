(()=>{'use strict';
  const get=id=>document.getElementById(id);let items=[],generation=0;
  const status=text=>get('personal-status').textContent=text;
  const pendingReads=new Map();
  async function setRead(item,read){
    if(pendingReads.has(item.id))return pendingReads.get(item.id);
    const before=item.read_at;
    generation++; // Discard reads started before this local change.
    item.read_at=read?new Date().toISOString():null;
    const task=Promise.resolve().then(async()=>{
      try{
        const result=await pywebview.api.personal_read(item.id,read);
        if(!result?.ok)throw Error(result?.error||'Read status was not saved.');
      }catch(error){item.read_at=before;throw error;}
      finally{pendingReads.delete(item.id);render();}
    });
    pendingReads.set(item.id,task);
    render();get('personal-refresh').disabled=false;
    return task;
  }
  async function readOpened(item){
    if(pendingReads.has(item.id))return pendingReads.get(item.id);
    if(item.read_at)return;
    return setRead(item,true);
  }
  async function openJob(item){
    try{
    const result=await pywebview.api.notification_job(item.card_id,item.comment_id||'');
    if(!result?.ok)throw Error(result?.error||'The job link is unavailable.');
    window.parent.postMessage({type:'linguar-open-job',...result},'*');
    try{await readOpened(item);}catch(e){status(e.message);}
    return true;
    }catch(e){status(e.message||'The job link is unavailable.');return false;}
  }
  function render(){const feed=get('personal-feed');const scroll=feed.scrollTop;feed.replaceChildren();
    const visible=get('personal-unread').checked?items.filter(item=>!item.read_at):items;
    if(!visible.length){const empty=document.createElement('p');empty.className='personal-empty';empty.textContent=get('personal-unread').checked?'No unread notifications. Turn off Only show unread to see earlier messages.':'No notifications in this view. Add members from a job’s Members button. New OneLoss comments and @mentions appear here.';feed.append(empty);return;}
    for(const item of visible){const row=document.createElement('article');row.className='personal-notification'+(!item.read_at?' unread':'');
      const content=document.createElement('div'),title=document.createElement('strong'),meta=document.createElement('small'),body=document.createElement('p'),actions=document.createElement('div');actions.className='personal-actions';
      title.textContent=item.client;meta.textContent=`${item.kind==='mention'?'Mention':item.kind==='membership'?'Added to job':'Job comment'} · ${item.actor} · ${new Date(item.created_at).toLocaleString()}`;
      body.textContent=item.body;content.append(title,document.createElement('br'),meta,body);row.append(content,actions);feed.append(row);
      function button(label,fn){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=async()=>{b.disabled=true;try{await fn();}catch(e){status(e.message||'Action was not confirmed. Refresh and retry.');}finally{b.disabled=false;}};actions.append(b);return b;}
      button('Open job',()=>openJob(item));
      button('Read message',async()=>{if(window.NotificationReader){window.NotificationReader.open(item,()=>openJob(item));await readOpened(item);}});
      const readButton=button(item.read_at?'Mark unread':'Mark read',async()=>{await setRead(item,!item.read_at);status('Read status saved across PCs.');});
      readButton.disabled=pendingReads.has(item.id);
      button(item.muted?'Unmute job':'Mute job',async()=>{const result=await pywebview.api.personal_mute(item.card_id,!item.muted);if(!result?.ok)throw Error(result?.error||'Mute was not saved.');const muted=!item.muted;await load();status(muted?'This job is muted, including mentions.':'Notifications enabled for this job.');});
    }feed.scrollTop=scroll;
  }
  async function load(){if(pendingReads.size){status('Saving read status…');return;}const token=++generation;get('personal-refresh').disabled=true;status('Checking your inbox…');
    try{const result=await pywebview.api.personal_inbox(get('personal-filter').value,false);if(token!==generation)return;if(!result?.ok)throw Error(result?.error||'Your inbox could not load.');items=result.items||[];render();status(`Latest ${items.length} notifications · refresh to check for new activity.${result.pending_delivery?' '+result.pending_delivery+' comment notification deliveries pending on this PC. Refresh to retry.':''}`);}
    catch(e){if(token===generation)status(e.message);}finally{if(token===generation)get('personal-refresh').disabled=false;}
  }
  window.addEventListener('pywebviewready',()=>{
    get('personal-refresh').onclick=load;get('personal-filter').onchange=load;get('personal-unread').onchange=render;
    get('personal-source').onclick=()=>{get('personal-panel').hidden=false;get('trello-panel').hidden=true;get('personal-source').setAttribute('aria-pressed','true');get('trello-source').setAttribute('aria-pressed','false');};
    get('trello-source').onclick=()=>{get('personal-panel').hidden=true;get('trello-panel').hidden=false;get('personal-source').setAttribute('aria-pressed','false');get('trello-source').setAttribute('aria-pressed','true');window.dispatchEvent(new Event('trello-notifications-open'));};
    load();
  });
})();
