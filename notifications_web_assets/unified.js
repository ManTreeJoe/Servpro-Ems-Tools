/* One inbox; provider identity stays internal for routing read/mute writes. */
(()=>{'use strict';
 const get=id=>document.getElementById(id),feeds={personal:[],trello:[]},pending=new Set();
 let generation=0,loading=false,bulkClearing=false,items=[],view='all',selectedBoards=null,liveRefreshTimer=null,feedRendered=false;
 const unknownBoard='Unassigned board';
 const boardName=item=>item.board||unknownBoard;
 const saveFilters=()=>window.PanelState?.set({notificationBoards:selectedBoards,notificationView:view,notificationUnread:get('unread-only').checked});
 const expanded=new Set(),opening=new Map();
 const previewObserver=new ResizeObserver(entries=>{
   for(const {target} of entries){
     const control=target.parentElement?.querySelector('.notification-expand');
     if(control?.classList.contains('notification-expand'))
       control.hidden=!target.classList.contains('expanded')&&target.scrollHeight<=target.clientHeight+1;
   }
 });
 const status=message=>get('status-msg').textContent=message;
 const api=()=>window.pywebview.api;
 let countRequest=0;
 async function refreshUnread(){
   const request=++countRequest;let count=null;
   try{const result=await api().unread_count();if(result?.ok&&Number.isSafeInteger(result.count)&&result.count>=0)count=result.count;}catch{}
   if(request!==countRequest)return;
   const pill=get('unread-pill');pill.textContent=count===null?'—':String(count);
   pill.title=count===null?'Unread count unavailable':`${count} unread notifications across Trello and OneLoss`;
   pill.setAttribute('aria-label',pill.title);pill.classList.toggle('zero',count===0);
   window.parent.postMessage({type:'oneloss-notifications-count',count},'*');
 }
 function rebuild(){
   const boards=new Map(feeds.trello.filter(x=>x.card_id).map(x=>[x.card_id,x.board]));
   const merged=new Map();
   for(const [source,rows] of Object.entries(feeds))for(const raw of rows){
     const isComment=['comment','mention','commentCard','mentionedOnCard'].includes(raw.kind||raw.type);
     const key=isComment&&raw.card_id&&raw.comment_id?`comment:${raw.card_id}:${raw.comment_id}`:`${source}:${raw.id}`;
     const ref={source,raw},date=raw.created_at||raw.date||'';
     const item=merged.get(key)||{key,refs:[],date,title:raw.client||raw.card_name||'Job activity',board:raw.board||boards.get(raw.card_id)||'',body:'',actor:raw.actor||raw.by||'',kind:raw.kind||raw.type,type:raw.type,unread:false};
     item.refs.push(ref);item.unread ||= source==='personal'?!raw.read_at:!!raw.unread;
     if(date>item.date)item.date=date;
     const body=raw.body||raw.snippet||'';if(body.length>item.body.length)item.body=body;
     if(raw.kind==='mention'||raw.type==='mentionedOnCard')item.kind=item.type='mention';
     item.is_move ||= raw.is_move;
     merged.set(key,item);
   }
   items=[...merged.values()].map(item=>({...item,body:item.body.trim()?item.body:'Update details unavailable. Open the card to check.'})).sort((a,b)=>b.date.localeCompare(a.date)||a.key.localeCompare(b.key));
 }
 function visible(){return items.filter(item=>(!get('unread-only').checked||item.unread)&&(selectedBoards===null||selectedBoards.includes(boardName(item)))&&(view!=='mentions'||window.NotificationTypes.category(item)==='tags'));}
 function renderBoards(){
   const choices=get('notification-board-options');
   const names=[...new Set([...items.map(boardName),...(selectedBoards||[])])].sort();
   choices.replaceChildren();
   const all=element('label'),allCheck=document.createElement('input');allCheck.type='checkbox';allCheck.checked=selectedBoards===null;
   allCheck.onchange=()=>{selectedBoards=allCheck.checked?null:[];saveFilters();render();};
   all.append(allCheck,document.createTextNode('All boards'));choices.append(all);
   for(const name of names){
     const label=element('label'),check=document.createElement('input');check.type='checkbox';
     check.checked=selectedBoards===null||selectedBoards.includes(name);
     check.onchange=()=>{
       const next=new Set(selectedBoards===null?names:selectedBoards);
       if(check.checked)next.add(name);else next.delete(name);
       selectedBoards=[...next];saveFilters();render();
     };
     label.append(check,document.createTextNode(name));choices.append(label);
   }
   get('notification-board-summary').textContent=selectedBoards===null?'All boards':selectedBoards.length===1?selectedBoards[0]:`${selectedBoards.length} boards`;
 }
 function element(tag,text,className){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;}
 function notificationDate(value){
   const date=value?new Date(value):null;
   if(!date||Number.isNaN(date.getTime()))return {key:'unknown',label:'Date unavailable',time:'',full:''};
   // Group by the viewer's local calendar day, not the UTC date substring.
   const key=`${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
   return {key,label:date.toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}),
     time:date.toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'}),full:date.toLocaleString()};
 }
 function button(label,action){const b=element('button',label,'mark-btn');b.type='button';b.onclick=async()=>{b.disabled=true;try{await action();}catch(e){status(e.message||'Action could not be confirmed. Refresh and retry.');}finally{b.disabled=false;}};return b;}
 async function mark(item,read=true){
   if(pending.has(item.key))return false;
   pending.add(item.key);generation++;render();
   try{
     for(const ref of item.refs){
       const unread=ref.source==='personal'?!ref.raw.read_at:!!ref.raw.unread;
       if(unread!==read)continue;
       const result=await (ref.source==='personal'?api().personal_read(ref.raw.id,read):api().mark_read(ref.raw.id,read));
       if(!result?.ok)throw Error(result?.error||'Read status was not saved.');
       if(ref.source==='personal')ref.raw.read_at=read?new Date().toISOString():null;else ref.raw.unread=!read;
     }
     window.parent.postMessage({type:'oneloss-notifications-changed'},'*');return true;
   }finally{pending.delete(item.key);rebuild();render();void refreshUnread();}
 }
 async function openJob(item){
   const raw=item.refs.find(r=>r.raw.card_id)?.raw||item.refs[0].raw;
   try{
     const result=await api().notification_job(raw.card_id,raw.comment_id||'');
     if(!result?.ok)throw Error(result?.error||'Job could not open.');
     status('Opening card…');
     const token=crypto.randomUUID();
     opening.set(token,item);
     setTimeout(()=>opening.delete(token),60000);
     window.parent.postMessage({type:'linguar-open-job',...result,notificationToken:token},'*');
     return true;
   }catch(e){status(e.message);return false;}
 }
 window.addEventListener('message',async event=>{
   if(event.source===window.parent&&event.data?.type==='oneloss-notification-board-changed'){
     const refreshWhenIdle=()=>{
       if(loading||bulkClearing||pending.size||document.querySelector('.emoji-picker')||window.CommentReactions?.isBusy()){
         liveRefreshTimer=setTimeout(refreshWhenIdle,1000);return;
       }
       liveRefreshTimer=null;void load();
     };
     clearTimeout(liveRefreshTimer);liveRefreshTimer=setTimeout(refreshWhenIdle,100);return;
   }
   if(event.source!==window.parent||event.data?.type!=='oneloss-notification-opened')return;
   const opened=opening.get(event.data.token);if(!opened)return;
   const item=items.find(item=>item.key===opened.key)||opened;
   opening.delete(event.data.token);
   try{await mark(item);status('Card opened · notification marked read.');}catch(e){status(e.message);}
 });
 window.addEventListener('pagehide',()=>clearTimeout(liveRefreshTimer),{once:true});
 function render(){
   previewObserver.disconnect();
   renderBoards();
   document.querySelectorAll('[data-notification-view]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.notificationView===view)));
   const feed=get('feed'),scroll=feed.scrollTop,list=element('ul',undefined,'notif-list'),shown=visible();
   const groups=new Map();
   for(const item of shown){
     const card=item.refs.find(ref=>ref.raw.card_id)?.raw.card_id;
     const key=card||item.key;
     if(!groups.has(key))groups.set(key,[]);
     groups.get(key).push(item);
   }
   for(const group of groups.values()){
    const first=group[0],section=element('li',undefined,'notification-job');
    const heading=element('header',undefined,'notification-job-head');
    heading.append(button(first.title,()=>openJob(first)),element('small',boardName(first)));
    heading.classList.toggle('has-unread',group.some(item=>item.unread));
    const events=element('ul',undefined,'notification-events');section.append(heading,events);list.append(section);
    let previousDay=null;
    for(const item of group){
     const displayDate=notificationDate(item.date);
     if(displayDate.key!==previousDay){
       events.append(element('li',displayDate.label,'notification-date-divider'));
       previousDay=displayDate.key;
     }
     const row=element('li',undefined,'notif '+(item.unread?'unread':'read'));row.dataset.notificationKey=item.key;
     const linked=item.refs.find(ref=>ref.raw.card_id)?.raw;
     if(linked){row.dataset.popoutTool='pipeline';row.dataset.popoutContext=JSON.stringify({
       cardId:linked.card_id,client:item.title,commentId:linked.comment_id||''});}
     const category=window.NotificationTypes.category(item),labels={tags:'Mention',messages:'Comment',moves:'Card move',reactions:'Reaction',other:'Activity'};
     const initials=String(item.actor||'?').trim().split(/\s+/).slice(0,2).map(part=>part[0]).join('').toUpperCase();
     const icon=element('span',initials,'notif-avatar');icon.setAttribute('aria-hidden','true');
     const content=element('div',undefined,'notif-body');
     const meta=element('div',undefined,'notif-meta');
     meta.append(element('strong',item.actor||labels[category]));
     if(category==='reactions')meta.append(element('span','reacted to a comment','notification-event-label'));
     const date=element('time',displayDate.time,'notif-date');
     if(displayDate.full){date.dateTime=item.date;date.title=displayDate.full;date.setAttribute('aria-label',displayDate.full);}meta.append(date);
     const body=element('div',undefined,'notif-snippet');body.innerHTML=window.NotificationReader.markdown(item.body);
     body.onclick=e=>{
       const a=e.target.closest('a');if(a){e.preventDefault();if(/^(https?:\/\/|mailto:)/i.test(a.href))api().open_url(a.href);return;}
       if(window.getSelection()?.toString())return;
       void openJob(item);
     };
     body.tabIndex=0;body.setAttribute('role','button');body.setAttribute('aria-label',`Open ${item.title} at this update`);
     body.onkeydown=e=>{if(e.target===body&&(e.key==='Enter'||e.key===' ')){e.preventDefault();void openJob(item);}};
     row.classList.toggle('is-activity',!['tags','messages'].includes(category));
     body.classList.toggle('expanded',expanded.has(item.key));
     content.append(meta,body);
     // Only provider-backed comment identities may be used for Trello reactions.
     const reactionRef=item.refs.find(ref=>ref.source==='trello' &&
       ['commentCard','mentionedOnCard'].includes(ref.raw.type) &&
       /^[a-f\d]{24}$/i.test(ref.raw.comment_id||'') && ref.raw.card_id);
     if(reactionRef && window.CommentReactions){
       const raw=reactionRef.raw;
       row.classList.add('job-comment');
       row.dataset.commentSource='trello';row.dataset.commentId=raw.comment_id;
       row.dataset.commentCardId=raw.card_id;
       const reactions=element('div');
       reactions.innerHTML=window.CommentReactions.markup({source:'trello',id:raw.comment_id});
       content.append(reactions);
     }
     const more=button(expanded.has(item.key)?'Show less':'Show more',()=>{
       const isExpanded=!expanded.has(item.key);
       if(isExpanded)expanded.add(item.key);else expanded.delete(item.key);
       body.classList.toggle('expanded',isExpanded);more.textContent=isExpanded?'Show less':'Show more';
       more.setAttribute('aria-expanded',String(isExpanded));
     });
     more.classList.add('notification-expand');more.setAttribute('aria-expanded',String(expanded.has(item.key)));
     more.hidden=true;content.append(more);
     previewObserver.observe(body);
     const readToggle=button('',()=>mark(item,item.unread));
     readToggle.className='notification-read-toggle';
     readToggle.title=item.unread?'Mark read':'Mark unread';
     readToggle.setAttribute('aria-label',readToggle.title);
     readToggle.classList.toggle('is-unread',item.unread);
     meta.append(readToggle);
     row.append(icon,content);if(pending.has(item.key))row.querySelectorAll('button').forEach(b=>b.disabled=true);events.append(row);
    }
   }
   feed.replaceChildren(shown.length?list:element('div','No notifications match this view.','empty'));feed.scrollTop=scroll;
   get('mark-all-btn').disabled=bulkClearing||!!pending.size||!shown.some(i=>i.unread);
   get('clear-all-btn').disabled=bulkClearing||loading||!!pending.size;
 }
 async function load(){
   if(loading||bulkClearing||pending.size||document.querySelector('.emoji-picker')||window.CommentReactions?.isBusy())return;loading=true;const token=++generation;get('refresh-btn').disabled=true;get('clear-all-btn').disabled=true;status('Checking notifications…');
   void refreshUnread();
   try{
     const results=await Promise.allSettled([Promise.resolve().then(()=>api().personal_inbox('all',false)),Promise.resolve().then(()=>api().list_notifications(false,80))]);
     if(token!==generation)return;
     const previous=JSON.stringify(feeds);
     let failures=0;
     results.forEach((result,index)=>{
       if(result.status!=='fulfilled'||!result.value?.ok){failures++;return;}
       if(index===0)feeds.personal=result.value.items||[];
       else feeds.trello=(result.value.groups||[]).flatMap(g=>g.items.map(item=>({...item,board:g.board})));
     });
     if(!feedRendered||JSON.stringify(feeds)!==previous){rebuild();render();feedRendered=true;}
     status(failures?'Some notifications could not refresh. Previous messages are kept; try Refresh.':`${items.length} notifications loaded · ${items.filter(item=>item.unread).length} unread in this loaded batch`);
   }finally{loading=false;get('refresh-btn').disabled=false;get('clear-all-btn').disabled=bulkClearing||!!pending.size;}
 }
 window.addEventListener('pywebviewready',async()=>{
   await window.PanelState?.init('notifications');
   const saved=window.PanelState?.get('notificationBoards',null);
   selectedBoards=Array.isArray(saved)?saved.filter(name=>typeof name==='string'):null;
   view=window.PanelState?.get('notificationView','all')==='mentions'?'mentions':'all';
   get('unread-only').checked=!!window.PanelState?.get('notificationUnread',false);
   get('refresh-btn').onclick=load;
   get('unread-only').onchange=()=>{saveFilters();render();};
   document.querySelectorAll('[data-notification-view]').forEach(button=>button.onclick=()=>{view=button.dataset.notificationView;saveFilters();render();});
   get('mark-all-btn').onclick=async()=>{const shown=visible().filter(i=>i.unread);try{for(const item of shown)await mark(item);status('Shown notifications marked read.');}catch(e){status(e.message);}};
   get('clear-all-btn').onclick=async()=>{
     if(bulkClearing||loading||pending.size)return;
     if(document.querySelector('.emoji-picker')||window.CommentReactions?.isBusy()){status('Finish your reaction, then try again.');return;}
     if(!window.confirm('Mark all your Trello and OneLoss notifications read, including notifications not shown here?'))return;
     bulkClearing=true;generation++;render();get('refresh-btn').disabled=true;status('Marking Trello and OneLoss notifications read…');
     let result;
     try{result=await api().clear_all_sources();}catch{result={ok:false,trello:{ok:false},personal:{ok:false}};}
     bulkClearing=false;get('refresh-btn').disabled=false;
     await load();
     if(result?.ok)status('All Trello and OneLoss notifications marked read.');
     else{
       const failed=[!result?.trello?.ok?'Trello':'',!result?.personal?.ok?'OneLoss':''].filter(Boolean).join(' and ');
       status(`${failed || 'Some'} read status could not be confirmed. Refresh and retry; confirmed changes were kept.`);
     }
     window.parent.postMessage({type:'oneloss-notifications-changed'},'*');
   };
   void load();setInterval(()=>{if(!document.hidden)void load();},30000);
 });
})();
