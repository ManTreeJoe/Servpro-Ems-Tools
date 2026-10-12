const {chromium}=require('playwright');
const assert=require('node:assert/strict'),path=require('node:path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1500,height:950}});
  await page.setContent('<html data-theme="dark"><body><dialog id="logs-audit"><div class="section-head"><h2>Logs audit</h2></div><p data-status>Review evidence before confirming.</p><div data-body></div></dialog></body></html>');
  for(const f of ['web_shared/theme.css','analytics_web_assets/app.css','analytics_web_assets/logs_review_workspace.css'])await page.addStyleTag({path:path.resolve(f)});
  await page.addScriptTag({path:path.resolve('analytics_web_assets/logs_review_workspace.js')});
  await page.evaluate(()=>{
   const form=document.createElement('form');form.innerHTML='<label>Job Date (received)<input name="job_date" value="2026-09-16"></label><input name="period_start" value="2026-10-05"><input name="period_end" value="2026-10-11"><label>Notes<textarea name="note"></textarea></label><div style="height:650px">Existing audit fields</div><div class="audit-footer"></div>';
   const library=document.createElement('details'),openButton=document.createElement('button'),backButton=document.createElement('button');
   openButton.dataset.open='';openButton.onclick=()=>window.opens++;
   window.opens=0;window.picks=[];window.comments=[];
   window.queue={cards:[{id:'a',name:'Morgan residence'},{id:'b',name:'Cedar Grove'}],drafts:{}};
   window.workspace=LogsReviewWorkspace.mount({host:document.querySelector('[data-body]'),queue,current:'a',form,library,openButton,backButton,evidence:{card:{name:'Morgan residence'}},comments:[{id:'old',author:'Earlier',date:'2026-10-01',text:'Earlier note'},{id:'new',author:'Latest',date:'2026-10-08',text:'<img src=x onerror=alert(1)>'}],onSelect:id=>picks.push(id),onOpenComment:id=>comments.push(id),onQuery:q=>window.query=q});
   document.querySelector('dialog').showModal();
  });
  assert.equal(await page.locator('.logs-review-comment').first().locator('strong').textContent(),'Latest');
  assert.equal(await page.locator('.logs-review-comment img').count(),0);
  await page.locator('[name=note]').fill('Keep this draft');
  await page.locator('.logs-review-detail').evaluate(e=>e.scrollTop=80);
  const scroll=await page.locator('.logs-review-detail').evaluate(e=>e.scrollTop);
  await page.locator('[data-open]').evaluate(e=>e.click());
  assert.equal(await page.locator('.logs-review-detail').evaluate(e=>e.scrollTop),scroll);
  assert.equal(await page.locator('[name=note]').inputValue(),'Keep this draft');
  await page.locator('[data-review-comment="new"]').click();
  assert.deepEqual(await page.evaluate(()=>comments),['new']);
  await page.locator('[data-review-search]').fill('Cedar');
  assert.equal(await page.locator('[data-review-card]').count(),1);
  await page.locator('[data-review-card]').click();
  assert.deepEqual(await page.evaluate(()=>picks),['b']);
  await page.locator('[data-review-search]').fill('');
  await page.locator('[data-review-next]').click();
  assert.deepEqual(await page.evaluate(()=>picks),['b','b']);
  await page.evaluate(()=>{queue.drafts.a={fields:{}};workspace.refreshQueue();});
  assert.match(await page.locator('[data-review-card="a"]').innerText(),/Draft saved/);
  await page.locator('.logs-review-detail').evaluate(e=>e.scrollTop=0);
  await page.screenshot({path:path.join(require('node:os').tmpdir(),'logs-review-workspace-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.locator('dialog').evaluate(e=>e.scrollWidth<=e.clientWidth),true);
  for(const width of [1500,390]){
   await page.setViewportSize({width,height:950});
   for(const [pane,input,list] of [['.logs-review-queue','[data-review-search]','[data-review-jobs]'],['.logs-review-comments','[data-comment-search]','[data-review-comments]']]){
    await page.locator(list).evaluate(e=>{e.style.minHeight='2500px';});
    await page.locator(pane).evaluate(e=>e.scrollTop=0);
    const before=await page.locator(input).evaluate(e=>e.getBoundingClientRect().top);
    await page.locator(pane).evaluate(e=>e.scrollTop=600);
    const after=await page.locator(input).evaluate(e=>e.getBoundingClientRect().top);
    assert.ok(Math.abs(after-before)<2,`${input} pinned at ${width}px`);
   }
  }
  await page.setViewportSize({width:1500,height:950});
  await page.screenshot({path:path.join(require('node:os').tmpdir(),'logs-review-sticky-search.png')});
  console.log('PASS: exact job/comment callbacks, draft and scroll retained, search, next, saved status, escaping, responsive layout');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
