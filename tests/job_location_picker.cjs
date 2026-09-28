const {chromium}=require('playwright'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});await page.setContent('<div id="status-msg"></div>');
 for(const file of ['web_shared/theme.css','web_shared/modal.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css'])await page.addStyleTag({path:path.resolve(file)});
 for(const file of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(file)});
 await page.evaluate(()=>{
  window.moves=[];window.copies=[];window.pywebview={api:{copy_to_clipboard:async value=>copies.push(value),
   card_placement_context:async()=>({ok:true,placement:{board_id:'wip',list_id:'intake',version:7},boards:[
    {board_id:'wip',name:'Work in progress',lists:[{id:'intake',name:'Intake'},{id:'active',name:'Active'}]},
    {board_id:'estimate',name:'Estimating',lists:[{id:'review',name:'Review'},{id:'closed',name:'Hidden',closed:true}]}
   ]}),card_placement_change:(...args)=>{moves.push(args);return new Promise(resolve=>window.finishMove=resolve)} }};
  window.job=openAuditModal({ok:true,client:'Test customer',card_id:'ems-card',selected_division:'EMS',audit:{found:true},
   app_placement:{board:'Work in progress',lane:'Intake'},crm:{job_log:[]},comments:[],
   info_sections:[{name:'Customer',fields:[{id:'phone',label:'Phone',value:'555-0100'}]}]});
 });
 await page.locator('[data-copy-job-field="555-0100"]').click();assert.deepEqual(await page.evaluate(()=>copies),['555-0100']);
 await page.locator('[data-comment-input]').fill('Unsent draft');
 await page.locator('[data-move-job-location="app_lane"]').click();
 await page.waitForSelector('#placement-action [data-section]');
 assert.equal(await page.locator('#placement-action [data-section]').inputValue(),'intake');
 await page.locator('#placement-action [data-board]').selectOption('estimate');
 assert.equal(await page.locator('#placement-action [data-section] option').count(),1);
 await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-job-location-picker.png')});
 await page.locator('#placement-action [data-save]').click();
 assert.deepEqual(await page.evaluate(()=>moves[0]),['ems-card','move',7,'estimate','review']);
 assert.equal(await page.locator('[data-move-job-location="app_lane"] strong').textContent(),'Intake');
 assert.equal(await page.locator('#placement-action [data-board]').isDisabled(),true);
 await page.evaluate(()=>finishMove({ok:false,error:'Version conflict'}));
 await page.waitForFunction(()=>document.querySelector('#placement-action [data-error]').textContent.includes('Version conflict'));
 assert.equal(await page.locator('[data-move-job-location="app_lane"] strong').textContent(),'Intake');
 await page.locator('#placement-action [data-save]').click();await page.evaluate(()=>finishMove({ok:true}));
 await page.waitForSelector('#placement-action',{state:'detached'});
 assert.equal(await page.locator('[data-move-job-location="app_board"] strong').textContent(),'Estimating');
 assert.equal(await page.locator('[data-move-job-location="app_lane"] strong').textContent(),'Review');
 assert.equal(await page.locator('[data-comment-input]').inputValue(),'Unsent draft');
 console.log('PASS: location dropdowns, scoped lanes, confirmed update, failed-save retention and draft/copy preservation');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
