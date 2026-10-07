const {chromium}=require('playwright');
const assert=require('node:assert/strict'),path=require('node:path'),os=require('node:os');
const {pathToFileURL}=require('node:url');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(pathToFileURL(path.resolve('apa_web_assets/index.html')).href);
  await page.evaluate(()=>{
   window.pywebview={api:{get_franchise_list:async()=>[],get_franchise_filter:async()=>''}};
   loadInitialData=async()=>{window.bootCompleted=true;};
   window.dispatchEvent(new Event('pywebviewready'));
  });
  assert(await page.evaluate(()=>window.bootCompleted));
  assert.equal(await page.locator('#bulk-paste-btn,#open-word-btn').count(),0);
  assert(await page.locator('#paste-review-btn').isVisible());
  assert(await page.locator('#print-btn').isVisible());
  await page.locator('#more-btn').click();
  assert(await page.locator('#contacts-btn').isVisible());
  assert(await page.locator('#reveal-btn').isVisible());
  await page.screenshot({path:path.join(os.tmpdir(),'oneloss-apa-toolbar.png')});
  assert.deepEqual(errors,[]);
  console.log('PASS: APA boots without removed buttons; reconcile, print and More actions remain');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
