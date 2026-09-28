const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:900,height:700}});
  await page.setContent('<style>.overlay{position:fixed;inset:0}.overlay-backdrop{position:absolute;inset:0}.overlay-panel{position:absolute;left:200px;top:200px;height:200px;background:white}</style>');
  await page.addScriptTag({path:path.resolve('web_shared/modal.js')});
  await page.evaluate(()=>openModal({title:'Test',width:400,body:'<input value="Draft">'}));
  await page.mouse.move(300,300);await page.mouse.down();await page.mouse.move(30,30);await page.mouse.up();
  assert.equal(await page.locator('.overlay').count(),1,'Inside-to-outside release must not close');
  await page.mouse.move(30,30);await page.mouse.down();await page.mouse.move(300,300);await page.mouse.up();
  assert.equal(await page.locator('.overlay').count(),1,'Outside-to-inside release must not close');
  await page.mouse.click(30,30,{button:'right'});
  assert.equal(await page.locator('.overlay').count(),1);
  await page.mouse.click(30,30);
  assert.equal(await page.locator('.overlay').count(),0,'Full backdrop click closes');
  console.log('PASS: backdrop requires full primary click; boundary drags stay open.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
