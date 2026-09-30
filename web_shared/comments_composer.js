/* Shared drawer controls. Exact card IDs, per-card drafts, explicit send targets. */
window.SharedComments = (() => {
  const divisions = ['EMS', 'CONTENTS', 'RECON'];
  const label = value => ({CONTENTS:'Contents', RECON:'Recon', EMS:'EMS'})[value] || value;
  function mount(root, reload) {
    const input = root.querySelector('#cmt-new');
    const send = root.querySelector('#cmt-post');
    const compose = root.querySelector('.cmt-compose');
    compose.classList.add('comment-compose');
    const views = document.createElement('div'); views.className='drawer-divisions';
    views.setAttribute('aria-label','Read comments from division'); views.setAttribute('role','group');
    root.querySelector('.cmt-filter').before(views);
    const targets = document.createElement('div'); targets.className='drawer-destinations';
    targets.setAttribute('aria-label','Send comment to divisions'); targets.setAttribute('role','group');
    root.querySelector('.cmt-btns').prepend(targets);
    const status=document.createElement('small');status.className='drawer-comment-status';status.setAttribute('role','status');compose.append(status);
    let row=null, cards=[], selected=new Set(), serial=0, sending=false;
    const key=()=>row?.trello_card_id ? 'oneloss.comment-draft.'+row.trello_card_id : '';
    function save(){try{if(key()){if(input.value)localStorage.setItem(key(),input.value);else localStorage.removeItem(key());}}catch(_){}}
    input.addEventListener('input',save);
    function paint(){
      views.replaceChildren(); targets.replaceChildren(); targets.append('Send to ');
      for(const division of divisions){
        const card=cards.find(c=>c.division===division);
        for(const [container,isTarget] of [[views,false],[targets,true]]){
          const button=document.createElement('button');button.type='button';button.textContent=label(division);
          button.disabled=!card || sending;button.title=card?'':'No verified linked card';
          button.setAttribute('aria-pressed',String(isTarget?selected.has(card?.card_id):card?.card_id===row?.trello_card_id));
          if(isTarget)button.dataset.commentDestination=division;
          button.onclick=()=>{if(isTarget){selected.has(card.card_id)?selected.delete(card.card_id):selected.add(card.card_id);paint();}
            else reload({...row,trello_card_id:card.card_id,division},false);};
          container.append(button);
        }
      }
      send.disabled=sending||!selected.size;
    }
    input._mentionTargets=()=>cards.filter(c=>selected.has(c.card_id)).map(c=>({cardId:c.card_id,division:c.division,board:c.board||label(c.division)}));
    window.CommentMarkdown?.mount(input);
    input._richEditor?.editor.view.dom.addEventListener('keydown',event=>{
      if(!event.defaultPrevented&&event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();send.click();}
    });
    async function select(next){
      if(row?.trello_card_id===next.trello_card_id&&row?.client===next.client){row=next;return;}
      save(); row={...next};const request=++serial;
      try{input.value=localStorage.getItem(key())||'';}catch(_){input.value='';}
      const current=String(next.division||'EMS').toUpperCase();
      cards=[{division:current,card_id:next.trello_card_id}];selected=new Set([next.trello_card_id]);status.textContent='';paint();
      try{
        const result=await pywebview.api.comment_destinations(next.client);
        if(request!==serial)return;
        const linked=(result?.cards||[]).filter(c=>c.card_id&&c.pinned!==false&&!c.conflict&&divisions.includes(c.division));
        const exact=linked.find(c=>c.card_id===next.trello_card_id);
        const actual=exact?.division||current;
        const others=linked.filter(c=>c.division!==actual&&c.card_id!==next.trello_card_id);
        cards=[{division:actual,card_id:next.trello_card_id},...others.filter(c=>others.filter(other=>other.card_id===c.card_id||other.division===c.division).length===1)];
        if(!result?.ok)status.textContent='Linked destinations unavailable; the selected card is still available.';
        paint();
      }catch(_){if(request===serial)status.textContent='Linked destinations unavailable; the selected card is still available.';}
    }
    async function post(){
      if(sending||!row||!input.value.trim()||!selected.size)return;
      const origin={...row},body=input.value,ids=[...selected],request=serial;
      sending=true;paint();status.textContent='Sending…';
      const failed=[],warnings=[];
      for(const id of ids){try{const result=await pywebview.api.drawer_post(origin.client,id,body.trim());if(!result?.ok)failed.push(id);else if(result.notification_warning)warnings.push(result.notification_warning);}catch(_){failed.push(id);}}
      sending=false;
      if(request!==serial){
        if(!failed.length)try{const oldKey='oneloss.comment-draft.'+origin.trello_card_id;if(localStorage.getItem(oldKey)===body)localStorage.removeItem(oldKey);}catch(_){}
        paint();return;
      }
      if(failed.length){selected=new Set(failed);status.textContent='Some destinations were not confirmed. Draft kept; only unconfirmed destinations remain selected. Check their threads before retrying.';}
      else{if(input.value===body){input.value='';save();}status.textContent=warnings.length?warnings.join(' '):'Posted to Trello.';}
      paint();
      if(!failed.includes(origin.trello_card_id))reload(origin,true);
    }
    return {select,post,save};
  }
  return {mount};
})();
