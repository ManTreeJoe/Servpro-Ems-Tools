const {chromium}=require('playwright'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage();await page.setContent('<div id="status-msg"></div>');
 for(const f of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(f)});
 await page.evaluate(async()=>{
  window.liveCalls=0;window.pywebview={api:{job_card_workspace_fast:async()=>{throw Error('Saved data failed');},job_card_workspace:async()=>{liveCalls++;return {ok:false,error:'Live data failed'};}}};
  await onAuditCard('Maria test','card','','EMS');
 });
 assert.equal(await page.evaluate(()=>liveCalls),1);
 assert.doesNotMatch(await page.locator('#job-panel-requirements').innerText(),/Loading checklists/);
 assert.match(await page.locator('#job-panel-requirements').innerText(),/Details could not be loaded/);
 await page.getByRole('button',{name:'Retry details',exact:true}).click();
 await page.waitForFunction(()=>liveCalls===2);
 const timeout=await page.evaluate(async()=>{try{await boundedWorkspaceRead(new Promise(()=>{}),'Test',5);}catch(e){return e.message;}});
 assert.match(timeout,/timed out/);
 console.log('PASS fast failure still attempts live read, failed placeholders stop loading, retry and bounded wait');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
