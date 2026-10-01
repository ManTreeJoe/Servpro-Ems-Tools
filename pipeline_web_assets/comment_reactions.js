/* Explicit Trello reactions; floating picker with no background polling. */
window.CommentReactions = (() => {
  const states = new WeakMap();
  const snapshots = new Map(), mounted = new WeakSet(), pending = new Set();
  let reading = 0;
  function stateFor(box) {
    if(states.has(box))return states.get(box);
    const article=box.closest('.job-comment');
    if(!article)return {};
    const card=article.dataset.commentCardId,id=article.dataset.commentSource==='trello'?article.dataset.commentId:article.dataset.commentExternalId;
    const key=JSON.stringify([card,id]);
    if(!snapshots.has(key))snapshots.set(key,{card,id});
    const state=snapshots.get(key);states.set(box,state);
    // Retain only a bounded page-session cache. Never persist account reaction state.
    if(snapshots.size>300)for(const [old,value] of snapshots){if(!value.busy&&old!==key){snapshots.delete(old);break;}}
    return state;
  }
  function repaint(state) {
    document.querySelectorAll('.comment-reactions').forEach(box=>{if(stateFor(box)===state)paint(box);});
  }
  function drain() {
    while(reading<2&&pending.size){
      const box=pending.values().next().value;pending.delete(box);
      if(!box.isConnected)continue;
      const state=stateFor(box);
      if(state.busy||Date.now()-(state.checkedAt||0)<30000)continue;
      reading++;load(box).finally(()=>{reading--;drain();});
    }
  }
  const visible = new IntersectionObserver(entries=>{
    for(const entry of entries)if(entry.isIntersecting){visible.unobserve(entry.target);pending.add(entry.target);}
    drain();
  });
  function mount(box) {
    if(mounted.has(box))return;mounted.add(box);stateFor(box);paint(box);visible.observe(box);
  }
  const hydration = new MutationObserver(records=>{
    for(const record of records)for(const node of record.addedNodes){
      if(node.nodeType!==1)continue;
      if(node.matches('.comment-reactions'))mount(node);
      node.querySelectorAll('.comment-reactions').forEach(mount);
    }
    for(const record of records)for(const node of record.removedNodes){
      if(node.nodeType!==1)continue;
      if(node.matches('.comment-reactions'))visible.unobserve(node);
      node.querySelectorAll('.comment-reactions').forEach(box=>visible.unobserve(box));
    }
  });
  hydration.observe(document.documentElement,{childList:true,subtree:true});
  let popup=null, owner=null, observer=null, recent=[];
  try {recent=JSON.parse(localStorage.getItem('oneloss.recentEmoji')||'[]');if(!Array.isArray(recent))recent=[];}catch(_){}
  function markup(comment) {
    const id=comment?.source==='trello'?comment.id:comment?.external_id;
    return /^[a-f\d]{24}$/i.test(id||'')?'<div class="comment-reactions"><span class="reaction-counts"></span><button type="button" class="text-btn" data-reactions-open aria-haspopup="dialog" aria-expanded="false">☺ React</button><small class="reaction-message" role="status"></small></div>':'';
  }
  function button(text,label,fn){const b=document.createElement('button');b.type='button';b.textContent=text;b.title=label;b.setAttribute('aria-label',label);b.onclick=fn;return b;}
  function close(focus=false){const trigger=owner?.querySelector('[data-reactions-open]');trigger?.setAttribute('aria-expanded','false');popup?.remove();popup=null;owner=null;observer?.disconnect();observer=null;if(focus&&trigger?.isConnected)trigger.focus();}
  function position(){
    if(!popup||!owner?.isConnected){close();return;}
    const r=owner.getBoundingClientRect(),h=popup.offsetHeight,w=popup.offsetWidth;
    popup.style.left=Math.max(8,Math.min(r.left,innerWidth-w-8))+'px';
    popup.style.top=Math.max(8,Math.min(r.bottom+6+h>innerHeight?r.top-h-6:r.bottom+6,innerHeight-h-8))+'px';
  }
  function paint(box){
    const s=states.get(box)||{},counts=box.querySelector('.reaction-counts');counts.replaceChildren();
    for(const row of s.rows||[]){const b=button(`${row.emoji||'☺'} ${row.count}`,`${row.mine?'Remove':'Add'} reaction · ${(row.people||[]).join(', ')}`,()=>load(box,row.code));b.dataset.reactionCode=row.code;b.setAttribute('aria-pressed',String(row.mine));b.disabled=!!s.busy||!!s.error;counts.append(b);}
    box.querySelector('.reaction-message').textContent=s.busy&&s.writing?'Saving…':s.error||'';
    if(owner===box)draw();
  }
  async function load(box,code){
    const s=stateFor(box);if(s.busy||code&&(!s.rows||s.error))return;
    const article=box.closest('.job-comment'),active=!s.rows?.find(r=>r.code===code)?.mine;
    s.busy=true;s.writing=!!code;s.error='';states.set(box,s);if(code&&owner===box)close(true);paint(box);
    try{
      const card=article.dataset.commentCardId,id=article.dataset.commentSource==='trello'?article.dataset.commentId:article.dataset.commentExternalId;
      if(!card)throw Error();
      const result=await window.pywebview.api.job_comment_reactions(card,id,code||null,code?active:null);
      if(!result?.ok)throw Error(result?.error||'Trello could not confirm reactions. Reopen React to check.');
      s.rows=result.reactions||[];s.choices=result.choices||[];s.account=result.account;
      if(code&&active){recent=[code,...recent.filter(c=>c!==code)].slice(0,16);try{localStorage.setItem('oneloss.recentEmoji',JSON.stringify(recent));}catch(_){}}
    }catch(e){s.error=e.message||'Trello is unavailable. Reopen React to check before trying again.';}
    finally{s.busy=false;s.checkedAt=Date.now();repaint(s);}
  }
  function draw(){
    if(!popup||!owner)return;
    const box=owner,s=states.get(box)||{},grid=popup.querySelector('.emoji-grid'),tabs=popup.querySelector('.emoji-categories');grid.replaceChildren();tabs.replaceChildren();
    popup.querySelector('[role=status]').textContent=s.busy?'Loading reactions…':s.error||`Reacting as ${s.account||'connected Trello account'}`;
    const q=popup.querySelector('input').value.toLowerCase().trim(),category=popup.dataset.category||'All',choices=s.choices||[];
    for(const group of ['All','Recent',...new Set(choices.map(c=>c.category))]){const tab=button(group,group,()=>{popup.dataset.category=group;draw();});tab.setAttribute('aria-pressed',String(category===group));tabs.append(tab);}
    const visible=(category==='Recent'?recent.map(code=>choices.find(c=>c.code===code)).filter(Boolean):choices).filter(c=>(q||category==='All'||category==='Recent'||c.category===category)&&(!q||`${c.name} ${c.category} ${c.emoji}`.toLowerCase().includes(q)));
    for(const c of visible){const b=button(c.emoji,c.name,()=>load(box,c.code));b.dataset.emojiCode=c.code;b.disabled=!!s.busy||!!s.error;b.setAttribute('aria-pressed',String(!!s.rows?.find(r=>r.code===c.code)?.mine));grid.append(b);}
    if(!visible.length&&!s.busy)grid.textContent=s.error?'Refresh to try again.':category==='Recent'&&!q?'Your recent reactions will appear here.':'No matching emojis.';
    popup.querySelector('[data-reactions-refresh]').disabled=!!s.busy;position();
  }
  function open(box){
    if(owner===box){close(true);return;}close();owner=box;box.querySelector('[data-reactions-open]').setAttribute('aria-expanded','true');
    popup=document.createElement('section');popup.className='emoji-picker';popup.setAttribute('role','dialog');popup.setAttribute('aria-label','Choose a Trello reaction');
    popup.innerHTML='<header><strong>React in Trello</strong></header><input type="search" placeholder="Search emojis…" aria-label="Search emojis"><div class="emoji-categories" role="group" aria-label="Emoji categories"></div><div class="emoji-grid" role="group" aria-label="Emojis"></div><footer><small role="status"></small><button type="button" data-reactions-refresh>Refresh</button></footer>';
    popup.querySelector('header').append(button('×','Close emoji picker',()=>close(true)));
    popup.querySelector('input').oninput=()=>{popup.dataset.category='All';draw();};popup.querySelector('[data-reactions-refresh]').onclick=()=>load(box);
    document.body.append(popup);draw();popup.querySelector('input').focus();
    observer=new MutationObserver(()=>{if(!box.isConnected)close();});observer.observe(document.body,{childList:true,subtree:true});load(box);
  }
  document.addEventListener('click',e=>{const trigger=e.target.closest('[data-reactions-open]');if(trigger)open(trigger.closest('.comment-reactions'));});
  document.addEventListener('pointerdown',e=>{if(popup&&!popup.contains(e.target)&&!owner?.contains(e.target))close();},true);
  document.addEventListener('keydown',e=>{
    if(!popup)return;
    if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();close(true);}
    if(e.key==='Tab'){
      const nodes=[...popup.querySelectorAll('button:not(:disabled),input')],i=nodes.indexOf(document.activeElement);
      if(i<0||!e.shiftKey&&i===nodes.length-1||e.shiftKey&&i===0){e.preventDefault();(e.shiftKey?nodes.at(-1):nodes[0]).focus();}e.stopImmediatePropagation();
    }
  },true);
  window.addEventListener('resize',position);
  document.addEventListener('scroll',e=>{if(popup&&!popup.contains(e.target))close();},true);
  document.querySelectorAll('.comment-reactions').forEach(mount);
  return {markup};
})();
