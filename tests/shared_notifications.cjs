const {chromium}=require('playwright');
const path=require('node:path'), assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:800},colorScheme:'dark'});
  await page.route('https://notice.test/**',route=>{
   const name=new URL(route.request().url()).pathname;
   if(name.endsWith('.js')||name.endsWith('.css')) return route.fulfill({path:path.resolve('.'+name)});
   return route.fulfill({contentType:'text/html; charset=utf-8',body:`<meta charset="utf-8"><link rel="stylesheet" href="/web_shared/theme.css">
    <body style="background:var(--bg);color:var(--text);font-family:Segoe UI;padding:24px">
    <h1>OneLoss · Jobs</h1><label>Comment <input id="draft" value="Unsaved draft"></label><div id="status"></div>
    <script>window.setStatus=(msg)=>{document.getElementById('status').textContent=msg;return 42;};</script>
    <script src="/web_shared/health_banner.js"></script></body>`});
  });
  await page.goto('https://notice.test/jobs/');
  await page.waitForFunction(()=>window._toastLogShim);
  await page.locator('#draft').focus();
  assert.equal(await page.evaluate(()=>setStatus('SupabaseError: HTTP 500: statement timeout; token=secret','error')),42);
  assert.equal(await page.locator('.ol-notice').count(),1);
  assert.match(await page.locator('.ol-notice strong').textContent(),/Connection needs attention/);
  assert.equal(await page.locator('.ol-notice [role=alert]').count(),1);
  assert.equal(await page.evaluate(()=>document.activeElement.id),'draft');
  assert.doesNotMatch(await page.locator('.ol-notice pre').textContent(),/secret/);
  await page.evaluate(()=>setStatus('SupabaseError: HTTP 500: statement timeout; token=secret','error'));
  assert.equal(await page.locator('.ol-notice').count(),1);
  assert.match(await page.locator('.ol-context').textContent(),/repeated 2 times/);
  assert.equal(await page.getByRole('button',{name:'Retry',exact:true}).count(),0);
  await page.screenshot({path:path.join(process.env.TEMP,'oneloss-shared-notice.png')});
  await page.getByRole('button',{name:'Dismiss notification'}).click();
  assert.equal(await page.evaluate(()=>_toastLog.read().length),2);
  await page.evaluate(()=>OneLossNotice.show({msg:'Could not refresh photos',retry:async()=>{window.retried=true;return {ok:true};}}));
  await page.getByRole('button',{name:'Retry',exact:true}).click();
  assert.equal(await page.evaluate(()=>retried),true);
  assert.equal(await page.locator('.ol-notice').count(),0);
  // A child frame forwards once to the shell, without double-writing history.
  const frameReady=page.waitForEvent('framenavigated', {predicate:f=>f.url().includes('/child/')});
  await page.evaluate(()=>{window._toastLog.clear();const f=document.createElement('iframe');f.src='/child/';document.body.append(f);});
  const frame=await frameReady;
  await frame.waitForFunction(()=>window._toastLogShim);
  await frame.evaluate(()=>setStatus('Photo import failed','error'));
  assert.equal(await page.locator('.ol-notice').count(),1);
  assert.equal(await frame.locator('.ol-notice').count(),0);
  assert.equal(await page.evaluate(()=>_toastLog.read().length),1);
  await page.evaluate(()=>window.dispatchEvent(new ErrorEvent('error',{message:'Example failure',error:new Error('Example failure')})));
  assert.match(await page.locator('.ol-notice').last().textContent(),/Something went wrong on this page/);
  await page.evaluate(()=>{for(let i=0;i<5;i++)OneLossNotice.show({msg:'Error '+i});});
  assert.equal(await page.locator('.ol-notice').count(),3);
  await page.setViewportSize({width:390,height:844});
  const bounds=await page.locator('#oneloss-notices').boundingBox();
  assert.ok(bounds.x>=0&&bounds.x+bounds.width<=390);
  await page.screenshot({path:path.join(process.env.TEMP,'oneloss-shared-notice-mobile.png')});
  console.log('PASS: shared loader, original status, focus, plain errors, redaction, deduplication, retry, history, iframe delivery, runtime errors, bounded stack, mobile layout');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
