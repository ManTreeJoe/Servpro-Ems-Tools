const {chromium}=require('playwright');const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setContent('<div id="status-msg"></div>');
 for(const file of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css'])await page.addStyleTag({path:path.resolve(file)});
 for(const file of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/linked_workspace_preload.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(file)});
 await page.evaluate(async()=>{
  window.calls=[];window.cards=['EMS','CONTENTS','RECON'].map(division=>({division,card_id:division,pinned:true}));
  window.payload=division=>({ok:true,client:'Preload fixture',card_id:division,selected_division:division,audit:{found:true},crm:{job_log:[]},division_trello_cards:cards,comments:[{id:division,text:division+' saved',source:'trello'}]});
  window.pywebview={api:{job_card_workspace_fast:async(c,id,d)=>{calls.push(['fast',id]);return payload(d);},job_card_workspace:async(c,id,d)=>{calls.push(['full',id]);return payload(d);},refresh_job_comments:async id=>{calls.push(['comments',id]);return {ok:true,comments:[{id,text:id+' preloaded',source:'trello'}]};}}};
  await onAuditCard('Preload fixture','EMS','','EMS');
 });
 await page.waitForFunction(()=>calls.some(c=>c[0]==='comments'&&c[1]==='RECON'));
 assert.equal(await page.locator('[data-division-data="EMS"]').getAttribute('aria-selected'),'true');
 assert.deepEqual(await page.evaluate(()=>calls.filter(c=>c[0]==='full')),[['full','EMS']]);
 assert.ok((await page.locator('[data-comment-stream]').innerText()).includes('EMS saved'));
 await page.locator('[data-comment-input]').fill('Keep my EMS draft');
 page.once('dialog',d=>d.dismiss());
 await page.locator('[data-division-data="CONTENTS"]').click();
 assert.ok((await page.locator('[data-comment-stream]').innerText()).includes('EMS saved'));
 assert.equal(await page.locator('[data-comment-input]').inputValue(),'Keep my EMS draft');
 assert.equal(await page.evaluate(()=>calls.filter(c=>c[0]==='comments'&&c[1]==='CONTENTS').length),1);
 await page.locator('[data-comment-input]').fill('');
 await page.locator('[data-division-data="CONTENTS"]').click();
 await page.waitForFunction(()=>calls.some(c=>c[0]==='full'&&c[1]==='CONTENTS'));
 assert.equal(await page.evaluate(()=>calls.filter(c=>c[0]==='fast'&&c[1]==='CONTENTS').length),1);
 assert.equal(await page.locator('[data-division-data="CONTENTS"]').getAttribute('aria-selected'),'true');
 // Re-entering a visited division must read fresh data, not resurrect a cached Job Log.
 await page.locator('[data-division-data="EMS"]').click();
 await page.waitForFunction(()=>calls.filter(c=>c[0]==='fast'&&c[1]==='EMS').length===2);
 // Isolated scheduler checks: skip ambiguous/unpinned/shared IDs and stop after close.
 const result=await page.evaluate(async()=>{
  let active=true;const requests=[];let release;
  const session=LinkedWorkspacePreload.create({job_card_workspace_fast:(c,id)=>{requests.push(id);return new Promise(resolve=>release=()=>resolve({ok:true,card_id:id}));},refresh_job_comments:async id=>{requests.push('comments:'+id);return {ok:true,comments:[]};}},()=>active);
  session.schedule({client:'test',selected_division:'EMS',division_trello_cards:[{division:'CONTENTS',card_id:'c',pinned:true},{division:'RECON',card_id:'r',pinned:false}]});
  await new Promise(resolve=>setTimeout(resolve,20));active=false;release();await new Promise(resolve=>setTimeout(resolve,20));
  const denied=[];const blocked=LinkedWorkspacePreload.create({job_card_workspace_fast:async(c,id)=>{denied.push(id);return {ok:true};}},()=>true);
  blocked.schedule({selected_division:'EMS',division_trello_cards:[{division:'CONTENTS',card_id:'same',pinned:true},{division:'RECON',card_id:'same',pinned:true}]});
  await new Promise(resolve=>setTimeout(resolve,20));return {requests,denied};
 });
 assert.deepEqual(result,{requests:['c'],denied:[]});assert.deepEqual(errors,[]);
 console.log('PASS: linked divisions preload sequentially, EMS/drafts stay selected, switches reuse one-shot reads, visited logs reload, no speculative full audits, invalid links/closed workspace skipped.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
