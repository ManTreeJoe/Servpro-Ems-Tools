const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage();
  await page.setContent('<div id="status-msg"></div>');
  for(const file of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js']) await page.addScriptTag({path:path.resolve(file)});
  await page.evaluate(()=>{
   window.reloads=0; window.onAuditCard=async()=>{reloads++; return new Promise(()=>{});};
   window.pywebview={api:{save_job_log_update:()=>new Promise(resolve=>window.finishSave=resolve)}};
   window.modal=openAuditModal({ok:true,client:'Fixture',card_id:'card',selected_division:'EMS',audit:{ok:true,found:true},
    crm:{ok:true,job_log:[]},comments:[{id:'c',text:'Keep this comment'}],checklists:[],documents:{files:[]}});
   window.originalModal=modal.element;
   window.commentInput=document.querySelector('[data-comment-input]');
  });
  await page.locator('[data-comment-input]').fill('Unsent draft');
  assert.deepEqual(await page.evaluate(()=>{
    state.board={boards:[{name:'EMS Work',lanes:[{name:'Scheduled',cards:[{card_id:'card'}]}]}]};
    return appCardPlacement('card');
  }),{board:'EMS Work',lane:'Scheduled',source:'app_board'});
  await page.evaluate(()=>{
    pywebview.api.job_docusketch_folder=async()=>({status:'found',path:'C:/Jobs/Fixture/DOCS/DocuSketch'});
    window.openJobFolderLinkModal=async(data,close,onLinked)=>{
      if(close) throw new Error('Folder pin must not close the workspace');
      await onLinked({ok:true,path:'C:/Jobs/Fixture'});
    };
  });
  await page.locator('[data-repin-job-folder]').evaluate(el=>el.click());
  assert.equal(await page.locator('[data-open-docs-folder]').first().isEnabled(),true);
  assert.equal(await page.locator('[data-copy-folder-path]').isEnabled(),true);
  assert.match(await page.locator('[data-docusketch-folder]').textContent(),/folder found/);
  assert.equal(await page.locator('[data-comment-input]').inputValue(),'Unsent draft');
  await page.locator('#job-tab-log').click();
  await page.locator('[data-add-job-log]').first().click();
  await page.locator('[data-save-job-log]').click();
  assert.equal(await page.evaluate(()=>originalModal.isConnected),true);
  assert.equal(await page.locator('[data-save-job-log]').isDisabled(),true);
  const started=Date.now();
  await page.evaluate(()=>finishSave({ok:true,entry:{entry_id:'new',source:'pc_only',work_date:'2026-09-22',work_type:'Monitor',note:'Saved update'},pending_sync:false}));
  await page.waitForTimeout(100);
  console.log(`After acknowledged save: ${Date.now()-started}ms, full reloads=${await page.evaluate(()=>reloads)}`);
  assert.equal(await page.evaluate(()=>reloads),0,'Saving must not trigger a full card reload');
  assert.equal(await page.evaluate(()=>originalModal.isConnected && commentInput===document.querySelector('[data-comment-input]')),true);
  assert.equal(await page.locator('[data-comment-input]').inputValue(),'Unsent draft');
  assert.equal(await page.locator('[data-job-log-id="new"]').count(),1);
  await page.evaluate(()=>modal.applyRefresh({ok:true,card_id:'card',crm:{ok:true,job_log:[]}}));
  assert.equal(await page.locator('[data-job-log-id="new"]').count(),1,'Late pre-save refresh must not erase saved row');
  await page.evaluate(()=>{pywebview.api.export_job_log_pdf=async payload=>{window.exportPayload=payload;return {ok:true,cancelled:true};};});
  await page.locator('[data-print-job-log]').click();
  assert.equal(await page.evaluate(()=>exportPayload.entries[0].entry_id),'new');
  assert.equal(await page.evaluate(()=>exportPayload.division),'EMS');
  await page.locator('[data-edit-job-log="new"]').click();
  await page.locator('[data-save-job-log]').click();
  await page.evaluate(()=>finishSave({ok:false,error:'Database refused save'}));
  await page.waitForTimeout(50);
  assert.equal(await page.locator('[data-save-job-log]').isEnabled(),true);
  assert.match(await page.locator('[data-job-log-editor]').textContent(),/Database refused save/);
  console.log('PASS: save updates log in place, preserves drafts, keeps failures editable.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
