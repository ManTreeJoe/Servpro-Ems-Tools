const {chromium}=require('playwright');
const assert=require('node:assert/strict'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage();
 await page.addInitScript(()=>{
  const d=new Date(),day=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  window.rows=[{id:'visit',job_id:'job',title:'Test job',queue:'scheduled',group:'Work To Be Performed',date:day,activities:[{label:'Demo',people:['Sam']}],revision:1}];
  window.pywebview={api:{schedule_load:async()=>({ok:true,context:'ctx',department:'IE',records:structuredClone(window.rows)}),schedule_realtime:async()=>({ok:false,error:'offline'}),
   schedule_save:command=>new Promise(resolve=>{window.finishSave=ok=>{
    if(ok)window.rows=[{...window.rows[0],...command.visit,revision:2}];
    resolve(ok?{ok:true,saved:{revision:2}}:{ok:false,error:'Save rejected'});
   };})}};
 });
 await page.goto('file:///'+path.resolve('run_doc_editor_web_assets/calendar_preview.html').replaceAll('\\','/')+'?live=1');
 await page.locator('[data-edit="visit"]').waitFor();
 await page.evaluate(()=>{window.moving=moveVisit('visit',null,{queue:'tbs',group:'TBS Mitigation'});});
 assert.equal(await page.locator('.wc-waiting [data-edit="visit"]').count(),1,'Move must render before save resolves');
 assert.equal(await page.locator('.wc-day [data-edit="visit"]').count(),0);
 await page.evaluate(()=>window.finishSave(false));
 await page.evaluate(()=>window.moving);
 assert.equal(await page.locator('.wc-day [data-edit="visit"]').count(),1,'Failure restores original');
 await page.evaluate(()=>{window.moving=moveVisit('visit',null,{queue:'hold',group:'On Hold'});});
 assert.equal(await page.locator('.wc-waiting [data-edit="visit"]').count(),1);
 await page.evaluate(()=>window.finishSave(true));await page.evaluate(()=>window.moving);
 assert.equal(await page.locator('.wc-waiting [data-edit="visit"]').count(),1);
 console.log('PASS: immediate move before acknowledgement, rejection rollback, successful reconciliation');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
