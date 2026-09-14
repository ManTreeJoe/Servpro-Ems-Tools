const {chromium}=require('playwright');
const path=require('path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage();
  await page.setContent(`<div id="root" class="modal-scrim audit-overlay"><div class="modal-box audit-card"><header class="modal-head">Test job</header><div class="modal-body"><div class="job-card-layout"><div class="job-card-main"><section>Job info</section><section class="job-log-section">Job log</section></div><aside class="job-card-activity"><input data-comment-search placeholder="Search comments"><div class="comment-stream">${'<p>Earlier comment</p>'.repeat(80)}</div><div class="comment-compose"><textarea data-comment-input aria-label="Job comment">draft</textarea><div><span data-comment-state></span><button data-post-comment>Add comment</button></div></div></aside></div></div></div></div>`);
  for(const file of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css']) await page.addStyleTag({path:path.resolve(file)});
  await page.addScriptTag({path:path.resolve('pipeline_web_assets/job_workspace_tabs.js')});
  await page.evaluate(()=>{
   window.originalInput=document.querySelector('[data-comment-input]');
   window.posts=[];document.querySelector('[data-post-comment]').onclick=()=>posts.push(originalInput.value);
   JobWorkspaceTabs.mount(document.querySelector('#root'),'comment-test');
  });
  for(const width of [1280,390]){
   await page.setViewportSize({width,height:800});
   for(const tab of ['overview','log','requirements','files','run']){
    await page.locator('#job-tab-'+tab).click();
    assert.equal(await page.locator('[data-comment-input]').isVisible(),true,`composer available on ${tab}`);
    await page.evaluate(()=>{document.querySelector('.job-card-layout').scrollTop=0;});
    const bounds=await page.locator('.comment-compose').boundingBox();
    assert.ok(bounds.y>=0&&bounds.y+bounds.height<=800,`composer stays in viewport on ${tab}`);
   }
  }
  assert.equal(await page.locator('[data-comment-input]').inputValue(),'draft');
  assert.equal(await page.evaluate(()=>originalInput===document.querySelector('[data-comment-input]')),true);
  await page.locator('[data-comment-input]').fill('New comment');
  await page.locator('[data-post-comment]').click();
  assert.deepEqual(await page.evaluate(()=>posts),['New comment']);
  await page.locator('#job-tab-log').click();
  assert.equal(await page.locator('[data-comment-search]').isVisible(),true);
  await page.screenshot({path:path.join(require('os').tmpdir(),'linguar-comment-dock.png')});
  console.log('PASS: comment composer visible on all tabs with long history, narrow layout, retained draft and post handler.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
