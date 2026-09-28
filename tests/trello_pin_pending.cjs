const {chromium}=require('playwright');
const path=require('node:path'), assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage();
  await page.setContent('<div id="status-msg"></div>');
  await page.addScriptTag({path:path.resolve('pipeline_web_assets/app.js')});
  await page.evaluate(()=>{
   const nativeTimer=window.setTimeout;
   window.setTimeout=(fn,ms,...args)=>nativeTimer(fn,ms===12000?30:ms,...args);
   window.calls=0; window.acknowledged=0;
   window.pywebview={api:{
    global_card_search:async()=>({ok:true,cards:[]}),
    pin_crm_division_trello:()=>{calls++;return new Promise(resolve=>window.finishPin=resolve);}
   }};
   window.target={dataset:{client:'Fixture',division:'EMS'}};
   openChangePinnedTrelloCard(target,()=>{acknowledged++;});
  });
  await page.locator('[data-direct-input]').fill('Abcd1234');
  await page.locator('[data-direct-form] button').click();
  await page.waitForTimeout(70);
  assert.match(await page.locator('[data-results]').textContent(),/Still waiting/);
  await page.locator('[data-direct-form] button').click();
  assert.equal(await page.evaluate(()=>calls),1);
  await page.locator('[data-close]').click();
  await page.evaluate(()=>openChangePinnedTrelloCard(target));
  await page.locator('[data-direct-input]').fill('DifferentCard');
  await page.locator('[data-direct-form] button').click();
  assert.equal(await page.evaluate(()=>calls),1,'Reopening must not allow a competing save');
  await page.locator('[data-direct-input]').fill('Abcd1234');
  await page.locator('[data-direct-form] button').click();
  await page.evaluate(()=>finishPin({ok:true,card_id:'Abcd1234',info_pull_pending:true}));
  await page.waitForTimeout(50);
  assert.equal(await page.locator('.trello-pin-overlay').count(),0);
  assert.equal(await page.evaluate(()=>calls),1);
  assert.equal(await page.evaluate(()=>acknowledged),1);
  assert.match(await page.locator('#status-msg').textContent(),/background/);
  console.log('PASS: slow save retained, retry blocked, late success acknowledged');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
