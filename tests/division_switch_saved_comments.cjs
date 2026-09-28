const {chromium}=require('playwright');
const assert=require('node:assert/strict'),path=require('node:path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage();
  await page.setContent('<div id="pane"><input class="comment-search"><div data-comment-stream></div><div class="comment-compose"><textarea>Draft stays</textarea></div></div>');
  await page.addScriptTag({path:path.resolve('pipeline_web_assets/job_conversation.js')});
  await page.evaluate(()=>{
   window.reads=0; window.refreshes=0;
   window.pane=JobConversation.mount(document.querySelector('#pane'),{
    division:'EMS',cardId:'ems',cards:[{division:'CONTENTS',card_id:'contents'}],
    comments:[],initialComplete:true,render:r=>`<p>${r.text}</p>`,
    fetchSaved:async card=>{reads++;return {ok:true,cached:true,comments:[{id:'saved',text:'Previously saved Contents'}]};},
    fetch:async()=>{refreshes++;return new Promise(r=>window.finish=r);}
   });
   document.querySelector('[data-comment-division="CONTENTS"]').click();
  });
  await page.waitForFunction(()=>document.querySelector('[data-comment-stream]').textContent.includes('Previously saved Contents'),null,{timeout:1500});
  assert.equal(await page.locator('textarea').inputValue(),'Draft stays');
  assert.equal(await page.evaluate(()=>refreshes),1);
  await page.evaluate(()=>{
   pane.add('contents',{id:'new',text:'Just posted'});
   finish({ok:true,comments:[{id:'stale',text:'Stale response'}]});
  });
  await page.waitForTimeout(30);
  assert.match(await page.locator('[data-comment-stream]').innerText(),/Just posted/);
  assert.doesNotMatch(await page.locator('[data-comment-stream]').innerText(),/Stale response/);
  console.log('PASS saved division comments appear while remote fetch is pending; draft and new post survive.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e.message);process.exitCode=1});
