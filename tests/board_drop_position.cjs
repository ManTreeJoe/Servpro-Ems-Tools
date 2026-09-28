const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage();
 await page.route('http://localhost/**',r=>r.fulfill({contentType:'text/html',body:'<div id="status-msg"></div><div id="job-shelf" class="hidden"></div>'}));
 await page.goto('http://localhost/');await page.addScriptTag({path:path.resolve('pipeline_web_assets/app.js')});
 await page.addScriptTag({path:path.resolve('web_shared/card_drop_preview.js')});
 await page.evaluate(async()=>{
  renderBoard=()=>{};showMoveUndo=()=>{};
  window.moves=[];window.pywebview={api:{move_card:async(...args)=>{moves.push(args);return {ok:true};}}};
  state.board={boards:[{lanes:[{list_id:'a',cards:[{card_id:'x',pos:50}]},{list_id:'b',name:'Target',cards:[{card_id:'one',pos:100},{card_id:'two',pos:200}]}]}]};
  const lane=document.createElement('div');lane.dataset.listId='b';lane.dataset.laneName='Target';
  lane.innerHTML='<div class="kcard" data-card-id="one" style="height:80px"></div><div class="kcard" data-card-id="two" style="height:80px"></div>';document.body.append(lane);
  state.drag={cardId:'x',fromListId:'a',name:'X'};
  lane.classList.add('lane-cards');
  // The shared preview is also verified independently below; this fixture
  // leaves the real lane wrapper out to exercise the no-preview fallback.
  await onLaneDrop({preventDefault(){},currentTarget:lane,clientY:lane.children[1].getBoundingClientRect().top+1});
 });
 assert.deepEqual(await page.evaluate(()=>state.board.boards[0].lanes[1].cards.map(c=>c.card_id)),['one','x','two']);
 assert.equal(await page.evaluate(()=>moves[0][3]),150,'Saved position must lie between destination neighbours');
 await page.evaluate(async()=>{
  const lane=document.querySelector('[data-list-id="b"]');
  lane.innerHTML='<div class="kcard" data-card-id="one" style="height:80px"></div><div class="kcard" data-card-id="x" style="height:80px"></div><div class="kcard" data-card-id="two" style="height:80px"></div>';
  state.drag={cardId:'two',fromListId:'b',name:'Two'};
  await onLaneDrop({preventDefault(){},currentTarget:lane,clientY:lane.getBoundingClientRect().top});
 });
 assert.deepEqual(await page.evaluate(()=>state.board.boards[0].lanes[1].cards.map(c=>c.card_id)),['two','one','x']);
 assert.equal(await page.evaluate(()=>moves[1][3]),50);
 await page.evaluate(async()=>{
  const lane=document.querySelector('[data-list-id="b"]');
  state.drag={cardId:'two',fromListId:'b',name:'Two'};
  await onLaneDrop({preventDefault(){},currentTarget:lane,clientY:10000});
 });
 assert.deepEqual(await page.evaluate(()=>state.board.boards[0].lanes[1].cards.map(c=>c.card_id)),['one','x','two']);
 await page.evaluate(async()=>{
  const lane=document.querySelector('[data-list-id="b"]');
  delete state.board.boards[0].lanes[1].cards[0].pos;
  state.drag={cardId:'two',fromListId:'b',name:'Two'};
  await onLaneDrop({preventDefault(){},currentTarget:lane,clientY:lane.getBoundingClientRect().top});
 });
 assert.equal(await page.evaluate(()=>moves.length),3,'Missing cached order must not save a guessed position');
 await page.evaluate(()=>{
  const lane=document.querySelector('[data-list-id="b"]');
  const second=lane.children[1];
  CardDropPreview.show(lane,'.kcard',null,second.getBoundingClientRect().top+1);
  if(CardDropPreview.selection(lane).before!==second) throw new Error('Wrong preview slot');
  const gap=lane.querySelector('.card-drop-preview');
  CardDropPreview.show(lane,'.kcard',null,gap.getBoundingClientRect().top+5);
  if(CardDropPreview.selection(lane).before!==second) throw new Error('Preview jitters inside gap');
 });
 await page.screenshot({path:path.join(require('node:os').tmpdir(),'oneloss-drop-preview.png')});
 await page.emulateMedia({reducedMotion:'reduce'});
 await page.evaluate(()=>{CardDropPreview.clear();CardDropPreview.show(document.querySelector('.lane-cards'),'.kcard',null,10000);});
 assert.equal(await page.evaluate(()=>document.getAnimations().length),0,'Reduced motion respected');
 console.log('PASS: Jobs drop inserts and saves the chosen slot');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
