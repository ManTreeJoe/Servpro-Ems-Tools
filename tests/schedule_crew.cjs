const {chromium}=require('playwright');
const assert=require('node:assert/strict'),path=require('node:path'),os=require('node:os');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  await page.goto('file:///'+path.resolve('run_doc_editor_web_assets/calendar_preview.html').replaceAll('\\','/'));
  await page.evaluate(()=>{window.pywebview={api:{get_crew_roster:async()=>({ok:true,entries:[
   {name:'Jose Diaz',aliases:['Jose']},{name:'Jose Manuel',aliases:['Jose M']},
   {name:'Vince',aliases:['Vicente']}]})}};});
  await page.locator('.wc-week [data-edit]').first().click();
  const input=page.locator('[data-assignment]').first(), picker=page.locator('[data-crew-picker]').first();
  await input.fill('Jose, Outside vendor');
  await picker.selectOption('Jose Diaz');
  assert.equal(await input.inputValue(),'Outside vendor, Jose Diaz');
  await picker.selectOption('Jose Manuel');
  assert.equal(await input.inputValue(),'Outside vendor, Jose Diaz, Jose Manuel');
  await picker.selectOption('Jose Diaz');
  assert.equal((await input.inputValue()).split('Jose Diaz').length,2);
  await page.getByRole('button',{name:'Apply sample edit',exact:true}).click();
  await page.locator('.wc-week [data-edit]').first().click();
  assert.match(await input.inputValue(),/Jose Manuel/);
  await page.setViewportSize({width:540,height:800});
  await picker.scrollIntoViewIfNeeded();
  const box=await picker.boundingBox();assert(box.x>=0 && box.x+box.width<=540);
  await page.screenshot({path:path.join(os.tmpdir(),'oneloss-scheduling-roster.png')});
  await page.evaluate(()=>{window.pywebview.api.get_crew_roster=async()=>{throw new Error('offline')};});
  await page.evaluate(()=>ScheduleCrew.load());
  assert(await picker.isDisabled());
  await input.fill('Still editable');
  assert.equal(await input.inputValue(),'Still editable');
  console.log('PASS: two Joses, aliases deduplicated, manual crew retained, reopen, narrow layout, offline fallback');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
