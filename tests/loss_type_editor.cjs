const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1000,height:850},colorScheme:'dark'});
 await page.setContent('<div id="status-msg"></div>');
 for(const file of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/loss_types.css'])await page.addStyleTag({path:path.resolve(file)});
 await page.addScriptTag({path:path.resolve('pipeline_web_assets/app.js')});
 await page.evaluate(async()=>{
   window.saved=[];
   window.pywebview={api:{
     job_settings_schema:async()=>({ok:true,fields:[{id:'carrier',label:'Carrier',core:true},{id:'cause_of_loss',label:'Cause of loss',core:true},{id:'loss_categories',label:'Loss type',core:true}]}),
     job_settings_load:async()=>({ok:true,values:{carrier:'AAA',cause_of_loss:'Burst pipe',loss_categories:'Water'}}),
     job_settings_save:async(...args)=>{saved.push(args);return {ok:true};}
   }};
   await openJobInfoEditor({client:'Sample job',card_id:'card1'},{},()=>{});
 });
 await page.locator('[data-loss-type][value="Water"]').uncheck();
 await page.locator('[data-loss-type][value="Fire"]').check();
 await page.locator('[data-loss-type][value="Smoke"]').check();
 await page.locator('[data-loss-type][value="Bio"]').check();
 await page.locator('[data-loss-type][value="Cleaning"]').check();
 await page.screenshot({path:require('node:os').tmpdir()+'/oneloss-loss-types.png'});
 await page.getByRole('button',{name:'Save job info',exact:true}).click();
 assert.deepEqual(await page.evaluate(()=>saved[0][1]),{loss_categories:'Fire, Smoke, Bio, Cleaning'});
 assert.equal(await page.evaluate(()=>saved[0][4]),'card1');
 for (const explicit of [false,true]) {
   await page.evaluate(async explicit=>{
     pywebview.api.job_settings_load=async()=>({ok:true,loss_categories_explicit:explicit,values:{loss_categories:''}});
     await openJobInfoEditor({client:'Sample job',card_id:'card1',info_sections:[{fields:[{id:'loss_categories',value:'Bio, Cleaning'}]}]}, {}, ()=>{});
   },explicit);
   assert.equal(await page.locator('[data-loss-type][value="Bio"]').isChecked(),!explicit);
   assert.equal(await page.locator('[data-loss-type][value="Cleaning"]').isChecked(),!explicit);
   await page.getByRole('button',{name:'Cancel',exact:true}).click();
 }
 await page.evaluate(async()=>{
   window.retryCount=0;
   pywebview.api.job_settings_load=async()=>({ok:true,loss_categories_explicit:true,loss_label_context:{revision:'v1'},values:{loss_categories:'Water'}});
   pywebview.api.job_settings_save=async(...args)=>{
     saved.push(args);
     return ++retryCount===1 ? {ok:true,loss_labels_pending:true,pending_push:true,loss_label_context:{revision:'v2'},error:'Loss types saved; Trello sync pending.'} : {ok:true};
   };
   await openJobInfoEditor({client:'Sample job',card_id:'card1'}, {}, ()=>{});
 });
 await page.locator('[data-loss-type][value="Fire"]').check();
 await page.getByRole('button',{name:'Save job info',exact:true}).click();
 await page.getByRole('button',{name:'Retry Trello sync',exact:true}).waitFor();
 await page.screenshot({path:require('node:os').tmpdir()+'/oneloss-loss-label-retry.png'});
 await page.setViewportSize({width:430,height:850});
 await page.screenshot({path:require('node:os').tmpdir()+'/oneloss-loss-label-retry-mobile.png'});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth <= window.innerWidth));
 await page.setViewportSize({width:1000,height:850});
 await page.getByRole('button',{name:'Retry Trello sync',exact:true}).click();
 assert.equal(await page.locator('.job-info-edit-overlay').count(),0);
 assert.deepEqual(await page.evaluate(()=>saved.at(-1)[5]),{revision:'v2'});
 assert.equal(await page.evaluate(()=>saved.at(-1)[1].loss_categories),'Water, Fire');
 assert.equal(await page.evaluate(()=>mergeWorkspaceRefresh(
   {info_sections:[{name:'Property',fields:[{id:'loss_categories',value:'Water'}]}]},
   {info_sections:[{name:'Property',fields:[{id:'loss_categories',value:''}]}]}
 ).info_sections[0].fields[0].value),'');
 await page.evaluate(async()=>{
   pywebview.api.job_settings_load=async()=>({ok:true,values:{loss_categories:'Water'},loss_label_error:'Trello labels could not be verified.'});
   await openJobInfoEditor({client:'Sample job',card_id:'card1'}, {}, ()=>{});
 });
 assert.equal(await page.locator('[data-loss-type][value="Fire"]').isDisabled(),true);
 assert.equal(await page.locator('[data-job-info-input="carrier"]').isDisabled(),false);
 await page.getByRole('button',{name:'Cancel',exact:true}).click();
 console.log('PASS: loss types save independently without changing carrier or cause, scoped to exact card');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
