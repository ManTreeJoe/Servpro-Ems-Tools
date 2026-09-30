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
 await page.evaluate(()=>{window.pywebview={api:{}};openAuditModal({ok:true,client:'Popup height test',card_id:'ems-card',selected_division:'EMS',audit:{found:true},crm:{},comments:[]});});
 for(const height of [960,720,600]){
  await page.setViewportSize({width:1426,height});
  const bounds=await page.locator('.audit-card').boundingBox();
  const post=await page.locator('[data-post-comment]').boundingBox();
  assert(bounds.y>=8 && bounds.y+bounds.height<=height-8,`Job popup must fit with breathing room at ${height}px: ${JSON.stringify(bounds)}`);
  assert(post.y>=0&&post.y+post.height<=height-8,`Post button must be fully visible: ${JSON.stringify(post)}`);
 }
 console.log('PASS: notification job popup and post button fit at 960, 720 and 600px heights');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
