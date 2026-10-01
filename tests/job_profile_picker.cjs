const {chromium}=require('playwright');
const path=require('node:path'), assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:950}});
  await page.setContent('<div id="status-msg"></div>');
  for(const f of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css']) await page.addStyleTag({path:path.resolve(f)});
  for(const f of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js']) await page.addScriptTag({path:path.resolve(f)});
  await page.evaluate(()=>{
   document.documentElement.dataset.theme='dark';
   window.applied=[];
   window.pywebview={api:{apply_job_profile:async(c,id)=>{applied.push([c,id]);return {ok:false,error:'Test failure'};}}};
   openAuditModal({ok:true,client:'Profile test',card_id:'card',selected_division:'EMS',audit:{found:true},comments:[],crm:{job_profile_suggestions:[{profile_id:'pm',name:'Property manager template',recommended:false},{profile_id:'base',name:'Regular',recommended:true}]}});
  });
  await page.locator('#job-tab-requirements').click();
  await page.getByText('Apply a requirements profile',{exact:true}).click();
  assert.equal(await page.locator('[data-job-profile] option').count(),2);
  await page.locator('[data-job-profile]').selectOption('pm');
  page.once('dialog',d=>d.accept());
  await page.locator('[data-job-profile-apply]').click();
  assert.deepEqual(await page.evaluate(()=>applied),[['Profile test','pm']]);
  assert.equal(await page.locator('[data-job-profile-apply]').isEnabled(),true);
  await page.locator('.progress-section').screenshot({path:path.join(require('os').tmpdir(),'oneloss-profile-picker.png')});
  console.log('PASS: arbitrary profile selection and failed apply recovery');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
