const {chromium}=require('playwright');
const assert=require('node:assert/strict'),path=require('node:path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1400,height:950}});
  await page.goto('file:///'+path.resolve('run_doc_editor_web_assets/calendar_preview.html').replaceAll('\\','/'));
  const original=await page.evaluate(()=>structuredClone(records.find(r=>r.queue==='tbs')));
  const card=()=>page.locator(`[data-edit="${original.id}"]`);
  await card().dragTo(page.locator('.wc-day-heading').first());
  await page.waitForFunction(id=>records.find(r=>r.id===id).queue==='scheduled',original.id);
  assert.equal(await page.evaluate(id=>records.find(r=>r.id===id).queue,original.id),'scheduled');
  const target=page.locator('.wc-waiting-group').filter({has:page.locator('h3',{hasText:original.group})});
  await card().dragTo(target.locator('h3'));
  await page.waitForFunction(()=>!document.querySelector('.wc-pointer-ghost'));
  const returned=await page.evaluate(id=>records.find(r=>r.id===id),original.id);
  assert.equal(returned.queue,'tbs','Dropping back onto waiting work must unschedule the visit');
  assert.equal(returned.group,original.group);
  assert.equal(returned.date,null);
  assert.deepEqual(returned.activities,original.activities);
  assert.equal(await card().count(),1);
  assert.equal(await page.locator('#editor').isVisible(),false);
  // Empty waiting groups are valid destinations too.
  await page.evaluate(()=>{const retained=records.filter(r=>r.queue!=='hold');records.splice(0,records.length,...retained);calendar.update({records});});
  await card().dragTo(page.locator('.wc-waiting-group').filter({has:page.locator('h3',{hasText:'On Hold'})}).locator('h3'));
  await page.waitForFunction(()=>!document.querySelector('.wc-pointer-ghost'));
  assert.equal(await page.evaluate(id=>records.find(r=>r.id===id).queue,original.id),'hold');
  await page.screenshot({path:require('node:os').tmpdir()+'/oneloss-return-waiting.png'});
  console.log('PASS: return to waiting group, empty hold target, no duplicates or editor open, crew preserved');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
