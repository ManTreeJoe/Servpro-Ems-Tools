const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1280,height:900}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const html=fs.readFileSync('analytics_web_assets/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace(/<link\b[^>]*>/g,'');
 await page.route('http://flow.test/**',r=>r.fulfill({contentType:'text/html',body:html}));await page.goto('http://flow.test');
 await page.addStyleTag({path:path.resolve('web_shared/theme.css')});
 for(const file of ['app.css','workspace_layout.css','flow.css','theme_controls.css'])await page.addStyleTag({path:path.resolve('analytics_web_assets',file)});
 await page.evaluate(()=>{document.documentElement.dataset.theme='dark';window.messages=[];addEventListener('message',e=>messages.push(e.data));window.pywebview={api:{
 load_flow:async()=>{if(window.fail)return {ok:false,error:'Offline'};return {ok:true,location:'IE',source:'Test queues',lanes:['WORK IN PROGRESS','TBS NEW LOSS','TBS MITIGATION','TBS CONTENTS','TEST/CLEARANCE','PENDING APPROVALS','ON HOLD','SNAPSHOT','JUANTES','ZAC','KIM+ESTEBAN','AARON'].map((name,i)=>({id:String(i),board_id:i<7?'wip':'est',board:i<7?'WORK IN PROGRESS':'ESTIMATING',name,cards:[{id:'card'+i,name:'Sample job '+i}]}))};},
 flow_history:async()=>({ok:true,name:'Sample job',complete:true,current_seconds:null,periods:[],totals:[],estimator_cycles:[]})}};});
 for(const file of ['flow.js','app.js'])await page.addScriptTag({path:path.resolve('analytics_web_assets',file)});
 await page.evaluate(()=>dispatchEvent(new Event('pywebviewready')));await page.waitForSelector('[data-history]');
 assert.equal(await page.locator('#filters').isVisible(),false);
 await page.locator('[data-lane="6"]').click();assert.equal(await page.locator('[data-history]').count(),1);
 await page.locator('[data-flow-open]').click();await page.waitForFunction(()=>messages.some(m=>m.cardId==='card6'));
 await page.locator('[data-history]').click();await page.waitForSelector('#flow-history h3');
 assert.match(await page.locator('#flow-history').textContent(),/Unknown/);
 await page.keyboard.press('Escape');assert.equal(await page.locator('#flow-history').isVisible(),false);
 await page.locator('#flow-all').click();await page.locator('#flow-search').fill('Sample job 2');assert.equal(await page.locator('[data-history]').count(),1);
 await page.locator('#flow-search').fill('');
 assert.equal(await page.locator('body').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(23, 25, 28)');
 assert.equal(await page.locator('.flow-lane').first().evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(32, 35, 40)');
 await page.screenshot({path:path.join(os.tmpdir(),'oneloss-analytics-flow.png'),fullPage:true});
 await page.evaluate(()=>document.documentElement.dataset.theme='light');
 assert.equal(await page.locator('body').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(245, 247, 244)');
 assert.equal(await page.locator('.flow-lane').first().evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(255, 255, 255)');
 await page.evaluate(()=>document.documentElement.dataset.theme='dark');
 await page.evaluate(()=>window.fail=true);await page.locator('#refresh').click();await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('Offline'));
 assert.equal(await page.locator('[data-history]').count(),12);
 await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.emulateMedia({reducedMotion:'reduce'});await page.locator('[data-history]').first().click();assert.equal(await page.locator('#flow-history').evaluate(el=>getComputedStyle(el).animationName),'none');
 assert.deepEqual(errors,[]);console.log('PASS: queues, filters, exact card, unknown timing, failed refresh retains content, narrow layout, reduced motion');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
