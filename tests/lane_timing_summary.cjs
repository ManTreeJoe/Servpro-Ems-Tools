const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:390,height:844}});
 await page.setContent('<main></main>');
 await page.addStyleTag({path:path.resolve('web_shared/theme.css')});
 await page.addStyleTag({path:path.resolve('web_shared/lane_timing_summary.css')});
 await page.addScriptTag({path:path.resolve('web_shared/lane_timing_summary.js')});
 await page.evaluate(()=>document.querySelector('main').innerHTML=LaneTimingSummary.render({snapshot_cycles:[{started:'2026-10-01T17:00:00Z',ended:'2026-10-02T17:00:00Z',assigned_lane:'<Zac>',seconds:86400}],waiting_lanes:[{board:'WIP',lane:'ON HOLD',visits:2,unknown_visits:1,seconds:3600}],logs_arrivals:[{lane:'Received',entered:'2026-10-03T17:00:00Z'}],logs_age_seconds:null}));
 assert.match(await page.locator('main').textContent(),/Assigned to <Zac>/);
 assert.equal(await page.locator('zac').count(),0);
 assert.match(await page.locator('main').textContent(),/total is partial/);
 assert.match(await page.locator('main').textContent(),/Unknown/);
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 console.log('PASS: shared timing summaries, partial coverage, unknown Logs age, escaping and narrow layout');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
