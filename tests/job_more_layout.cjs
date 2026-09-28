const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  await page.setContent('<div id="status-msg"></div>');
  for(const file of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css'])await page.addStyleTag({path:path.resolve(file)});
  for(const file of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(file)});
  await page.evaluate(()=>{document.documentElement.dataset.theme='dark';window.pywebview={api:{}};openAuditModal({ok:true,client:'Header layout test',card_id:'ems-card',selected_division:'EMS',audit:{found:true},crm:{},comments:[]});});
  for(const width of [1440,1280,900,600]){
   await page.setViewportSize({width,height:1000});
   const more=await page.locator('.more-quick-menu .tool-menu-trigger').boundingBox();
   const first=await page.locator('[data-initial-notes]').boundingBox();
   assert.ok(Math.abs(more.y-first.y)<3,`More should remain on first action row at ${width}px; got ${more.y} vs ${first.y}`);
   await page.locator('.more-quick-menu .tool-menu-trigger').click();
   const menu=await page.locator('.more-quick-menu .tool-menu-panel').boundingBox();
   assert.ok(menu.x>=0 && menu.x+menu.width<=width,'More menu must remain onscreen');
   await page.keyboard.press('Escape');
   assert.equal(await page.locator('.audit-card').isVisible(),true);
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-more-layout.png')});
  console.log('PASS: More stays on first action row and its menu stays onscreen at four widths.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
