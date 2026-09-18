const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.setContent('<div id="status-msg"></div><button id="fixture-card">Saved job</button>');
  for(const file of ['web_shared/theme.css','web_shared/modal.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css'])await page.addStyleTag({path:path.resolve(file)});
  for(const file of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(file)});
  await page.evaluate(()=>{
   window.copied=[];window.checked=[];
   window.pywebview={api:{job_card_workspace_fast:()=>new Promise(resolve=>window.finishFast=resolve),job_card_workspace:()=>new Promise(resolve=>window.finishFull=resolve),copy_to_clipboard:async value=>copied.push(value),set_job_check_item:async(...args)=>{checked.push(args);return {ok:true};}}};
   const card=document.querySelector('#fixture-card');
   Object.assign(card.dataset,{client:'Saved job',cardId:'card1',division:'EMS',cardSummary:JSON.stringify({job_info:{customer_name:'Saved customer',phone:'555-0100'}})});
   window.opening=onAuditCard(card);
   window.originalRoot=document.querySelector('.audit-overlay');
   window.originalInput=document.querySelector('[data-comment-input]');
   window.initialFacts=document.querySelector('.job-info-section');
  });
  await page.evaluate(()=>finishFast({ok:true,client:'Saved job',card_id:'card1',selected_division:'EMS',deferred_loading:true,audit:{found:true},crm:{},info_sections:[],comments:[]}));
  await page.waitForFunction(()=>!!window.finishFull);
  assert.equal(await page.evaluate(()=>originalRoot.isConnected),true,'DB response replaced the entire card');
  assert.match(await page.locator('.job-info-section').textContent(),/555-0100/,'empty partial response erased saved facts');
  await page.locator('[data-comment-input]').fill('Keep my draft');
  await page.locator('#job-tab-files').click();
  await page.evaluate(()=>{window.fileSection=document.querySelector('.signatures-section');finishFull({ok:true,client:'Saved job',card_id:'card1',selected_division:'EMS',audit:{found:true,path:'C:/Saved'},crm:{},info_sections:[{name:'Customer Information',fields:[{id:'phone',label:'Phone',value:'555-0199'}]}],comments:[{id:'c1',text:'Ready for billing',source:'trello'}],division_trello_cards:[{division:'EMS',card_id:'card1',pinned:true},{division:'CONTENTS',card_id:'contents1',pinned:true}],checklists:[{id:'list1',name:'Front Office',items:[{id:'check1',name:'Verify job',complete:false}]}]});return opening;});
  assert.equal(await page.evaluate(()=>originalRoot.isConnected && originalInput===document.querySelector('[data-comment-input]')),true);
  assert.equal(await page.locator('[data-comment-input]').inputValue(),'Keep my draft');
  assert.equal(await page.locator('#job-tab-files').getAttribute('aria-selected'),'true');
  assert.match(await page.locator('.job-info-section').textContent(),/555-0199/);
  assert.match(await page.locator('.job-info-section').textContent(),/Saved customer/);
  assert.match(await page.locator('[data-comment-stream]').textContent(),/Ready for billing/);
  assert.equal(await page.locator('[data-comment-division="CONTENTS"]').isDisabled(),false);
  assert.equal(await page.evaluate(()=>{
   const files=document.querySelector('.signatures-section'),facts=document.querySelector('.job-info-section');
   state.openWorkspace.applyRefresh({ok:true,card_id:'card1',comments:[{id:'c1',text:'Ready for billing',source:'trello'}]});
   return files===document.querySelector('.signatures-section') && facts===document.querySelector('.job-info-section');
  }),true,'unchanged sections were replaced');
  await page.locator('#job-tab-overview').click();
  await page.locator('[data-copy-job-field="555-0199"]').click();
  assert.deepEqual(await page.evaluate(()=>copied),['555-0199']);
  await page.locator('#job-tab-requirements').click();
  await page.locator('[data-check-item="check1"]').check();
  assert.deepEqual(await page.evaluate(()=>checked),[['card1','check1',true,'Verify job','Saved job']]);
  await page.evaluate(()=>state.openWorkspace.applyRefresh({ok:true,card_id:'card1',checklists:[],comments:[],audit:{trello_error:'Offline'}}));
  assert.equal(await page.locator('[data-check-item="check1"]').isChecked(),true,'refresh overwrote a checklist edit');
  assert.match(await page.locator('[data-comment-stream]').textContent(),/Ready for billing/,'failed refresh erased known comments');
  assert.equal(await page.locator('[data-comment-input]').inputValue(),'Keep my draft');
  assert.deepEqual(errors,[]);
  console.log('PASS: partial data never blanks the card; changed facts and comments update in place, preserving draft/tab and action bindings.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
