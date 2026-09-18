const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.setContent('<div id="status-msg"></div>');
  for(const file of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css']) await page.addStyleTag({path:path.resolve(file)});
  for(const file of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js']) await page.addScriptTag({path:path.resolve(file)});
  await page.evaluate(()=>{
   document.documentElement.dataset.theme='dark';
   window.calls=[];window.posts=[];window.projectOpens=[];
   const row=(id,text)=>({id,text,source:'trello',actor:'Example coordinator',at:'2026-09-18T10:00:00Z'});
   window.pywebview={api:{
    refresh_job_comments:async card=>{calls.push(card);return {ok:true,comments:[row(card+'-comment',card==='contents-card'?'Contents packing update':'EMS inspection update')]};},
    post_job_comment:async(...args)=>{posts.push(args);return {ok:true,pending_sync:true,comment:row('new-comment',args[2])};},
    open_companycam_link:async(...args)=>{projectOpens.push(args);return true;},
   }};
   window.payload={ok:true,client:'Test customer',card_id:'ems-card',selected_division:'EMS',
    audit:{found:true},crm:{},info_sections:[{name:'Customer',fields:[{id:'address',label:'Address',value:'123 Test Street'}]}],
    division_trello_cards:[{division:'EMS',card_id:'ems-card',pinned:true},{division:'CONTENTS',card_id:'contents-card',pinned:true}],
    comments:[row('ems-comment','EMS inspection update')]};
   window.modal=openAuditModal(payload);
  });
  assert.equal(await page.locator('[data-comment-input]').isVisible(),true);
  assert.equal(await page.locator('[data-comment-division="ALL"]').count(),0);
  await page.locator('.tool-menu-trigger').filter({hasText:'CompanyCam'}).click();
  await page.locator('[data-open-companycam]').click();
  assert.deepEqual(await page.evaluate(()=>projectOpens),[['Test customer','ems-card']]);
  await page.locator('[data-comment-input]').fill('Unsent draft');
  await page.locator('[data-comment-division="CONTENTS"]').click();
  await page.waitForFunction(()=>document.querySelector('[data-comment-stream]').textContent.includes('Contents packing update'));
  assert.equal(await page.locator('[data-comment-id]').count(),1);
  assert.equal(await page.locator('[data-comment-division][aria-pressed="true"]').count(),1);
  await page.locator('[data-comment-division="CONTENTS"]').click();
  assert.equal(await page.locator('[data-comment-division][aria-pressed="true"]').count(),1);
  assert.deepEqual(await page.evaluate(()=>calls),['contents-card']);
  assert.equal(await page.locator('[aria-label="Post comment to division"]').inputValue(),'EMS');
  assert.equal(await page.locator('[data-comment-division="RECON"]').isDisabled(),true);
  await page.locator('[data-comment-search]').fill('packing');
  assert.equal(await page.locator('[data-comment-id]:visible').count(),1);
  await page.locator('#job-tab-files').click();
  assert.equal(await page.locator('[data-comment-input]').inputValue(),'Unsent draft');
  await page.locator('[aria-label="Post comment to division"]').selectOption('CONTENTS');
  await page.locator('[data-post-comment]').click();
  assert.deepEqual(await page.evaluate(()=>posts),[['Test customer','contents-card','Unsent draft']]);
  await page.locator('[data-comment-search]').fill('');
  assert.equal(await page.locator('[data-comment-id="new-comment"]').getAttribute('data-comment-card-id'),'contents-card');
  assert.match(await page.locator('[data-comment-state]').textContent(),/sync pending/);
  // A refresh started before posting must not erase the newly saved message.
  await page.evaluate(()=>{
   window.pywebview.api.refresh_job_comments=()=>new Promise(resolve=>window.finishRefresh=resolve);
   document.querySelector('[data-comment-division="EMS"]').click();
   window.refreshPromise=state.openWorkspace.conversation.refresh();
  });
  await page.waitForFunction(()=>!!window.finishRefresh);
  await page.evaluate(()=>{
   state.openWorkspace.conversation.add('contents-card',{id:'newer',text:'Just saved',source:'linguar'});
   finishRefresh({ok:true,comments:[]});
   return refreshPromise;
  });
  assert.equal(await page.locator('[data-comment-id="newer"]').count(),1);
  await page.evaluate(()=>{
   window.sameInput=document.querySelector('[data-comment-input]');
   sameInput.value='Still writing';
   window.unchangedAccepted=modal.applyIfUnchanged({...payload,load_ms:500,cached:false,comments:[]});
  });
  assert.equal(await page.evaluate(()=>unchangedAccepted),true);
  assert.equal(await page.evaluate(()=>sameInput===document.querySelector('[data-comment-input]')),true);
  assert.equal(await page.locator('[data-comment-input]').inputValue(),'Still writing');
  assert.equal(await page.locator('[data-comment-id="newer"]').count(),1);
  assert.equal(await page.evaluate(()=>modal.applyIfUnchanged({...payload,client:'Changed job'})),false);
  await page.evaluate(()=>{pywebview.api.refresh_job_comments=async()=>({ok:false,error:'Offline'});return state.openWorkspace.conversation.refresh();});
  assert.match(await page.locator('.comment-division-status').textContent(),/Offline/);
  assert.equal(await page.locator('[data-comment-id="newer"]').count(),1);
  await page.locator('#job-tab-overview').click();
  await page.screenshot({path:path.join(require('os').tmpdir(),'linguar-job-conversation-desktop.png')});
  assert.deepEqual(errors,[]);
  // Exercise the real New Loss dialog, not just the backend selection helper.
  await page.evaluate(()=>{
   modal.close(true);
   pywebview.api.new_loss_templates=async()=>({ok:true,default_template_id:'residential',templates:[
    {id:'commercial',name:'Water Commercial Template',kind:'water'},
    {id:'residential',name:'EMS - Residential Template',kind:'water'}]});
   pywebview.api.parse_new_loss=async()=>({ok:true,fields:{loss_type:'water',insured_name:'Test'}});
   pywebview.api.new_loss_folder_plan=async()=>({ok:true});
   openNewLossModal();
  });
  await page.waitForFunction(()=>document.querySelector('#nl-loss_type').value==='residential');
  await page.locator('#nl-paste').fill('Example assignment');
  await page.locator('#nl-parse').click();
  assert.equal(await page.locator('#nl-loss_type').inputValue(),'residential');
  await page.locator('#nl-loss_type').selectOption('commercial');
  await page.locator('#nl-parse').click();
  assert.equal(await page.locator('#nl-loss_type').inputValue(),'commercial');
  await page.locator('#nl-card_name').fill('');
  await page.locator('#nl-insured_name').fill('Nathan');
  await page.locator('#nl-carrier').fill('Cool beens');
  assert.equal(await page.locator('#nl-card_name').inputValue(),'Nathan - Cool beens');
  await page.locator('#nl-card_name').fill('Custom loss title');
  await page.locator('#nl-insured_name').fill('Nathan Example');
  assert.equal(await page.locator('#nl-card_name').inputValue(),'Custom loss title');
  assert.deepEqual(errors,[]);
  console.log('PASS: production job modal, linked-division filters, explicit post target, draft/search retention, late-refresh guard, New Loss default and manual selection.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
