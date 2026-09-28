const {chromium}=require('playwright'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setContent('<div id="status-msg"></div>');
 for(const f of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css'])await page.addStyleTag({path:path.resolve(f)});
 for(const f of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/job_drafts.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(f)});
 await page.evaluate(()=>{
  document.documentElement.dataset.theme='dark';window.savedDrafts=new Map();window.posts=[];
  window.pywebview={api:{job_draft:async(card,division,kind,id,change)=>{
   const key=[card,division,kind,id].join('|'),old=savedDrafts.get(key)||{version:0,payload:null,scope:'test'};
   if(change){if(change.version!==old.version)return {ok:false,error:'stale'};savedDrafts.set(key,{scope:'test',version:old.version+1,payload:change.payload});}
   return {ok:true,...(savedDrafts.get(key)||old)};
  },post_job_comment:async(...args)=>{posts.push(args);return {ok:true,comment:{id:'sent',text:args[2]}};}}};
  window.fixture={ok:true,client:'Draft fixture',card_id:'ems-card',selected_division:'EMS',audit:{found:true},crm:{job_log:[]},comments:[],division_trello_cards:[{division:'EMS',card_id:'ems-card',pinned:true}]};
  window.openFixture=()=>window.modal=openAuditModal(structuredClone(fixture));openFixture();
 });
 await page.locator('[data-comment-input]').fill('Recover this unsent message');
 await page.waitForFunction(()=>[...savedDrafts.values()].some(d=>d.payload?.text==='Recover this unsent message'));
 await page.locator('#job-tab-log').click();await page.locator('[data-add-job-log]').last().click();
 await page.locator('[data-log-field="note"]').fill('Recover this work note');await page.locator('[data-log-post-trello]').uncheck();
 await page.waitForFunction(()=>[...savedDrafts.values()].some(d=>d.payload?.note==='Recover this work note'&&d.payload.post_to_trello===false));
 await page.evaluate(()=>{modal.element.remove();openFixture();});
 await page.locator('.comment-compose').getByRole('button',{name:'Restore draft',exact:true}).click();
 assert.equal(await page.locator('[data-comment-input]').inputValue(),'Recover this unsent message');
 assert.deepEqual(await page.evaluate(()=>posts),[]);
 await page.locator('#job-tab-log').click();await page.locator('[data-add-job-log]').last().click();
 await page.locator('[data-job-log-editor]').getByRole('button',{name:'Restore draft',exact:true}).click();
 assert.equal(await page.locator('[data-log-field="note"]').inputValue(),'Recover this work note');
 assert.equal(await page.locator('[data-log-post-trello]').isChecked(),false);
 await page.locator('[data-cancel-job-log]').click();
 await page.locator('[data-post-comment]').click();
 await page.waitForFunction(()=>[...savedDrafts.values()].every(d=>d.payload===null));
 await page.evaluate(()=>{modal.element.remove();openFixture();});
 await page.waitForTimeout(350);
 assert.equal(await page.getByRole('button',{name:'Restore draft',exact:true}).count(),0);
 await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-draft-recovery.png')});
 assert.deepEqual(errors,[]);console.log('PASS: actual modal drafts recover without submission; cancel and acknowledged post clear recovery.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
