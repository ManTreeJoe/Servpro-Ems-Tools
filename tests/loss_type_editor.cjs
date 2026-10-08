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
 console.log('PASS: loss types save independently without changing carrier or cause, scoped to exact card');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
