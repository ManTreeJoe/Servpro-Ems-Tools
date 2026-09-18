const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.setContent('<div id="status-msg"></div>');
  for(const file of ['web_shared/theme.css','web_shared/modal.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css'])await page.addStyleTag({path:path.resolve(file)});
  for(const file of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(file)});
  await page.evaluate(()=>{
   window.pywebview={api:{}};
   window.payload={ok:true,client:'Loading test',card_id:'card1',selected_division:'EMS',audit:{ok:true,found:true},
    crm:{job_log:[{entry_id:'log1',source:'trello',work_type:'Inspection',note:'Saved inspection evidence'}]},
    checklists:[{id:'intake',name:'Intake',items:[]},{id:'est',name:'Estimating',items:[{id:'e1',name:'Review estimate',complete:false}]}],
    documents:{files:[{path:'C:/fixture/inspection.pdf',name:'Saved inspection.pdf'}]},comments:[]};
   window.modal=openAuditModal(payload);
  });
  const failures=[];
  await page.locator('#job-tab-requirements').click();
  await page.locator('[data-checklist-role="est"]').click();
  await page.locator('[data-comment-input]').focus();
  await page.evaluate(()=>modal.applyRefresh({...payload,comments:[{id:'c1',text:'Incoming comment'}]}));
  if(await page.locator('[data-checklist-role="est"]').getAttribute('aria-selected')!=='true') failures.push('Background hydration reset the selected checklist section');
  await page.locator('#job-tab-log').click();
  await page.locator('.job-log-source summary').click();
  await page.locator('[data-comment-input]').focus();
  await page.evaluate(()=>modal.applyRefresh({...payload,comments:[{id:'c2',text:'Another incoming comment'}]}));
  if(!await page.locator('.job-log-source').evaluate(node=>node.open)) failures.push('Background hydration collapsed the open evidence');
  await page.locator('#job-tab-files').click();
  await page.evaluate(()=>modal.applyRefresh({ok:true,card_id:'card1',deferred_loading:true,documents:{files:[]},audit:{audit_pending:true}}));
  if(!await page.locator('[data-document-path]').count()) failures.push('Partial hydration hid an already-saved file behind a loading placeholder');
  assert.deepEqual(errors,[]);
  assert.deepEqual(failures,[]);
  console.log('PASS: delayed hydration preserves checklist selection, expanded evidence and already-saved files.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
