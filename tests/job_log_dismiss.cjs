const {chromium}=require('playwright');
const path=require('node:path'), assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage();
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  page.on('dialog',d=>d.accept());
  await page.setContent('<div id="status-msg"></div>');
  for(const file of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js']) await page.addScriptTag({path:path.resolve(file)});
  await page.evaluate(()=>{
   window.calls=[];
   window.pywebview={api:{
    delete_job_log_update: async (...args)=>{calls.push(args); return {ok:true,pending_sync:true,deleted_ids:['bad'],deleted_sources:['["card", "comment:Pack Out"]'],deleted_comment_id:''};}
   }};
   window.fixture={ok:true,client:'Fixture',card_id:'card',selected_division:'EMS',audit:{ok:true,found:true},
    crm:{job_log:['bad','good'].map(entry_id=>({entry_id,source:'trello',source_id:entry_id==='bad'?'comment:Pack Out':'other:Demo',placement_card_id:'card',work_type:'EQ placed',note:'Original evidence'}))},
    comments:[{id:'comment',text:'Original evidence'}],checklists:[],documents:{files:[]}};
   window.staleFixture=structuredClone(fixture);
   window.controller=openAuditModal(fixture);
   controller.applyRefresh(structuredClone(fixture));
  });
  await page.locator('#job-tab-log').click();
  assert.equal(await page.locator('[data-delete-job-log="bad"]').textContent(),'Delete log entry');
  await page.locator('[data-delete-job-log="bad"]').click();
  await page.waitForFunction(()=>!document.querySelector('[data-job-log-id="bad"]'));
  assert.equal(await page.locator('[data-job-log-id="good"]').count(),1);
  assert.equal(await page.locator('[data-comment-id="comment"]').count(),1);
  assert.match(await page.locator('#status-msg').textContent(),/sync pending/);
  await page.evaluate(()=>controller.applyRefresh(structuredClone(staleFixture)));
  assert.equal(await page.locator('[data-job-log-id="bad"]').count(),0,'Late refresh must not restore a dismissed interpretation');
  await page.evaluate(()=>{const late=structuredClone(staleFixture);late.crm.job_log[0].entry_id='shared-alias';controller.applyRefresh(late);});
  assert.equal(await page.locator('[data-job-log-id="shared-alias"]').count(),0,'A second ID for the same source must stay deleted');
  await page.evaluate(()=>{const next=structuredClone(staleFixture);next.crm.job_log.push({entry_id:'background-new',work_type:'Unrequested refresh'});controller.applyRefresh(next);});
  assert.equal(await page.locator('[data-job-log-id="background-new"]').count(),0,'Background refresh must not change a loaded log');
  await page.evaluate(()=>{pywebview.api.refresh_saved_job_log=async()=>({ok:true,crm:{job_log:[{entry_id:'manual-refresh-new',work_type:'Explicit refresh'}]}});});
  await page.locator('[data-refresh-job-log]').click();
  await page.waitForFunction(()=>document.querySelector('[data-job-log-id="manual-refresh-new"]'));
  await page.evaluate(()=>{pywebview.api.delete_job_log_update=async()=>({ok:false,error:'Disk unavailable; entry kept'});});
  await page.locator('[data-delete-job-log="good"]').click();
  await page.waitForFunction(()=>document.querySelector('[data-log-action-error]'));
  assert.equal(await page.locator('[data-job-log-id="good"] [role="alert"]').textContent(),'Disk unavailable; entry kept');
  assert.deepEqual(await page.evaluate(()=>calls),[['Fixture','bad','card','EMS']]);
  await page.evaluate(()=>{
    controller.close();
    const stale=structuredClone(fixture);
    controller=openAuditModal(stale);
    controller.applyRefresh({ok:true,card_id:'card',crm:{ok:true,
      job_log:fixture.crm.job_log.filter(row=>row.entry_id!=='bad'),job_log_deleted_ids:['bad']}});
  });
  assert.equal(await page.locator('[data-job-log-id="bad"]').count(),0,'Saved dismissal must remove stale rows after reopening');
  assert.deepEqual(errors,[]);
  console.log('PASS: log-only deletion survives stale rows and source aliases; sibling and comment remain.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
