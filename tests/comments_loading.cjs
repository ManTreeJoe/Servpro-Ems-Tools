const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage();
  await page.setContent('<div id="root"><div class="comment-search"></div><div data-comment-stream></div><div data-comment-count></div><div class="comment-compose"></div></div>');
  for(const file of ['web_shared/theme.css','pipeline_web_assets/job_workspace_tabs.css']) await page.addStyleTag({path:path.resolve(file)});
  await page.addScriptTag({path:path.resolve('pipeline_web_assets/job_conversation.js')});
  await page.evaluate(()=>{window.c=JobConversation.mount(document.querySelector('#root'),{
   cardId:'ems',division:'EMS',comments:[],initialComplete:false,
   cards:[{division:'CONTENTS',card_id:'contents'}],render:r=>`<p>${r.text}</p>`,
   fetch:()=>new Promise(resolve=>window.resolveComments=resolve)
  });});
  assert.equal(await page.locator('.comment-division-status .ui-spinner').count(),1);
  const top=await page.locator('.comment-search').evaluate(el=>el.getBoundingClientRect().top);
  assert.doesNotMatch(await page.locator('[data-comment-stream]').textContent(),/Loading comments/);
  await page.evaluate(()=>c.applyInitialRefresh('ems',[],false));
  assert.doesNotMatch(await page.locator('[data-comment-stream]').textContent(),/No comments/);
  await page.evaluate(()=>c.applyInitialRefresh('ems',[],true));
  assert.match(await page.locator('[data-comment-stream]').textContent(),/No comments/);
  assert.equal(await page.locator('.comment-search').evaluate(el=>el.getBoundingClientRect().top),top,'Spinner completion must not shift comments');
  await page.locator('[data-comment-division="CONTENTS"]').click();
  assert.equal(await page.locator('.comment-division-status .ui-spinner').count(),1);
  await page.evaluate(()=>resolveComments({ok:false,error:'Offline'}));
  await page.waitForFunction(()=>document.querySelector('.comment-division-error').textContent.includes('Offline'));
  assert.doesNotMatch(await page.locator('[data-comment-stream]').textContent(),/No comments/);
  await page.evaluate(()=>{window.pending=c.refresh();});
  await page.evaluate(()=>resolveComments({ok:true,comments:[]}));
  await page.evaluate(()=>pending);
  assert.match(await page.locator('[data-comment-stream]').textContent(),/No comments/);
  await page.evaluate(()=>c.add('contents',{id:'saved',text:'Saved comment'}));
  await page.evaluate(()=>{window.pending=c.refresh();});
  assert.match(await page.locator('[data-comment-stream]').textContent(),/Saved comment/);
  assert.equal(await page.locator('.comment-search').evaluate(el=>el.getBoundingClientRect().top),top,'Refresh must not insert a status row');
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await page.locator('.ui-spinner').evaluate(el=>getComputedStyle(el).animationName),'none');
  await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-comments-spinner.png')});
  await page.evaluate(()=>resolveComments({ok:true,comments:[{id:'saved',text:'Saved comment'}]}));await page.evaluate(()=>pending);
  console.log('PASS: loading, checked empty, failed load, retry and division switching.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
