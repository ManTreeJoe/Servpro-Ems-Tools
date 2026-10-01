const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{const b=await chromium.launch({channel:'msedge',headless:true});try{
 const p=await b.newPage();await p.setContent('<div id="status-msg"></div><div id="job-shelf" class="hidden"></div>');
 await p.addScriptTag({path:path.resolve('pipeline_web_assets/app.js')});
 await p.evaluate(async()=>{
  renderBoard=()=>{};showMoveUndo=()=>{};window.calls=[];
  const payload=pos=>({ok:true,boards:[{lanes:[{list_id:'a',cards:[{card_id:'x',pos:50}]},{list_id:'b',name:'Target',cards:[{card_id:'one',pos:100},{card_id:'two',pos}]}]}]});
  state.board=payload(100);
  window.pywebview={api:{board_view_shared_refresh:async()=>{calls.push('refresh');return payload(200);},move_card:async(...args)=>{calls.push(args);return {ok:true};}}};
  const lane=document.createElement('div');lane.dataset.listId='b';lane.dataset.laneName='Target';lane.innerHTML='<div class="kcard" data-card-id="one" style="height:80px"></div><div class="kcard" data-card-id="two" style="height:80px"></div>';document.body.append(lane);
  state.drag={cardId:'x',fromListId:'a',name:'X'};
  await onLaneDrop({preventDefault(){},currentTarget:lane,clientY:lane.children[1].getBoundingClientRect().top+1});
 });
 assert.deepEqual(await p.evaluate(()=>calls),['refresh',['x','b',0,150]]);
 assert.doesNotMatch(await p.locator('#status-msg').textContent(),/Refresh Jobs/);
 await p.evaluate(async()=>{window.calls=[];state.drag={cardId:'x'};await refreshSavedBoardInBackground(true);});
 assert.equal(await p.evaluate(()=>calls.length),0,'No background refresh during drag');
 console.log('PASS: stale ordering automatically refreshes and retries exact slot; active drag is protected');
}finally{await b.close();}})().catch(e=>{console.error(e);process.exit(1)});
