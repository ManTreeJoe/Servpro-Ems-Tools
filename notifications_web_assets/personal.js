(()=>{'use strict';
  const get=id=>document.getElementById(id);let items=[],generation=0;
  const status=text=>get('personal-status').textContent=text;
  function render(){const feed=get('personal-feed');feed.replaceChildren();
    if(!items.length){const empty=document.createElement('p');empty.className='personal-empty';empty.textContent='No notifications in this view. Add members from a job’s Members button. New OneLoss comments and @mentions appear here.';feed.append(empty);return;}
    for(const item of items){const row=document.createElement('article');row.className='personal-notification'+(!item.read_at?' unread':'');
      const content=document.createElement('div'),title=document.createElement('strong'),meta=document.createElement('small'),body=document.createElement('p'),actions=document.createElement('div');actions.className='personal-actions';
      title.textContent=item.client;meta.textContent=`${item.kind==='mention'?'Mention':item.kind==='membership'?'Added to job':'Job comment'} · ${item.actor} · ${new Date(item.created_at).toLocaleString()}`;
      body.textContent=item.body;content.append(title,document.createElement('br'),meta,body);row.append(content,actions);feed.append(row);
      function button(label,fn){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=async()=>{b.disabled=true;try{await fn();}catch(e){status(e.message||'Action was not confirmed. Refresh and retry.');}finally{b.disabled=false;}};actions.append(b);return b;}
      button('Open job',async()=>{window.parent.postMessage({type:'linguar-open-job',client:item.client,cardId:item.card_id,division:item.division},'*');});
      button('Read message',async()=>window.NotificationReader?.open(item,async()=>{window.parent.postMessage({type:'linguar-open-job',client:item.client,cardId:item.card_id,division:item.division},'*');return true;}));
      button(item.read_at?'Mark unread':'Mark read',async()=>{const result=await pywebview.api.personal_read(item.id,!item.read_at);if(!result?.ok)throw Error(result?.error||'Read status was not saved.');item.read_at=item.read_at?null:new Date().toISOString();if(get('personal-unread').checked)items=items.filter(i=>!i.read_at);render();status('Read status saved across PCs.');});
      button(item.muted?'Unmute job':'Mute job',async()=>{const result=await pywebview.api.personal_mute(item.card_id,!item.muted);if(!result?.ok)throw Error(result?.error||'Mute was not saved.');const muted=!item.muted;await load();status(muted?'This job is muted, including mentions.':'Notifications enabled for this job.');});
    }
  }
  async function load(){const token=++generation;get('personal-refresh').disabled=true;status('Checking your inbox…');
    try{const result=await pywebview.api.personal_inbox(get('personal-filter').value,get('personal-unread').checked);if(token!==generation)return;if(!result?.ok)throw Error(result?.error||'Your inbox could not load.');items=result.items||[];render();status(`Latest ${items.length} notifications · refresh to check for new activity.${result.pending_delivery?' '+result.pending_delivery+' comment notification deliveries pending on this PC. Refresh to retry.':''}`);}
    catch(e){if(token===generation)status(e.message);}finally{if(token===generation)get('personal-refresh').disabled=false;}
  }
  window.addEventListener('pywebviewready',()=>{
    get('personal-refresh').onclick=load;get('personal-filter').onchange=load;get('personal-unread').onchange=load;
    get('personal-source').onclick=()=>{get('personal-panel').hidden=false;get('trello-panel').hidden=true;get('personal-source').setAttribute('aria-pressed','true');get('trello-source').setAttribute('aria-pressed','false');};
    get('trello-source').onclick=()=>{get('personal-panel').hidden=true;get('trello-panel').hidden=false;get('personal-source').setAttribute('aria-pressed','false');get('trello-source').setAttribute('aria-pressed','true');window.dispatchEvent(new Event('trello-notifications-open'));};
    load();
  });
})();
