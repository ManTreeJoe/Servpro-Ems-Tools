const {chromium} = require('playwright');
const path = require('node:path'), assert = require('node:assert/strict');
(async () => {
 const browser = await chromium.launch({channel:'msedge', headless:true});
 try {
  const page = await browser.newPage();
  await page.route('http://localhost/**', r => r.fulfill({contentType:'text/html',body:'<div id="status-msg"></div>'}));
  await page.goto('http://localhost/');
  await page.addScriptTag({path:path.resolve('pipeline_web_assets/app.js')});
  await page.evaluate(async () => {
   window.pywebview = {api:{list_pics_stages:async () => {throw Error('Folder read unavailable');}}};
   try {await openXaStageModal('Fixture', 'X:/old');} catch (_) {}
  });
  assert.match(await page.locator('#status-msg').innerText(), /Folder read unavailable/);
  await page.evaluate(async () => {
   pywebview.api.list_pics_stages = async () => ({ok:true,job_path:'X:/resolved',stages:[{name:'Initial',count:1}]});
   pywebview.api.copy_pics_to_clipboard = async (...args) => {window.copyArgs=args; throw Error('Staging unavailable');};
   await openXaStageModal('Fixture','X:/old');
  });
  await page.locator('[data-stage]').click();
  await page.waitForFunction(() => !document.querySelector('[data-stage]').disabled);
  assert.match(await page.locator('#status-msg').innerText(), /Staging unavailable/);
  assert.equal(await page.evaluate(() => copyArgs[2]), 'X:/resolved');
  console.log('PASS: XA read/copy errors visible; button recovers; resolved folder retained.');
 } finally {await browser.close();}
})().catch(e => {console.error(e);process.exit(1);});
