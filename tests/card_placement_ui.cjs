const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1150,height:850}});
  await page.setContent('<div id="status-msg"></div>');
  for(const f of ['web_shared/theme.css','web_shared/modal.css','pipeline_web_assets/app.css']) await page.addStyleTag({path:path.resolve(f)});
  for(const f of ['web_shared/modal.js','pipeline_web_assets/app.js']) await page.addScriptTag({path:path.resolve(f)});
  await page.evaluate(()=>{
   window.calls=[]; window.testRow={card_id:'a',title:'Example, Customer - AAA',board_id:'wip',list_id:'active',state:'active',version:0};
   window.pywebview={api:{
    card_placement_context:async()=>({ok:true,placement:window.testRow,placements:[window.testRow],can_delete:true,
     boards:[{board_id:'wip',name:'Work in Progress',lists:[{id:'active',name:'Active'}]},
       {board_id:'est',name:'Estimating',lists:[{id:'review',name:'Pending Review'}]}]}),
    card_placement_change:async(...args)=>{window.calls.push(args); return {ok:false,error:'Card changed. Refresh and try again.'};},
    retry_card_placement_sync:async()=>({ok:true})}};
   openPlacementAction('a','move');
  });
  await page.locator('[data-board]').selectOption('est');
  assert.equal(await page.locator('[data-section]').inputValue(),'review');
  await page.locator('[data-save]').click();
  await page.locator('[data-error]').filter({hasText:'Card changed'}).waitFor();
  assert.deepEqual(await page.evaluate(()=>calls[0]),['a','move',0,'est','review']);
  assert.equal(await page.locator('[data-save]').isEnabled(),true);
  await page.screenshot({path:path.join(process.env.TEMP,'oneloss-placement-move.png')});
  await page.evaluate(()=>{closeModal('placement-action'); testRow.state='archived';testRow.version=1;openArchivedCards();});
  await page.locator('[data-restore]').waitFor();
  assert.equal(await page.locator('[data-delete]').count(),1);
  await page.locator('[data-delete]').click();
  await page.locator('#placement-action [data-save]').waitFor();
  assert.equal(await page.evaluate(()=>calls.length),1,'Delete must wait for explicit confirmation');
  assert.match(await page.locator('#placement-action').innerText(),/Trello card stays archived/);
  await page.screenshot({path:path.join(process.env.TEMP,'oneloss-placement-delete.png')});
  await page.setViewportSize({width:480,height:750});
  const bounds=await page.locator('#placement-action .overlay-panel').boundingBox();
  assert.ok(bounds.width<=480 && bounds.x>=0,'Narrow dialog must fit');
  console.log('PASS move destination, conflict retention, archived-only delete confirmation, narrow layout');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
