const {chromium}=require('playwright'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1000,height:800},colorScheme:'dark'});
 await page.setContent('<details id="history"></details>');
 for(const file of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/card_history.css'])await page.addStyleTag({path:path.resolve(file)});
 await page.addScriptTag({path:path.resolve('pipeline_web_assets/run_activity.js')});
 await page.evaluate(()=>{
  window.calls=[];window.pywebview={api:{
   card_activity_history:async()=>({ok:true,rows:[{at:'2026-10-02T12:00:00Z',actor:'Sam',source:'OneLoss',action:'Moved to Estimating'}]}),
   card_provider_activity:async()=>({ok:true,rows:[{id:'t',at:'2026-10-01T19:00:00Z',actor:'<b>Sam</b>',source:'Trello',action:'Checklist completed'}]}),
   saved_run_activity:(...args)=>{calls.push(args);return new Promise(resolve=>window.finish=resolve);}
  }};
  SavedRunActivity.mount(document.querySelector('#history'),'David Beal','EMS','card');
 });
 assert.equal(await page.evaluate(()=>calls.length),0);
 await page.evaluate(()=>document.querySelector('#history')._runActivity.activate());
 await page.waitForFunction(()=>document.querySelectorAll('.card-history-event').length===2);
 assert.deepEqual(await page.evaluate(()=>calls),[['David Beal','EMS']]);
 await page.evaluate(()=>finish({ok:true,rows:[{iso:'2026-09-24',labels:['Monitor'],techs:['Mark'],raw:'Scheduled work',source:'fixture.docx'}]}));
 await page.waitForFunction(()=>document.querySelector('[role=status]').textContent.includes('3 events'));
 assert.equal(await page.locator('.card-history-event').count(),3);
 assert.equal(await page.locator('.card-history-day h4').first().textContent(),'10/02/2026');
 assert.equal(await page.locator('.card-history-day h4').last().textContent(),'09/24/2026');
 assert.equal(await page.locator('.card-history-meta b').count(),0);
 assert.match(await page.locator('#history').textContent(),/not proof of completion/);
 assert.equal(await page.getByText('Legacy Run history',{exact:true}).count(),0);
 await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-combined-history.png')});
 await page.evaluate(()=>{
   pywebview.api.card_provider_activity=async()=>({ok:false,error:'Disconnected'});
   pywebview.api.saved_run_activity=async()=>({ok:true,rows:[]});
 });
 await page.getByRole('button',{name:'Refresh activity'}).click();
 await page.waitForFunction(()=>document.querySelector('[role=status]').textContent.includes('Showing previously loaded'));
 assert.equal(await page.locator('.card-history-event').count(),2);
 await page.setViewportSize({width:390,height:800});
 await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-combined-history-narrow.png')});
 console.log('PASS: combined history, partial loading, exact division, Pacific dates, failure retains prior events');
}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1});
