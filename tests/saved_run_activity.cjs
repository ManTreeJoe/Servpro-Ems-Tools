const {chromium}=require('playwright'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1200,height:900},colorScheme:'dark'});
 await page.setContent('<div id="status-msg"></div>');
 for(const file of ['web_shared/theme.css','pipeline_web_assets/app.css','web_shared/modal.css','pipeline_web_assets/job_workspace_tabs.css','pipeline_web_assets/job_files.css'])await page.addStyleTag({path:path.resolve(file)});
 for(const file of ['web_shared/modal.js','pipeline_web_assets/run_activity.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(file)});
 await page.evaluate(()=>{
  window.calls=[];window.pywebview={api:{saved_run_activity:(...args)=>{calls.push(args);return new Promise(resolve=>window.finish=resolve)}}};
  window.fixture={ok:true,client:'Fixture customer',card_id:'test-card',selected_division:'EMS',audit:{found:true},crm:{job_log:[]},comments:[]};
  window.job=openAuditModal(fixture);
 });
 assert.equal(await page.evaluate(()=>calls.length),0);
 await page.getByRole('tab',{name:'Run Activity',exact:true}).click();
 assert.deepEqual(await page.evaluate(()=>calls),[['Fixture customer','EMS']]);
 assert.doesNotMatch(await page.locator('.job-run-section').textContent(),/No activity/);
 await page.evaluate(()=>finish({ok:true,note:'Saved on this PC · Scheduled work',rows:[{iso:'2026-09-01',labels:['Demo'],raw:'Fixture customer: Demo scheduled',techs:['Crew A'],source:'fixture.docx'}]}));
 await page.locator('.saved-run-row').waitFor();
 await page.evaluate(()=>{window.originalRun=document.querySelector('.job-run-section');job.applyRefresh(fixture);});
 assert.equal(await page.evaluate(()=>originalRun===document.querySelector('.job-run-section')),true);
 assert.equal(await page.evaluate(()=>calls.length),1);
 await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-run-history.png')});
 await page.getByRole('button',{name:'Refresh saved history'}).click();
 await page.evaluate(()=>finish({ok:false,error:'Read failed'}));
 await page.waitForFunction(()=>document.querySelector('.job-run-section [role=status]').textContent.includes('Read failed'));
 assert.equal(await page.locator('.saved-run-row').count(),1,'Keep saved rows on failed refresh');
 console.log('PASS: run history lazy load, exact division, refresh preservation, failed refresh retains rows');
}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1});
