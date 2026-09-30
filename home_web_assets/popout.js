(()=>{
  const query=new URLSearchParams(location.search),frame=document.getElementById('tool');
  const status=text=>document.getElementById('popout-status').textContent=text;
  window.addEventListener('pywebviewready',async()=>{
    try{
      const result=await pywebview.api.popout_source(query.get('tool'));
      if(!result?.ok)throw Error('Tool unavailable.');
      const url=new URL(result.src,location.href);
      if(query.get('cardId')){
        url.searchParams.set('job_workspace','1');url.searchParams.set('card_id',query.get('cardId'));
        url.searchParams.set('focus',query.get('client')||'Job');
        url.searchParams.set('division',query.get('division')||'EMS');
        if(query.get('commentId'))url.searchParams.set('comment_id',query.get('commentId'));
      }
      frame.src=url.href;
    }catch(e){status(e.message);}
  });
  window.addEventListener('message',async event=>{
    if(event.source!==frame.contentWindow||event.origin!==location.origin)return;
    const d=event.data||{};let tool,context={};
    if(['ems-open-tool-modal','ems-navigate','linguar-open-daily-run'].includes(d.type)){
      try{await pywebview.api.popout_navigate_main(d);}catch(e){status(e.message);}return;
    }
    if(d.type==='linguar-open-job'){tool='pipeline';context=d;}
    else if(d.type==='ems-navigate'){tool=d.key==='audit'?'pipeline':d.key;context={client:d.focus};}
    else if(d.type==='linguar-open-daily-run')tool='daily_run';
    else if(d.type==='linguar-close-job-workspace'){status('You can close this window. The main app stays open.');return;}
    if(tool){try{const result=await pywebview.api.open_popout(tool,context);if(!result?.ok)status(result?.error||'Window unavailable.');}catch(e){status(e.message);}}
  });
})();
