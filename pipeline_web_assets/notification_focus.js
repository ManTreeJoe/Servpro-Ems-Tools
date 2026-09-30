window.focusNotificationComment=async(workspace,cardId,commentId)=>{
  if(!workspace?.element?.isConnected)return;
  const root=workspace.element;
  const find=()=>[...root.querySelectorAll('[data-comment-id]')].find(row=>row.dataset.commentCardId===cardId&&(row.dataset.commentId===commentId||row.dataset.commentExternalId===commentId));
  let row=find();
  if(!row){
    const status=document.createElement('div');status.className='notification-comment-status';status.setAttribute('role','status');status.textContent='Finding the comment from your notification…';root.querySelector('[data-comment-stream]')?.before(status);
    try{
      const result=await pywebview.api.notification_comment(cardId,commentId);
      if(!root.isConnected)return;
      if(!result?.ok)throw Error(result?.error||'Comment unavailable.');
      workspace.conversation.add(cardId,result.comment);row=find();
      if(!row)throw Error('The comment is not visible in this conversation.');
      status.remove();
    }catch(e){status.textContent=e.message+' ';const button=document.createElement('button');button.textContent='Open in Trello';button.className='btn compact';button.onclick=()=>pywebview.api.open_url(`https://trello.com/c/${encodeURIComponent(cardId)}#comment-${encodeURIComponent(commentId)}`);status.append(button);return;}
  }
  row.hidden=false;row.classList.add('notification-comment-target');row.tabIndex=-1;
  const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches||document.documentElement.classList.contains('reduce-motion');
  row.scrollIntoView({behavior:reduce?'instant':'smooth',block:'center'});row.focus({preventScroll:true});
};
