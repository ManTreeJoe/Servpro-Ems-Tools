/* Read-only operational queues. Independent from the slower weekly audit. */
window.AnalyticsFlow=(()=>{
 let data=null, selected='', query='', board='', generation=0, enterPending=true;
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function bounded(promise){let timer;return Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('The read is taking too long. Retry when the connection recovers.')),30000);})]).finally(()=>clearTimeout(timer));}
 const duration=s=>s==null?'Unknown':s<3600?`${Math.floor(s/60)} min`:s<86400?`${Math.floor(s/3600)}h ${Math.floor(s%3600/60)}m`:`${Math.floor(s/86400)}d ${Math.floor(s%86400/3600)}h`;
 const date=s=>s?new Date(s).toLocaleString('en-US',{year:'2-digit',month:'2-digit',day:'2-digit',hour:'numeric',minute:'2-digit'}):'Still open / not recorded';
 const color=name=>/HOLD/.test(name)?'hold':/PENDING|TBS|TEST|SNAPSHOT|ASSIGNED/.test(name)?'waiting':'work';
 function bars(lanes,attribute='data-lane'){
  const max=Math.max(1,...lanes.map(l=>l.cards.length));
  return `<div class="flow-bars">${[...lanes].sort((a,b)=>b.cards.length-a.cards.length).map(l=>`<button class="flow-bar ${color(l.name)}" ${attribute}="${esc(l.id)}" aria-pressed="${l.id===selected}" aria-label="${esc(l.board)} / ${esc(l.name)}: ${l.cards.length} cards. Show cards."><span class="flow-bar-label">${esc(l.name)}<small>${esc(l.board)}</small></span><span class="flow-bar-track" aria-hidden="true"><i style="width:${l.cards.length/max*100}%"></i></span><strong>${l.cards.length}</strong></button>`).join('')||'<p>No lanes in this scope.</p>'}</div>`;
 }
 function paint(animate=false){
  const host=document.querySelector('#flow');
  if(!data){host.innerHTML='<p role="status">Loading Jobs queues…</p>';return;}
  const searched=data.lanes.map(l=>({...l,cards:l.cards.filter(c=>c.name.toLowerCase().includes(query.toLowerCase()))}));
  const lanes=searched.filter(l=>!board||l.board_id===board);
  const boards=[...new Map(searched.map(l=>[l.board_id,l.board])).entries()].map(([id,name])=>({id,name,count:searched.filter(l=>l.board_id===id).reduce((sum,l)=>sum+l.cards.length,0)}));
  const maxBoard=Math.max(1,...boards.map(b=>b.count));
  const estimating=lanes.filter(l=>l.board_key==='est'||l.board==='ESTIMATING');
  const lane=lanes.find(l=>l.id===selected);
  const cards=(lane?lane.cards:lanes.flatMap(l=>l.cards.map(c=>({...c,lane:l.name,board:l.board})))).filter(c=>c.name.toLowerCase().includes(query.toLowerCase()));
  host.innerHTML=`<div class="flow-heading"><div><h2>Where work is sitting</h2><p>Current card placements · not unique jobs or hours worked</p></div><span>${esc(data.location)} · ${data.stale?'Saved queues':'Updated queues'}</span></div>
   <div class="flow-controls"><label>Board<select id="flow-board"><option value="">All active boards (Recon deferred)</option>${[...new Map(data.lanes.map(l=>[l.board_id,l.board])).entries()].map(([id,name])=>`<option value="${esc(id)}" ${id===board?'selected':''}>${esc(name)}</option>`).join('')}</select></label><label>Find a card<input id="flow-search" type="search" value="${esc(query)}" placeholder="Job name"></label><button id="flow-all">All lanes</button></div>
   <div class="flow-chart-grid${animate?' flow-chart-enter':''}">
    <section class="flow-chart"><h3>Cards by board</h3><p>Search-matched placements across boards · click a column to select a board.</p><div class="flow-columns">${boards.map((b,i)=>`<button class="flow-column" data-chart-board="${esc(b.id)}" aria-pressed="${b.id===board}" aria-label="${esc(b.name)}: ${b.count} cards. Select board."><strong>${b.count}</strong><span class="flow-column-track" aria-hidden="true"><i style="height:${b.count/maxBoard*100}%;background:var(${['--cobalt','--violet','--amber'][i%3]})"></i></span><span>${esc(b.name)}</span></button>`).join('')||'<p>No boards available.</p>'}</div><small>Baseline 0 · tallest column ${maxBoard===1&&!boards.some(b=>b.count)?0:maxBoard} cards</small></section>
    <section class="flow-chart"><h3>Cards by lane</h3><p>Selected board scope · longest bar ${Math.max(0,...lanes.map(l=>l.cards.length))} cards · click a bar for the card list.</p>${bars(lanes)}</section>
    ${estimating.length?`<section class="flow-chart flow-chart-wide"><h3>Estimating queues</h3><p>Card counts, not performance scores. Shared lanes remain shared; unassigned and review queues are included.</p>${bars(estimating,'data-est-lane')}</section>`:''}
   </div>
   <p class="coverage">Time comes from recorded moves, not comments or last activity. Inspect a card to retrieve its lane history. Shared automatic tracking and dollar totals are not connected yet.</p>
   <div class="section-head"><h2>${esc(lane?.name||'All lanes')} <small>· ${cards.length} cards</small></h2></div>
   <div class="table-wrap"><table><thead><tr><th>Card</th><th>Current lane</th><th>Timing</th></tr></thead><tbody>${cards.map(c=>`<tr><td><button data-flow-open="${esc(c.id)}">${esc(c.name)}</button><small>${esc(c.board||lane.board)}</small></td><td>${esc(c.lane||lane.name)}</td><td><button data-history="${esc(c.id)}">Inspect timing</button></td></tr>`).join('')||'<tr><td colspan="3">No cards match this selection.</td></tr>'}</tbody></table></div>
   <dialog id="flow-history"><header><h2>Card timing</h2><button data-close-history aria-label="Close timing">×</button></header><div class="flow-history-body"></div></dialog>`;
  host.querySelector('#flow-board').onchange=e=>{board=e.target.value;selected='';paint();};
  host.querySelector('#flow-search').oninput=e=>{query=e.target.value;const pos=e.target.selectionStart;paint();const input=host.querySelector('#flow-search');input.focus();input.setSelectionRange?.(pos,pos);};
  host.querySelector('#flow-all').onclick=()=>{selected='';paint();};
  host.querySelectorAll('[data-lane],[data-est-lane]').forEach(b=>b.onclick=()=>{const attr=b.hasAttribute('data-lane')?'data-lane':'data-est-lane';selected=b.getAttribute(attr);const scroll=host.querySelector(`[${attr}]`)?.closest('.flow-bars')?.scrollTop||0;paint();const replacement=[...host.querySelectorAll(`[${attr}]`)].find(el=>el.getAttribute(attr)===selected);replacement?.focus({preventScroll:true});if(replacement)replacement.closest('.flow-bars').scrollTop=scroll;});
  host.querySelectorAll('[data-chart-board]').forEach(b=>b.onclick=()=>{board=b.dataset.chartBoard;selected='';paint();[...host.querySelectorAll('[data-chart-board]')].find(el=>el.dataset.chartBoard===board)?.focus({preventScroll:true});});
  host.querySelectorAll('[data-flow-open]').forEach(b=>b.onclick=()=>parent.postMessage({type:'linguar-open-job',cardId:b.dataset.flowOpen,focus:cards.find(c=>c.id===b.dataset.flowOpen)?.name||''},location.origin));
  host.querySelectorAll('[data-history]').forEach(b=>b.onclick=()=>inspect(b.dataset.history));
  host.querySelector('[data-close-history]').onclick=()=>host.querySelector('dialog').close();
 }
 async function inspect(id){
  const dialog=document.querySelector('#flow-history'),body=dialog.querySelector('.flow-history-body');
  dialog.showModal();body.textContent='Reading recorded moves…';
  try{const result=await bounded(pywebview.api.flow_history(id));if(!dialog.isConnected||!dialog.open)return;if(!result.ok)throw Error(result.error);
   const current=result.periods.find(p=>p.current),cycles=result.estimator_cycles||[];
   body.innerHTML=`<div class="timing-title"><div><small>JOB MOVEMENT HISTORY</small><h3>${esc(result.name)}</h3><p>${current?esc(current.board)+' / '+esc(current.lane):'Current entry time not verified'}</p></div><div class="timing-current"><small>Time in current lane</small><strong>${duration(result.current_seconds)}</strong></div></div>
   <section class="timing-section"><h3>Estimating → Logs</h3><p class="timing-muted">Elapsed time through estimating. The clock stops at Logs—not Billed.</p><div class="timing-cycles">${cycles.map(c=>`<article class="timing-cycle"><div><span class="timing-state">${c.ended?'Reached Logs':c.seconds==null?'Unresolved':'In progress'}</span><h4>${esc(c.first_lane)}</h4><span class="timing-muted">First estimator lane</span></div><dl><div><dt>Started</dt><dd>${date(c.started)}</dd></div><div><dt>Entered Logs</dt><dd>${c.ended?date(c.ended):'Not recorded'}</dd></div></dl><strong class="timing-duration">${duration(c.seconds)}</strong></article>`).join('')||'<p class="timing-empty">No verified estimating cycle in the available history.</p>'}</div></section>
   <section class="timing-section"><h3>Movement timeline</h3><p class="timing-muted">Oldest to newest · elapsed time, not labor hours</p><ol class="timing-timeline">${result.periods.map(p=>`<li class="${p.current?'is-current':''}"><div class="timing-stop"><div><small>${esc(p.board)}</small><h4>${esc(p.lane)}</h4></div><strong>${duration(p.seconds)}</strong></div><div class="timing-dates"><span><b>Entered</b> ${date(p.entered)}</span><span><b>${p.current?'Status':'Left'}</b> ${p.current?'Current lane':p.exited?date(p.exited):'Not recorded'}</span></div><p class="timing-muted">Moved by ${esc(p.actor)}</p></li>`).join('')||'<li>No verifiable movement events available.</li>'}</ol></section>
   <details class="timing-totals"><summary>Total time by lane · includes returns</summary>${(result.totals||[]).map(t=>`<div><span><small>${esc(t.board)}</small>${esc(t.lane)}</span><span>${t.visits} ${t.visits===1?'visit':'visits'}</span><strong>${duration(t.seconds)}</strong></div>`).join('')||'<p>No verified durations available.</p>'}</details>
   ${window.LaneTimingSummary?.render(result) || ''}
   <aside class="timing-coverage"><strong>Coverage: available Trello events only</strong><p>${result.complete?'Available events retrieved; this does not prove the full job history is present.':'Retrieval limit reached; this history is partial.'} Missing moves remain unknown. Separate cards are not combined. Automatic shared tracking for every job is not connected yet.</p></aside>`;
  }catch(e){body.textContent=e.message||'Could not load movement history.';const retry=document.createElement('button');retry.textContent='Retry';retry.onclick=()=>{dialog.close();inspect(id);};body.append(retry);}
 }
 async function load(force=false){
  const token=++generation;const status=document.querySelector('#status');
  if(!data)paint();status.textContent=data?'Updating queues…':'Loading Jobs queues…';
  try{const result=await bounded(pywebview.api.load_flow(force));if(token!==generation)return;if(!result.ok)throw Error(result.error);data=result;paint(enterPending);enterPending=false;status.textContent=`${result.source}${result.saved_at?' · '+date(result.saved_at):''}`;
  }catch(e){if(token!==generation)return;status.textContent=(e.message||'Could not load queues.')+(data?' — Previous queues retained.':'');if(!data)document.querySelector('#flow').textContent='Queues unavailable. Use Refresh to retry.';}
 }
 return {load,cancel(){generation++;enterPending=true;}};
})();
