// A save acknowledgement must not put a newer status back to an old one.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage();
  await page.route(/^https?:/,r=>r.abort());
  await page.addInitScript(()=>{
   window.pendingSaves=[];
   window.pywebview={api:{get_pinned_card_for_item:async()=>({}),
    save_doc:(date,sections)=>new Promise(resolve=>pendingSaves.push({date,sections,resolve}))}};
  });
  await page.goto(pathToFileURL(path.resolve('apa_web_assets/index.html')).href);
  await page.evaluate(()=>{
   state.doc={date_iso:'2026-09-25',doc_exists:true,sections:[{name:'KIM',count:1,items:[{text:'Fixture-pending'}]}]};
   window.firstSave=saveDoc();
   state.doc.sections[0].items[0].text='Fixture-uploaded';
   window.secondSave=saveDoc();
  });
  await page.waitForFunction(()=>pendingSaves.length>=1);
  assert.equal(await page.evaluate(()=>pendingSaves.length),1,'Only one full-document write may run at a time');
  await page.evaluate(()=>{
   const first=pendingSaves[0];
   first.resolve({ok:true,doc:{date_iso:first.date,doc_exists:true,sections:first.sections}});
  });
  await page.evaluate(()=>firstSave);
  assert.equal(await page.locator('.item-text').innerText(),'Fixture-uploaded',
   'Earlier save response restored stale status while the newer save was pending');
  await page.waitForFunction(()=>pendingSaves.length===2);
  await page.evaluate(()=>{const next=pendingSaves[1];next.resolve({ok:true,doc:{date_iso:next.date,doc_exists:true,sections:next.sections}});});
  await page.evaluate(()=>secondSave);
  assert.equal(await page.locator('.item-text').innerText(),'Fixture-uploaded');
  console.log('PASS: stale acknowledgement cannot roll back newer visible status');
  await page.evaluate(async()=>{
   pywebview.api.status_options=async()=>({statuses:['pending','uploaded','extended'],subs:[],highlight:[]});
   const opening=openApaItemCtxMenu({preventDefault(){},stopPropagation(){},clientX:20,clientY:20},document.querySelector('.item'));
   // A save/refresh finishes while the menu is obtaining its options.
   state.doc=structuredClone(state.doc);
   await opening;
  });
  await page.locator('#apa-ctx-menu .apa-ctx-sub').filter({hasText:'Status'}).hover();
  await page.locator('.apa-ctx-submenu button').filter({hasText:/^\s*extended$/}).click();
  await page.waitForFunction(()=>pendingSaves.length===3);
  assert.equal(await page.evaluate(()=>pendingSaves[2].sections[0].items[0].text),'Fixture-extended',
   'Status menu must update the current card, not a detached pre-refresh object');
  console.log('PASS: status menu survives an equivalent document replacement');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
