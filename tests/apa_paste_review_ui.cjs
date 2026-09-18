const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1280,height:900}});
 await page.setContent('<html><body></body></html>');
 await page.addStyleTag({path:'apa_web_assets/app.css'});
 await page.addStyleTag({path:'apa_web_assets/paste_review.css'});
 await page.evaluate(()=>{
  const row={customer:'LINDA SAMPLE',claim:'000123:CON',division:'contents',requirement:'initial',due:'9/18/2026 8:55 AM',state:'pending',existing:[],candidates:[{card_id:'c1',name:'Sample, Linda — Contents',board:'Contents',list_name:'PABLO'}]};
  const batch={id:'demo',day:'2026-09-18',rows:[row]};
  window.pywebview={api:{paste_review:async(op,p)=>{
   if(op==='recent')return {ok:true,batch:null};
   if(op==='start')return {ok:true,batch};
   if(op==='inspect')return {ok:true,row,lanes:['Initial Uploads','PABLO']};
   if(op==='choose')return {ok:true,selection:{card_id:'c1',name:row.candidates[0].name,board:'Contents',trello_lane:'PABLO',description:'Claim Number: 000123:CON',lane:'Initial Uploads',sub:'AARON'}};
   if(op==='commit'){window.lastCommit=p;row.state='added';return {ok:true,batch};}
  }}};
 });
 await page.addScriptTag({path:'apa_web_assets/paste_review.js'});
 await page.evaluate(()=>ApaPasteReview.open('2026-09-18',()=>{}));
 await page.locator('textarea').fill('fixture');
 await page.locator('[data-start]').click();
 await page.locator('[data-match]').click();
 assert.equal(await page.locator('#apa-review-lane').inputValue(),'Initial Uploads');
 assert.equal(await page.locator('#apa-review-sub').inputValue(),'AARON');
 await page.screenshot({path:'../tmp/apa-review-desktop.png'});
 await page.setViewportSize({width:520,height:800});
 assert.equal(await page.locator('dialog').evaluate(el=>el.scrollWidth<=el.clientWidth),true);
 await page.screenshot({path:'../tmp/apa-review-narrow.png'});
 assert.equal(await page.locator('[data-confirm]').count(),0);
 assert.equal(await page.locator('[data-distinct]').count(),0);
 await page.locator('[data-add]').click();
 assert.match(await page.locator('[data-status]').textContent(),/Review complete/);
 assert.equal(await page.evaluate(()=>lastCommit.lane),'Initial Uploads');
 assert.equal(await page.evaluate(()=>lastCommit.confirmed),true);
 await browser.close();console.log('PASS: review UI routing, single-click approval, completion and narrow layout');
})().catch(e=>{console.error(e);process.exitCode=1;});
