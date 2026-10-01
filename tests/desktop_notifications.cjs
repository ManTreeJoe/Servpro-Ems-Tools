const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:960,height:800}});
  const html=fs.readFileSync('notifications_web_assets/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace(/<link\b[^>]*>/g,'');
  await page.setContent(html);
  for(const file of ['web_shared/theme.css','notifications_web_assets/theme.css','notifications_web_assets/desktop.css'])await page.addStyleTag({path:path.resolve(file)});
  await page.evaluate(()=>{
   document.documentElement.dataset.theme='dark';window.saved=[];window.fail=false;
   window.pywebview={api:{desktop_settings:async mode=>{
    if(window.fail)return {ok:false,error:'Not saved'};
    if(mode)window.saved.push(mode);
    return {ok:true,available:true,mode:mode||'off'};
   },desktop_test:async()=>({ok:true})}};
  });
  await page.addScriptTag({path:path.resolve('notifications_web_assets/desktop.js')});
  await page.evaluate(()=>window.dispatchEvent(new Event('pywebviewready')));
  await page.locator('.desktop-alert-settings summary').click();
  await page.locator('#desktop-alert-mode').selectOption('mentions');
  assert.deepEqual(await page.evaluate(()=>saved),['mentions']);
  await page.locator('#desktop-alert-test').click();
  assert.match(await page.locator('#desktop-alert-status').textContent(),/Sent to Windows/);
  await page.evaluate(()=>window.fail=true);
  await page.locator('#desktop-alert-mode').selectOption('jobs');
  assert.equal(await page.locator('#desktop-alert-mode').inputValue(),'mentions');
  assert.match(await page.locator('#desktop-alert-status').textContent(),/Not saved/);
  await page.screenshot({path:path.join(require('node:os').tmpdir(),'oneloss-desktop-alert-settings.png')});
  assert.ok(await page.locator('.desktop-alert-settings').evaluate(el=>el.scrollWidth<=el.clientWidth));
  console.log('Desktop notification controls: PASS');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
