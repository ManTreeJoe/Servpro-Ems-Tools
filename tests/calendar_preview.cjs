const {chromium}=require('playwright');
const assert=require('node:assert/strict'),path=require('node:path'),os=require('node:os');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1400,height:950}});
  await page.goto('file:///'+path.resolve('run_doc_editor_web_assets/calendar_preview.html').replaceAll('\\','/'));
  assert.equal(await page.locator('.wc-day').count(),3);
  assert.equal(await page.locator('.wc-waiting-group').count(),7);
  assert.match(await page.locator('.wc-waiting').textContent(),/TBS Contents/);
  assert.match(await page.locator('.wc-waiting').textContent(),/Property Management/);
  assert.match(await page.locator('.wc-waiting').textContent(),/On Hold/);
  assert.equal(await page.evaluate(()=>{const el=document.querySelector('.wc-day-items');el.scrollTop=150;return el.scrollTop>0;}),true);
  assert.equal(await page.getByText('Time not set',{exact:true}).count(),0);
  assert.equal(await page.evaluate(()=>{const el=document.querySelector('.wc-waiting-grid');el.scrollTop=200;return el.scrollTop>0;}),true);
  assert.equal(await page.evaluate(()=>document.querySelector('.wc-waiting').getBoundingClientRect().left>document.querySelector('.wc-week').getBoundingClientRect().left),true);
  await page.setViewportSize({width:1400,height:600});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollHeight>innerHeight),true);
  await page.setViewportSize({width:1400,height:950});
  const first=await page.locator('[data-day]').first().getAttribute('data-day');
  await page.getByRole('button',{name:'Next 3 days',exact:true}).click();
  assert.notEqual(await page.locator('[data-day]').first().getAttribute('data-day'),first);
  await page.getByRole('button',{name:'Today',exact:true}).click();
  await page.screenshot({path:path.join(os.tmpdir(),'calendar-three-days.png')});
  await page.locator('[data-period="month"]').click();
  assert.equal(await page.locator('.wc-month-day').count(),42);
  assert.equal(await page.locator('.wc-waiting-group').count(),7);
  await page.screenshot({path:path.join(os.tmpdir(),'calendar-month-view.png')});
  await page.getByRole('button',{name:'+ 10 more',exact:true}).first().click();
  assert.equal(await page.locator('.wc-day').count(),3);
  await page.locator('[data-period="month"]').click();
  await page.getByRole('button',{name:'Next month',exact:true}).click();
  await page.getByRole('button',{name:'Previous month',exact:true}).click();
  await page.getByRole('button',{name:'Legacy view',exact:true}).click();
  assert.equal(await page.locator('.run-paper section').count(),10);
  console.log('PASS: three-day/month navigation, month drilldown, seven visible waiting groups, column and page scrolling, Legacy sections');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
