const {chromium}=require('playwright');
const assert=require('node:assert/strict'),path=require('node:path'),os=require('node:os');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  await page.goto('file:///'+path.resolve('run_doc_editor_web_assets/calendar_preview.html').replaceAll('\\','/'));
  await page.evaluate(()=>{window.pywebview={api:{get_crew_roster:async()=>({ok:true,entries:[
   {name:'Jose Diaz',aliases:['Jose']},{name:'Jose Manuel',aliases:['Jose M']},
   {name:'Vince',aliases:['Vicente']},...['Aaron P','Brenda','Cesar','Danny','Edwin','Elena','Fernando','George','Jesse','Johnny','Juan','Marco','Maria','Maricruz','Mario Nevarez','Mark E','Mark L','Melvin','Mike','Nestor','Pablo','PCB','Priscilla','Rafa','Robert','Rudy','Sam','Sergio','Uli','Wendy'].map(name=>({name,aliases:[]}))]})}};});
  await page.locator('.wc-week [data-edit]').first().click();
  await page.locator('#activity-picker summary').click();
  await page.locator('[data-activity="Demo"]').click();
  await page.locator('#activity-picker summary').click();
  const input=page.locator('[data-assignment]').first(), picker=page.locator('[data-crew-picker]').first();
  await picker.click();
  const panel=page.locator('.crew-popover:popover-open');
  await panel.getByText('Edit names manually',{exact:true}).click();
  await input.fill('Outside vendor');
  await panel.getByRole('button',{name:'Jose Diaz',exact:true}).click();
  assert.equal(await input.inputValue(),'Outside vendor, Jose Diaz');
  await panel.getByRole('button',{name:'Jose Manuel',exact:true}).click();
  assert.equal(await input.inputValue(),'Outside vendor, Jose Diaz, Jose Manuel');
  await panel.getByRole('button',{name:'Jose Diaz',exact:true}).click();
  assert.equal(await input.inputValue(),'Outside vendor, Jose Manuel');
  await panel.getByRole('searchbox').fill('Jose M');
  assert.equal(await panel.locator('.crew-options button').count(),1);
  await panel.getByRole('searchbox').fill('');
  await input.fill('Jose, Outside vendor, Jose Manuel');
  assert.equal(await panel.getByRole('button',{name:'Jose Diaz',exact:true}).getAttribute('aria-pressed'),'true');
  await panel.getByRole('button',{name:'Use this crew for all activities',exact:true}).click();
  assert.equal(await page.locator('[data-assignment]').nth(1).inputValue(),await input.inputValue());
  await panel.getByRole('button',{name:'Done',exact:true}).click();
  await page.locator('.crew-row').nth(1).getByRole('button',{name:'Remove Jose Manuel',exact:true}).click();
  assert.match(await input.inputValue(),/Jose Manuel/);
  assert(!/Jose Manuel/.test(await page.locator('[data-assignment]').nth(1).inputValue()));
  await page.getByRole('button',{name:'Apply sample edit',exact:true}).click();
  await page.locator('.wc-week [data-edit]').first().click();
  assert.match(await input.inputValue(),/Jose Manuel/);
  await page.screenshot({path:path.join(os.tmpdir(),'oneloss-schedule-editor-desktop.png')});
  await page.setViewportSize({width:540,height:800});
  await picker.scrollIntoViewIfNeeded();
  await picker.click();
  const box=await panel.boundingBox();assert(box.x>=0 && box.x+box.width<=540 && box.y>=0 && box.y+box.height<=800);
  await page.screenshot({path:path.join(os.tmpdir(),'oneloss-scheduling-roster.png')});
  await page.evaluate(()=>{window.pywebview.api.get_crew_roster=async()=>{throw new Error('offline')};});
  await page.evaluate(()=>ScheduleCrew.load());
  assert.match(await panel.locator('.crew-notice').textContent(),/unavailable/);
  await panel.getByText('Edit names manually',{exact:true}).click();
  await input.fill('Still editable');
  assert.equal(await input.inputValue(),'Still editable');
  await page.keyboard.press('Escape');
  assert(await page.locator('#editor').isVisible());
  assert.equal(await page.locator('.crew-popover:popover-open').count(),0);
  console.log('PASS: two Joses, aliases deduplicated, manual crew retained, reopen, narrow layout, offline fallback');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
