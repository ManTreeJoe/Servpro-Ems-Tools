/* Suggestions are scoped to exact Send-to card IDs, never a customer-name pin. */
let nextId=0;
export function mentions(editor, source, box) {
  const panel=document.createElement('div');panel.className='comment-mention-panel';panel.hidden=true;
  const status=document.createElement('div');status.className='comment-mention-status';status.setAttribute('role','status');
  const list=document.createElement('div');list.setAttribute('role','listbox');list.setAttribute('aria-label','Mention suggestions');
  list.id='comment-mentions-'+(++nextId);
  panel.append(status,list);box.append(panel);
  const cache=new Map();let serial=0,hits=[],index=0,current=null,dismissed='',disposed=false;
  const targetKey=()=>JSON.stringify((source._mentionTargets?.()||[]).map(t=>[t.cardId,t.division,t.board]));
  function token(){
    if(editor.isDestroyed||!editor.isFocused||!editor.state.selection.empty||editor.isActive('code')||editor.isActive('codeBlock'))return null;
    const {$from}=editor.state.selection;
    const before=$from.parent.textBetween(0,$from.parentOffset,'\n','\ufffc');
    const match=/(?:^|[\s(\[])@([A-Za-z0-9_.-]*)$/.exec(before);
    if(!match)return null;
    return {from:$from.pos-match[1].length-1,to:$from.pos,term:match[1].toLowerCase()};
  }
  const key=t=>t?`${t.from}:${t.to}:${t.term}:${targetKey()}`:'';
  function hide(){serial++;panel.hidden=true;hits=[];current=null;editor.view.dom.removeAttribute('aria-activedescendant');editor.view.dom.setAttribute('aria-expanded','false');}
  function highlight(){
    [...list.children].forEach((button,i)=>button.setAttribute('aria-selected',String(i===index)));
    if(hits.length)editor.view.dom.setAttribute('aria-activedescendant',list.children[index].id);
    const selected=list.children[index];
    if(selected){
      const top=selected.offsetTop-list.offsetTop,bottom=top+selected.offsetHeight;
      if(top<list.scrollTop)list.scrollTop=top;
      else if(bottom>list.scrollTop+list.clientHeight)list.scrollTop=bottom-list.clientHeight;
    }
  }
  function insert(row){
    const now=token();if(!now||key(now)!==key(current))return hide();
    const range={from:now.from,to:now.to};hide();
    editor.chain().focus().insertContentAt(range,[{type:'text',text:`@${row.username} `}]).run();
  }
  async function load(target){
    function sourceCall(method){
      const key=method+':'+target.cardId,cached=cache.get(key);
      if(cached&&Date.now()-cached.at<300000)return cached.promise;
      const promise=Promise.resolve().then(()=>window.pywebview.api[method](target.cardId)).then(result=>{
        if(!result?.ok)throw Error('People unavailable');return result;
      }).catch(error=>{cache.delete(key);throw error;});
      cache.set(key,{at:Date.now(),promise});return promise;
    }
    return Promise.allSettled([
      sourceCall('job_comment_members'),sourceCall('oneloss_comment_members')
    ]).then(results=>{
      const rows=[];let missing=false;
      results.forEach((result,i)=>{if(result.status==='fulfilled'&&result.value?.ok){for(const member of result.value.members||[])rows.push({...member,source:i?'OneLoss':'Trello'});}else missing=true;});
      if(!rows.length&&results.every(result=>result.status!=='fulfilled'||!result.value?.ok))throw Error('People could not be loaded.');
      return {rows,missing};
    });
  }
  async function update(){
    const next=token(),signature=key(next);
    if(!next){dismissed='';hide();return;}
    if(signature===dismissed)return;
    const targets=source._mentionTargets?.()||[];
    const request=++serial;current=next;hits=[];list.replaceChildren();panel.hidden=false;
    editor.view.dom.setAttribute('aria-controls',list.id);editor.view.dom.setAttribute('aria-expanded','true');editor.view.dom.removeAttribute('aria-activedescendant');
    status.textContent=targets.length?'Loading people…':'Choose a Send to destination to tag someone.';
    if(!targets.length)return;
    try{
      const rows=await Promise.all(targets.map(async target=>({target,rows:await load(target)})));
      if(disposed||request!==serial||signature!==key(token()))return;
      const people=new Map();
      for(const {target,rows:result}of rows)for(const member of result.rows){
        if(!/^[A-Za-z0-9_.-]+$/.test(member.username||''))continue;
        const id=member.source+':'+member.username.toLowerCase(),label=target.board||target.division;
        if(!people.has(id))people.set(id,{...member,boards:new Set()});people.get(id).boards.add(label);
      }
      hits=[...people.values()].filter(row=>`${row.name} ${row.username}`.toLowerCase().includes(next.term)).sort((a,b)=>a.name.localeCompare(b.name)).slice(0,8);index=0;
      status.textContent=hits.length?'People on selected boards':'No matching people on the selected boards.';
      if(rows.some(row=>row.rows.missing))status.textContent+=' Some people could not load. Reopen suggestions to retry.';
      for(const [i,row]of hits.entries()){
        const button=document.createElement('button');button.type='button';button.setAttribute('role','option');button.id=`${list.id}-${i}`;button.tabIndex=-1;
        const name=document.createElement('strong');name.textContent=row.name||row.username;
        const detail=document.createElement('small');detail.textContent=`${row.source} · @${row.username} · ${[...row.boards].join(', ')}`;
        button.append(name,detail);button.addEventListener('mousedown',event=>event.preventDefault());button.onclick=()=>insert(row);list.append(button);
      }
      highlight();
    }catch(_){
      if(disposed||request!==serial||signature!==key(token()))return;
      status.textContent='Could not load Trello people. ';
      const retry=document.createElement('button');retry.type='button';retry.textContent='Retry';retry.onmousedown=event=>event.preventDefault();retry.onclick=()=>{cache.clear();update();};status.append(retry);
    }
  }
  function keyboard(event){
    if(panel.hidden||event.isComposing)return;
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();dismissed=key(token());hide();}
    else if(hits.length&&['ArrowDown','ArrowUp','Enter','Tab'].includes(event.key)){
      event.preventDefault();event.stopPropagation();
      if(event.key==='Enter'||event.key==='Tab')insert(hits[index]);
      else{index=(index+(event.key==='ArrowDown'?1:-1)+hits.length)%hits.length;highlight();}
    }
  }
  function blur(){hide();}
  function destinations(event){if(event.target.closest('[data-comment-destination],[data-comment-placement]')){hide();}}
  const compose=source.closest('.comment-compose');
  editor.on('update',update);editor.on('selectionUpdate',update);editor.on('focus',update);editor.on('blur',blur);
  editor.view.dom.addEventListener('keydown',keyboard,true);compose.addEventListener('click',destinations);
  return {destroy(){disposed=true;serial++;editor.off('update',update);editor.off('selectionUpdate',update);editor.off('focus',update);editor.off('blur',blur);editor.view.dom.removeEventListener('keydown',keyboard,true);compose.removeEventListener('click',destinations);panel.remove();cache.clear();}};
}
