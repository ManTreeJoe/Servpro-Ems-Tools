const {chromium}=require('playwright');
const path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:760,height:820}});
 await page.setContent('<main style="padding:24px"><section class="job-info-section">Job info</section></main>');
 await page.addStyleTag({path:path.resolve('web_shared/theme.css')});
 await page.addStyleTag({path:path.resolve('pipeline_web_assets/job_card_timing.css')});
 await page.addScriptTag({path:path.resolve('pipeline_web_assets/job_card_timing.js')});
 await page.evaluate(()=>{document.documentElement.dataset.theme='dark';window.calls=0;window.api={job_card_timing:async id=>{calls++;if(window.fail)throw Error('Offline');return {ok:true,complete:true,current_seconds:527400,periods:[{current:true,board:'ESTIMATING',lane:'JOHNNY',entered:'2026-10-01T17:20:00Z',actor:'Sample estimator',seconds:527400}],estimator_cycles:[{first_lane:'JOHNNY',started:'2026-10-01T17:20:00Z',seconds:527400}]};}};JobCardTiming.mount(document.querySelector('main'),'card',api);});
 await page.waitForSelector('.job-timing-section details');
 assert.match(await page.locator('.job-timing-heading').textContent(),/6d 2h/);
 await page.locator('summary').click();assert.match(await page.locator('ol').textContent(),/JOHNNY/);
 await page.screenshot({path:path.join(os.tmpdir(),'oneloss-job-card-timing.png')});
 await page.evaluate(()=>window.fail=true);await page.locator('button').click();await page.waitForFunction(()=>document.querySelector('[role=status]').textContent.includes('Offline'));
 assert.match(await page.locator('.job-timing-heading').textContent(),/6d 2h/);
 await page.setViewportSize({width:390,height:820});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.evaluate(()=>JobCardTiming.mount(document.querySelector('main'),'card',api));assert.equal(await page.locator('.job-timing-section').count(),1);
 console.log('PASS: job timing duration, history, failed refresh retains values, narrow layout, duplicate mount');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
