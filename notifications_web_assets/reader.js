window.NotificationReader=(()=>{
  const markdown=text=>window.CommentMarkdown?.display(text)||String(text||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
  function open(item,openJob,error=''){
    document.getElementById('notification-reader')?.close();
    const prior=document.activeElement,dialog=document.createElement('dialog');dialog.id='notification-reader';
    dialog.innerHTML='<header><div><small>Notification</small><h2></h2></div><button data-close aria-label="Close message">×</button></header><div class="notification-reader-body comment-markdown"></div><footer><span role="status"></span><button class="btn" data-open>Open job at comment</button></footer>';
    dialog.querySelector('h2').textContent=item.card_name||item.client||'Job activity';dialog.querySelector('.notification-reader-body').innerHTML=markdown(item.snippet||item.body||'');
    dialog.querySelector('[role=status]').textContent=error;
    dialog.querySelector('[data-close]').onclick=()=>dialog.close();
    dialog.addEventListener('close',()=>{dialog.remove();prior?.focus();});
    dialog.querySelector('[data-open]').onclick=async event=>{event.target.disabled=true;try{if(await openJob())dialog.close();}finally{event.target.disabled=false;}};
    dialog.querySelector('.notification-reader-body').onclick=e=>{const a=e.target.closest('a');if(a){e.preventDefault();if(/^(https?:|mailto:)/i.test(a.href))pywebview.api.open_url(a.href);}};
    if(item.card_url){const b=document.createElement('button');b.className='btn';b.textContent='Open in Trello';b.onclick=()=>pywebview.api.open_url(item.card_url+(item.comment_id?'#comment-'+item.comment_id:''));dialog.querySelector('footer').append(b);}
    document.body.append(dialog);dialog.showModal();
  }
  return {open,markdown};
})();
