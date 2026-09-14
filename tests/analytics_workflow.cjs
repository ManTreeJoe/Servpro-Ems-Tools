const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  page.setDefaultTimeout(8000);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const html=fs.readFileSync('analytics_web_assets/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace(/<link\b[^>]*>/g,'');
  await page.route('http://review.test/**',route=>route.fulfill({contentType:'text/html',body:html}));
  await page.goto('http://review.test/');
  await page.addStyleTag({path:path.resolve('analytics_web_assets/app.css')});
  await page.addStyleTag({path:path.resolve('analytics_web_assets/workspace_layout.css')});
  await page.evaluate(()=>{
   window.savedReviews={};window.messages=[];
   window.addEventListener('message',e=>messages.push(e.data));
   window.pywebview={api:{
    async load(f){
     if(window.failLoad)return {ok:false,error:'Test connection unavailable'};
     const key='v2:'+JSON.stringify([f.start,f.end,f.review_role]);
     const row={id:'trello:exact-card',name:'Test review card',canon:'test',identity:'Trello review card',stage:'unknown',carrier:'',received:'',divisions:[{division:'EMS'}],review_key:key,review_source:{card_id:'exact-card',list_name:'TO BE PRESERVED'}};
     return {ok:true,location:'IE',rows:[row],filters:f,options:{},warnings:['Current column membership — test data'],legacy_count:1,source:'Fixture',generated_at:new Date().toISOString(),review_store:{reviews:savedReviews,snapshots:[]}};
    },
    async export_csv(csv){window.exportedCSV=csv;return {ok:true};},
    async save_review(id,f,note,owner,due,outcome){savedReviews['v2:'+JSON.stringify([f.start,f.end,f.review_role])]={note,owner,due,outcome,reviewer_name:'Test Reviewer',updated_at:'2026-09-11T10:30:00',filters:f,role:f.review_role,evidence:{review_source:{list_name:'TO BE PRESERVED'}}};return {ok:true};}
   }};
  });
  await page.addScriptTag({path:path.resolve('analytics_web_assets/app.js')});
  await page.evaluate(()=>window.dispatchEvent(new Event('pywebviewready')));
  await page.waitForFunction(()=>document.querySelector('#rows button'));
  const range=await page.evaluate(()=>[document.querySelector('[name=start]').value,document.querySelector('[name=end]').value]);
  assert.equal((new Date(range[1])-new Date(range[0]))/86400000,6);
  await page.locator('[data-action=open]').click();
  await page.waitForFunction(()=>messages.some(m=>m.cardId==='exact-card'));
  await page.locator('[data-action=review]').click();
  await page.locator('#review-note').fill('Checked field log');
  await page.locator('#save-review').click();
  await page.waitForFunction(()=>document.querySelector('[data-action=review]').textContent==='Edit review');
  assert.match(await page.locator('.review-audit-stamp').textContent(),/Test Reviewer · 09-11-26/);
  await page.screenshot({path:path.join(require('node:os').tmpdir(),'linguar-review-audit-stamp.png'),fullPage:true});
  await page.locator('#export').click();
  await page.waitForFunction(()=>window.exportedCSV);
  const exported=await page.evaluate(()=>exportedCSV);
  for(const value of ['Reviewer','Test Reviewer','2026-09-11T10:30:00','TO BE PRESERVED','front_ops','This PC only']) assert.ok(exported.includes(value),value);
  assert.equal(await page.locator('.review-progress progress').getAttribute('value'),'1');
  await page.locator('#result-search').fill('no matching record');
  assert.equal(await page.locator('#record-count').textContent(),'0 records');
  await page.locator('#export').click();
  assert.ok(!(await page.evaluate(()=>exportedCSV)).includes('Test review card'));
  assert.ok((await page.evaluate(()=>exportedCSV)).includes('no matching record'));
  await page.locator('#reset-results').click();
  assert.equal(await page.locator('#record-count').textContent(),'1 records');
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,'narrow view has no page overflow');
  await page.screenshot({path:path.join(require('node:os').tmpdir(),'linguar-analytics-narrow.png'),fullPage:true});
  await page.setViewportSize({width:1280,height:900});
  await page.locator('[name=review_role]').selectOption('field');
  await page.locator('#filters .primary').click();
  await page.waitForFunction(()=>document.querySelector('[data-action=review]').textContent==='Review');
  assert.equal(await page.locator('.review-status').textContent(),'Not reviewed');
  assert.equal(await page.locator('.review-audit-stamp').count(),0);
  await page.evaluate(()=>window.failLoad=true);
  await page.locator('#refresh').click();
  await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('read-only'));
  assert.equal(await page.locator('#records').evaluate(el=>el.inert),true);
  assert.equal(await page.locator('#export').isDisabled(),true);
  await page.evaluate(()=>window.failLoad=false);
  await page.locator('#refresh').click();
  await page.waitForFunction(()=>!document.querySelector('#records').inert);
  await page.evaluate(()=>{
    const row=state.data.rows[0];row.correction_revision='revision-token';
    state.data.review_store.reviews[row.review_key]={outcome:'follow_up',note:'Original correction',owner:'Lead',week:'2026-08-03'};
    window.pywebview.api.resolve_correction=async(key,version,note)=>{window.resolution={key,version,note};return {ok:true};};
    render();
  });
  await page.locator('[data-action=review]').click();
  assert.equal(await page.locator('#save-review').textContent(),'Resolve correction');
  assert.equal(await page.locator('#review-note').inputValue(),'');
  assert.equal(await page.locator('#review-owner').evaluate(el=>el.readOnly),true);
  await page.locator('#review-note').fill('Signed copy received');
  await page.locator('#save-review').click();
  await page.waitForFunction(()=>window.resolution);
  assert.deepEqual(await page.evaluate(()=>[resolution.version,resolution.note]),['revision-token','Signed copy received']);
  await page.waitForFunction(()=>!document.querySelector('#records').inert);
  await page.screenshot({path:path.join(require('node:os').tmpdir(),'linguar-analytics-workflow.png')});
  assert.deepEqual(errors,[]);
  console.log('PASS: stable week, exact-card opening, save/reload, audit stamps/export, role isolation, failed-load protection and recovery');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
