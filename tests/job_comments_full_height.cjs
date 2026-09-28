const {chromium}=require('playwright');
const path=require('node:path'), assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:940}});
  await page.setContent('<body class="responsive-ui"><div id="status-msg"></div></body>');
  await page.evaluate(()=>document.documentElement.setAttribute('data-theme','dark'));
  for(const file of ['web_shared/theme.css','web_shared/modal.css','pipeline_web_assets/app.css','web_shared/workspace_controls.css','web_shared/responsive.css','pipeline_web_assets/job_workspace_tabs.css']) await page.addStyleTag({path:path.resolve(file)});
  for(const file of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js']) await page.addScriptTag({path:path.resolve(file)});
  await page.evaluate(()=>{
   window.pywebview={api:{}};
   window.modal=openAuditModal({ok:true,client:'Sample Restoration Job',card_id:'card',selected_division:'EMS',audit:{ok:true,found:true},crm:{ok:true,job_log:[]},
    comments:Array.from({length:25},(_,i)=>({id:String(i),text:'Inspection complete. Equipment checked and readings recorded. Next visit scheduled.',member:'Test Coordinator',date:'2026-09-22T12:00:00Z'})),checklists:[],documents:{files:[]}});
  });
  await page.locator('[data-comment-input]').fill('Keep this draft');
  for(const tab of ['log','requirements','overview']) await page.locator('#job-tab-'+tab).click();
  assert.equal(await page.locator('[data-comment-input]').inputValue(),'Keep this draft');
  const card=await page.locator('.audit-card').boundingBox();
  const activity=await page.locator('.job-card-activity').boundingBox();
  await page.screenshot({path:path.join(process.env.TEMP,'oneloss-full-height-comments.png')});
  assert.ok(Math.abs(activity.y-card.y)<=3,'Comments must begin at the top of the card');
  assert.ok(Math.abs(activity.height-card.height)<5,'Comments must span the card height');
  const composer=await page.locator('.comment-compose').boundingBox();
  assert.ok(composer.y+composer.height<=card.y+card.height+1,'Composer stays visible');
  await page.screenshot({path:path.join(process.env.TEMP,'oneloss-full-height-comments.png')});
  await page.setViewportSize({width:800,height:800});
  assert.equal(await page.locator('.audit-card').evaluate(el=>getComputedStyle(el).display),'flex','Narrow view retains stacked layout');
  console.log('PASS full-height comments, visible composer, draft retained across tabs, narrow fallback.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
