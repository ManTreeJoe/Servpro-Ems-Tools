const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:430,height:300}});
  await page.setContent('<div id="root"><header class="activity-head"><div><h3>Comments and activity</h3></div><span data-comment-count>12</span></header><div class="comment-search">Search comments</div><div data-comment-stream></div><div class="comment-compose"></div></div>');
  for(const file of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css'])await page.addStyleTag({path:path.resolve(file)});
  await page.addScriptTag({path:path.resolve('pipeline_web_assets/job_conversation.js')});
  await page.evaluate(()=>{document.documentElement.dataset.theme='dark';window.c=JobConversation.mount(document.querySelector('#root'),{followWorkspace:true,cardId:'ems',division:'EMS',comments:[],initialComplete:false,render:()=>'',fetch:async()=>({ok:true,comments:[]})});});
  await page.emulateMedia({reducedMotion:'reduce'});
  const shape=await page.locator('.ui-spinner').evaluate(el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return {width:r.width,height:r.height,padding:s.padding,bg:s.backgroundColor};});
  console.log(shape);
  assert.equal(shape.width,shape.height,'Spinner must be circular, not a badge-shaped oval');
  assert.equal(shape.width,16);
  assert.equal(shape.padding,'0px');
  assert.equal(shape.bg,'rgba(0, 0, 0, 0)');
  const before=await page.locator('.comment-search').boundingBox();
  await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-spinner-fixed.png')});
  await page.evaluate(()=>c.applyInitialRefresh('ems',[],true));
  assert.equal((await page.locator('.comment-search').boundingBox()).y,before.y);
  console.log('PASS: circular comment spinner; no completion layout shift');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
