const {chromium}=require('playwright');
const assert=require('node:assert/strict'),path=require('node:path'),os=require('node:os');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1000,height:700}});
  await page.route('https://notice.test/**',r=>r.fulfill({contentType:'text/html',body:'<button id="outside">Outside</button>'}));
  await page.goto('https://notice.test/');
  await page.clock.install();
  await page.addScriptTag({path:path.resolve('web_shared/toast_log.js')});
  const show=kind=>page.evaluate(kind=>OneLossNotice.show({panel:'notifications',kind,msg:'Saved job update',title:'Job updated'}),kind);
  await show('notification');
  await page.screenshot({path:path.join(os.tmpdir(),'oneloss-notice-timeout.png')});
  await page.clock.runFor(6000);
  await show('notification');
  assert.match(await page.locator('.ol-context').textContent(),/repeated 2/);
  await page.clock.runFor(2300);
  assert.equal(await page.locator('.ol-notice').count(),0,'Duplicates must not extend lifetime');
  for(const kind of ['warn','error']){
   await show(kind);
   await page.clock.runFor(11900);
   assert.equal(await page.locator('.ol-notice').count(),1);
   await page.clock.runFor(400);
   assert.equal(await page.locator('.ol-notice').count(),0,kind+' auto dismisses');
  }
  await show('notification');
  await page.clock.runFor(3000);
  await page.locator('.ol-notice').hover();
  await page.clock.runFor(15000);
  assert.equal(await page.locator('.ol-notice').count(),1,'Hover pauses timer');
  await page.mouse.move(0,0);
  await page.clock.runFor(5300);
  assert.equal(await page.locator('.ol-notice').count(),0,'Leaving resumes remaining time');
  await show('notification');
  await page.locator('.ol-notice button').first().focus();
  await page.clock.runFor(15000);
  assert.equal(await page.locator('.ol-notice').count(),1,'Keyboard focus pauses');
  await page.locator('#outside').focus();
  await page.clock.runFor(8300);
  assert.equal(await page.locator('.ol-notice').count(),0);
  assert.ok(await page.evaluate(()=>JSON.parse(localStorage.getItem('ems_toast_log')).length>=5),'History remains');
  await show('notification');
  await page.getByRole('button',{name:'Dismiss notification'}).click();
  assert.equal(await page.locator('.ol-notice').count(),0);
  await page.clock.runFor(20000);
  console.log('PASS notice expiry, duplicates, warnings/errors, hover, focus, manual dismissal and retained history');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
