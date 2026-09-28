const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:950}});
  await page.setContent('<div id="status-msg"></div>');
  for(const file of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css'])await page.addStyleTag({path:path.resolve(file)});
  for(const file of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(file)});
  await page.evaluate(()=>{
   document.documentElement.dataset.theme='dark';
   window.pywebview={api:{}};
   window.snapshotRequest=null;window.addEventListener('message',e=>{if(e.data?.type==='ems-open-tool-modal')snapshotRequest=e.data;});
   openAuditModal({ok:true,client:'Toolbar preview',card_id:'card',selected_division:'EMS',audit:{found:true},crm:{job_log:[],job_log_saved_at:'2026-09-28'},comments:[]});
  });
  await page.locator('#job-tab-log').click();
  assert.equal(await page.locator('[data-print-job-log]').isDisabled(),true);
  await page.locator('[data-create-snapshot]').click();
  await page.waitForFunction(()=>window.snapshotRequest);
  assert.deepEqual(await page.evaluate(()=>({cardId:snapshotRequest.cardId,division:snapshotRequest.division,create:snapshotRequest.create})),{cardId:'card',division:'EMS',create:true});
  const positions=await page.locator('.job-log-toolbar .btn').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().top));
  assert.equal(new Set(positions).size,1,'All secondary controls share one row');
  const header=await page.locator('.job-log-section .section-title-row').boundingBox();
  assert.ok(header.height<70,'No stacked header buttons');
  await page.locator('.job-log-section').screenshot({path:path.join(require('os').tmpdir(),'oneloss-job-log-toolbar.png')});
  await page.setViewportSize({width:960,height:800});
  const contained=await page.locator('.job-log-toolbar').evaluate(n=>[...n.querySelectorAll('button')].every(b=>b.getBoundingClientRect().right<=n.getBoundingClientRect().right+1));
  assert.ok(contained,'Controls wrap without overflow');
  await page.locator('.job-log-section [data-add-job-log]').click();
  assert.equal(await page.locator('[data-job-log-editor]').isVisible(),true);
  console.log('Job Log toolbar: PASS');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
