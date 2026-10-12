const {chromium}=require('playwright');
const assert=require('node:assert/strict'),path=require('node:path'),os=require('node:os');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  await page.setContent('<main id="schedule" data-layout="dispatch"></main>');
  await page.addStyleTag({path:path.resolve('web_shared/theme.css')});
  await page.addStyleTag({path:path.resolve('run_doc_editor_web_assets/weekly_calendar.css')});
  await page.addScriptTag({path:path.resolve('run_doc_editor_web_assets/weekly_calendar.js')});
  await page.evaluate(()=>{
   document.documentElement.dataset.theme='dark';
   window.calendar=OneLossWeeklyCalendar.mount(document.querySelector('#schedule'),{date:'2026-10-08',onEdit:id=>window.edited=id});
   calendar.update({records:['Reinspection','Work to be reviewed','Monitor'].map((label,i)=>({id:String(i),title:['Inspection follow-up','Work review','Drying check'][i],queue:'tbs',group:'TBS New Loss /Reinspection',since:'2026-10-07',activities:[{label}]}))});
  });
  const cards=page.locator('.wc-waiting .wc-visit');
  assert.deepEqual(await cards.evaluateAll(els=>els.map(el=>el.dataset.color)),['reinspection','review','monitor']);
  for(const card of await cards.all()){
   const style=await card.evaluate(el=>{const s=getComputedStyle(el);return {border:s.borderLeftWidth,background:s.backgroundImage};});
   assert.equal(style.border,'6px');
   assert.match(style.background,/linear-gradient/);
  }
  await cards.first().click();
  assert.equal(await page.evaluate(()=>window.edited),'0');
  await page.locator('.wc-waiting').screenshot({path:path.join(os.tmpdir(),'oneloss-waiting-colors.png')});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.locator('.wc-waiting').evaluate(el=>el.scrollWidth<=el.clientWidth),true);
  console.log('PASS: waiting activity colors, visible accents, edit callback, narrow sidebar');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
