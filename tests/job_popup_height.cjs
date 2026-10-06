const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage();
 await page.setContent('<body class="responsive-ui job-workspace-mode"><div id="status-msg"></div></body>');
 const html=fs.readFileSync('pipeline_web_assets/index.html','utf8');
 for(const match of html.matchAll(/<link[^>]+href="([^"]+\.css(?:\?[^"]*)?)"/g)){
  await page.addStyleTag({path:path.resolve('pipeline_web_assets',match[1].split('?')[0])});
 }
 for(const file of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(file)});
 await page.evaluate(()=>{window.pywebview={api:{}};openAuditModal({ok:true,client:'Popup height test',card_id:'ems-card',selected_division:'EMS',audit:{found:true},crm:{},info_sections:[{name:'Customer',fields:[{id:'customer_name',label:'Name',value:'Example customer'}]},{name:'Scope of work',fields:[{id:'scope_initial',label:'Initial scope',value:'Inspect kitchen\nDry affected walls'}]}],comments:[]});});
 assert.deepEqual(await page.locator('.job-info-group h4').allTextContents(),['App location','Scope of work','Customer']);
 assert.equal(await page.locator('.job-scope-field strong').evaluate(el=>getComputedStyle(el).whiteSpace),'pre-wrap');
 const inactive=page.locator('.inactive-division-tools').first();
 assert.equal(await inactive.locator('input').isVisible(),false);
 await inactive.locator('summary').click();
 assert.equal(await inactive.locator('input').isVisible(),true);
 await inactive.locator('summary').click();
 const composer=page.locator('[data-comment-input]');
 const compactHeight=(await composer.boundingBox()).height;
 await composer.focus();
 assert((await composer.boundingBox()).height>compactHeight,'Empty composer expands on focus');
 await composer.fill('Draft stays expanded');
 await page.locator('.modal-title').click();
 assert((await composer.boundingBox()).height>compactHeight,'Draft stays expanded after blur');
 await composer.fill('');
 await page.locator('.modal-title').click();
 assert.equal(await page.locator('.quick-primary-actions [data-initial-notes]').count(),0);
 assert.equal(await page.locator('.more-quick-menu [data-initial-notes]').count(),1);
 await page.locator('.more-quick-menu > .tool-menu-trigger').click();
 assert(await page.locator('.more-quick-menu [data-initial-notes]').isVisible(),'Initial notes is accessible from More');
 await page.locator('.more-quick-menu > .tool-menu-trigger').click();
 assert.equal(await page.locator('.activity-head h3 [data-comment-count]').count(),1);
 for(const height of [960,720,600]){
  await page.setViewportSize({width:1426,height});
  const bounds=await page.locator('.audit-card').boundingBox();
  const post=await page.locator('[data-post-comment]').boundingBox();
  const close=await page.locator('.workspace-corner-close').boundingBox();
  const count=await page.locator('[data-comment-count]').boundingBox();
  assert(Math.abs(bounds.x+bounds.width-close.x-close.width-13)<3,'Close belongs at the overall top-right corner');
  assert(close.y-bounds.y<16,'Close stays at top of workspace');
  assert(count.x+count.width<=close.x,'Comment count must not overlap close');
  assert(bounds.y>=8 && bounds.y+bounds.height<=height-8,`Job popup must fit with breathing room at ${height}px: ${JSON.stringify(bounds)}`);
  assert(post.y>=0&&post.y+post.height<=height-8,`Post button must be fully visible: ${JSON.stringify(post)}`);
 }
 await page.setViewportSize({width:1426,height:960});
 await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-clean-job-window.png')});
 await page.locator('.workspace-corner-close').click();
 assert.equal(await page.locator('.audit-overlay').count(),0,'Corner close dismisses the whole workspace');
 console.log('PASS: notification job popup and post button fit at 960, 720 and 600px heights');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
