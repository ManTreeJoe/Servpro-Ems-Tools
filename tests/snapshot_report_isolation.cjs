const {chromium}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage();
 const html=fs.readFileSync('snapshot_web_assets/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(/<link\b[^>]*>/gi,'');
 await page.setContent(html);
 await page.addScriptTag({path:path.resolve('snapshot_web_assets/app.js')});
 await page.evaluate(async()=>{
  window.calls=[];window.generated=null;window.opened=null;
  window.pywebview={api:{prefill_from_trello_card:async(...a)=>{calls.push(a);return {insured:'Report heading',logs:[{entry_id:'saved',date:'09/28/26',activity:'Pack out',techs:'ME'}],subs:[]};},
   check_multi_unit:async()=>({multi_unit:false}),generate:async p=>{generated=p;return {ok:true,path:'test.pdf',revision_saved:true,revision:1,rows_logs:1,rows_subs:0,job_log_unchanged:true};},open_pdf:async p=>{opened=p;}}};
  runSnapshotAudit=async()=>{};loadList=async()=>{};
  await startNew('Original job','contents-card','CONTENTS');
 });
 assert.deepEqual(await page.evaluate(()=>calls),[['contents-card','Original job','CONTENTS']]);
 await page.locator('#f-insured').fill('Edited display title');
 await page.locator('#logs-body [data-k="activity"]').fill('Report-only wording');
 const draft=await page.evaluate(()=>serializeSnapshotDraft());
 assert.equal(draft.sourceClient,'Original job');assert.equal(draft.division,'CONTENTS');
 await page.evaluate(d=>restoreSnapshotDraft(d),draft);
 await page.evaluate(()=>generate());
 const result=await page.evaluate(()=>generated);
 assert.equal(result.source_client,'Original job');assert.equal(result.card_id,'contents-card');assert.equal(result.division,'CONTENTS');
 assert.equal(result.logs[0].activity,'Report-only wording');assert.equal(await page.evaluate(()=>opened),'test.pdf');
 console.log('PASS: Snapshot exact-card prefill, draft restoration and report-only generation payload');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
