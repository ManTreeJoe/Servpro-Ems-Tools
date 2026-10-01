const {chromium}=require('playwright'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage();
 await page.setContent('<div id="feed"></div><span id="unread-pill"></span><div id="status-msg"></div><button id="refresh-btn">Refresh</button><input id="unread-only" type="checkbox"><button id="mark-all-btn">Mark all read</button>');
 await page.evaluate(()=>{window.mode='failure';window.PanelState={init:async()=>{},get:(_,fallback)=>fallback,set:()=>{}};window.pywebview={api:{mark_all_read:async()=>{if(mode==='throw')throw Error('bridge');return mode==='success'?{ok:true}:{ok:false,error:'Trello returned HTTP 403. Reconnect with write access.'};}}};});
 await page.addScriptTag({path:path.resolve('notifications_web_assets/app.js')});
 await page.evaluate(()=>{dispatchEvent(new Event('pywebviewready'));state.groups=[{board:'WIP',total:1,unread:1,items:[{id:'n',card_name:'Job',unread:true}]}];render();});
 for(const mode of ['failure','throw']){
  await page.evaluate(m=>window.mode=m,mode);await page.locator('#mark-all-btn').click();
  assert.equal(await page.locator('#mark-all-btn').isEnabled(),true);
  assert.equal(await page.locator('#unread-pill').textContent(),'1');
  assert.match(await page.locator('#status-msg').textContent(),mode==='failure'?/403/:/could not confirm/);
 }
 await page.evaluate(()=>window.mode='success');await page.locator('#mark-all-btn').click();
 assert.equal(await page.locator('#unread-pill').textContent(),'0');
 assert.equal(await page.locator('#status-msg').textContent(),'All marked read');
 console.log('PASS: mark-all success, actionable rejection, bridge failure and button recovery');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
