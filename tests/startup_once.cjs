const {chromium}=require('playwright'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage();
 await page.setContent('<button id="refresh-btn"></button><button id="settings-btn"></button>');
 await page.addScriptTag({path:path.resolve('home_web_assets/app.js')});
 await page.evaluate(()=>{
  window.counts={shell:0,interval:0};window.pywebview={api:{}};
  loadShell=async()=>{counts.shell++};maybeShowFirstRun=()=>{};maybeCheckUpdate=()=>{};updateConnectivity=()=>{};
  window.setInterval=()=>{counts.interval++};
  dispatchEvent(new Event('pywebviewready'));dispatchEvent(new Event('pywebviewready'));
 });
 await page.waitForTimeout(30);
 assert.deepEqual(await page.evaluate(()=>counts),{shell:1,interval:1});
 await page.setContent('<main></main>');
 await page.evaluate(()=>{delete window.pywebview;window.counts={health:0,interval:0};window.setInterval=()=>{counts.interval++};window.OneLossNotice={show(){}};});
 await page.route('https://startup.test/health_banner.js',route=>route.fulfill({path:path.resolve('web_shared/health_banner.js'),contentType:'application/javascript'}));
 await page.addScriptTag({url:'https://startup.test/health_banner.js'});
 await page.evaluate(()=>{window.pywebview={api:{health_state:async()=>{counts.health++;return {ok:true,problems:[]}}}};dispatchEvent(new Event('pywebviewready'));dispatchEvent(new Event('pywebviewready'));});
 assert.deepEqual(await page.evaluate(()=>counts),{health:1,interval:1});
 console.log('PASS: duplicate ready events create only one shell and health polling timer');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
