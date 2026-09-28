const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.setContent('<div id="status-msg"></div>');
  for(const file of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css'])await page.addStyleTag({path:path.resolve(file)});
  for(const file of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(file)});
  await page.evaluate(()=>{
   document.documentElement.dataset.theme='dark';
   window.calls=[];window.pending=[];
   window.cards=['EMS','CONTENTS','RECON'].map(division=>({division,card_id:division,pinned:true}));
   window.payload=division=>({ok:true,client:'Division test',card_id:division,selected_division:division,audit:{found:true},crm:{},division_trello_cards:cards,comments:[{id:division+'-comment',text:division+' message',source:'trello'}]});
   window.pywebview={api:{job_card_workspace_fast:(client,id,division)=>{calls.push([id,division]);return new Promise(resolve=>pending.push(()=>resolve(payload(division))));},job_card_workspace:async(client,id,division)=>payload(division),refresh_job_comments:async()=>({ok:true,comments:[]})}};
   openAuditModal(payload('EMS'));
  });
  assert.equal(await page.locator('[data-division-data]').count(),3);
  assert.equal(await page.locator('.audit-summary').count(),0);
  assert.equal(await page.getByRole('heading',{name:'Saved audit',exact:true}).count(),0);
  assert.equal(await page.locator('[data-run-folder-audit]').count(),1,'Requirements keeps its explicit file check');
  const tabs=await page.locator('.job-division-folder-tabs').boundingBox(),title=await page.locator('.modal-title').first().boundingBox();
  assert.ok(tabs.y+tabs.height<=title.y);
  await page.locator('[data-comment-input]').fill('Keep this draft');
  page.once('dialog',d=>d.dismiss());
  await page.locator('[data-division-data="CONTENTS"]').click();
  assert.equal(await page.locator('[data-comment-input]').inputValue(),'Keep this draft');
  assert.deepEqual(await page.evaluate(()=>calls),[]);
  page.once('dialog',d=>d.accept());
  await page.locator('[data-division-data="CONTENTS"]').click();
  assert.equal(await page.locator('[data-division-data="CONTENTS"]').getAttribute('aria-selected'),'true');
  assert.equal(await page.locator('[data-comment-division="CONTENTS"]').getAttribute('aria-pressed'),'true');
  assert.equal(await page.locator('[data-comment-destination="CONTENTS"]').getAttribute('aria-pressed'),'true');
  assert.ok(!(await page.locator('[data-comment-stream]').innerText()).includes('EMS message'));
  await page.locator('[data-division-data="RECON"]').click();
  await page.evaluate(()=>pending.splice(0).reverse().forEach(resolve=>resolve()));
  await page.waitForFunction(()=>document.querySelector('[data-comment-stream]').textContent.includes('RECON message'));
  assert.equal(await page.locator('[data-division-data="RECON"]').getAttribute('aria-selected'),'true');
  assert.deepEqual(await page.evaluate(()=>calls),[['CONTENTS','CONTENTS'],['RECON','RECON']]);
  await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-division-folder-tabs.png')});
  await page.evaluate(()=>{document.querySelector('.modal-wrap')?.remove();const p=payload('EMS');p.division_card_reconciliation={divisions:[{division:'CONTENTS',state:'conflict'}]};p.division_trello_cards=cards.slice(0,2);openAuditModal(p);});
  assert.equal(await page.locator('[data-division-data="CONTENTS"]').last().isDisabled(),true);
  assert.equal(await page.locator('[data-division-data="RECON"]').last().isDisabled(),true);
  assert.deepEqual(errors,[]);
  console.log('Job division folder tabs: passed');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
