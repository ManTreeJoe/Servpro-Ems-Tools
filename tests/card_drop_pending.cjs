const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const {pathToFileURL}=require('node:url');
(async()=>{const b=await chromium.launch({channel:'msedge',headless:true});try{
 const p=await b.newPage();await p.route(/^https?:/,r=>r.abort());
 await p.goto(pathToFileURL(path.resolve('pipeline_web_assets/index.html')).href);
 await p.evaluate(()=>{
  window.pywebview={api:{move_card:()=>new Promise(resolve=>window.finishMove=resolve)}};
  state.board={boards:[{key:'wip',name:'Work',lanes:[{list_id:'a',name:'A',cards:[{card_id:'x',client:'Test',pos:50,labels:[]}]},{list_id:'b',name:'B',cards:[]}]}]};state.activeBoardKey='wip';renderBoard();
  state.drag={cardId:'x',fromListId:'a',name:'Test'};
  window.drop=onLaneDrop({preventDefault(){},currentTarget:document.querySelector('.lane[data-list-id="b"]'),clientY:500});
 });
 assert.equal(await p.locator('.lane[data-list-id="b"] .kcard').count(),1,'Card must appear at destination before save responds');
 assert.equal(await p.locator('[data-drop-saving]').count(),1,'Pending move must not look confirmed');
 await p.evaluate(()=>renderBoard());
 assert.equal(await p.locator('.lane[data-list-id="b"] .kcard').count(),1,'Redraw must retain pending preview');
 await p.evaluate(()=>finishMove({ok:true}));await p.evaluate(()=>drop);
 assert.equal(await p.locator('[data-drop-saving]').count(),0);
 assert.equal(await p.locator('.lane[data-list-id="b"] .kcard').count(),1);
 await p.evaluate(()=>{
  loadBoard=async()=>{};
  state.drag={cardId:'x',fromListId:'b',name:'Test'};
  window.drop=onLaneDrop({preventDefault(){},currentTarget:document.querySelector('.lane[data-list-id="a"]'),clientY:500});
 });
 await p.evaluate(()=>finishMove({ok:false,error:'Not permitted'}));await p.evaluate(()=>drop);
  assert.equal(await p.locator('.lane[data-list-id="b"] .kcard').count(),1,'Failed move must restore last confirmed position');
 await p.evaluate(()=>{
  pywebview.api.move_card=async()=>{throw new Error('Disconnected')};
  state.drag={cardId:'x',fromListId:'b',name:'Test'};
  window.drop=onLaneDrop({preventDefault(){},currentTarget:document.querySelector('.lane[data-list-id="a"]'),clientY:500});
 });
 await p.evaluate(()=>drop);
 assert.equal(await p.locator('[data-drop-saving]').count(),0,'Thrown bridge failure must clear pending state');
 assert.equal(await p.locator('.lane[data-list-id="b"] .kcard').count(),1);
 console.log('PASS: immediate pending drop, redraw safety, confirmation and failure rollback');
}finally{await b.close();}})().catch(e=>{console.error(e);process.exitCode=1});
