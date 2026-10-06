const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage();
  await page.setContent('<div id="status-msg"></div>');
  for(const file of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js']) await page.addScriptTag({path:path.resolve(file)});
  await page.evaluate(()=>{
   window.fullCalls=0;
   window.pywebview={api:{
    job_card_placement:()=>new Promise(resolve=>window.finishPlacement=resolve),
    job_card_workspace_fast:async()=>({ok:true,card_id:'one',client:'Fixture',selected_division:'EMS',deferred_loading:true,audit:{found:true},crm:{},info_sections:[{name:'Customer',fields:[{id:'phone',label:'Phone',value:'555-0101'}]}]}),
    job_card_workspace:async()=>{fullCalls++;return {ok:true,card_id:'one',audit:{found:true},crm:{},comments:[]};}
   }};
   window.opening=onAuditCard('Fixture','one','','EMS');
  });
  await page.waitForFunction(()=>document.querySelector('.job-info-section')?.textContent.includes('555-0101'),{},{timeout:2000});
  assert.equal(await page.evaluate(()=>fullCalls),1,'Location lookup must not block full refresh');
  await page.locator('[data-comment-input]').fill('Unsaved draft');
  await page.evaluate(()=>finishPlacement({lane:'Ready lane',board:'Work board'}));
  await page.waitForFunction(()=>document.querySelector('.job-info-section')?.textContent.includes('Ready lane'));
  assert.equal(await page.locator('[data-comment-input]').inputValue(),'Unsaved draft');
  assert.equal(await page.locator('[data-workspace-load-state]').textContent(),'Up to date');
  await page.locator('[data-comment-input]').fill('');
  await page.locator('[data-close]').click();
  await page.evaluate(()=>{window.opening=onAuditCard('Fixture','one','','EMS');});
  await page.waitForFunction(()=>fullCalls===2);
  await page.evaluate(()=>{document.querySelector('[data-close]').click();finishPlacement({lane:'Stale lane',board:'Old board'});});
  await page.evaluate(()=>opening);
  assert.equal(await page.locator('.audit-overlay').count(),0,'Late location result must not reopen a closed job');
  console.log('PASS: delayed location lookup does not block saved facts or full refresh; closed job stays closed.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
