const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const p=await browser.newPage();await p.setContent('<body></body>');
 await p.evaluate(()=>{
  const card={id:'card1',name:'Test job',desc:''},comment={id:'c1',text:'Field inspection complete',author:'Field Lead',date:'2026-04-08T20:14:00Z'};
  let links={version:null,items:{}};
  window.pywebview={api:{
   logs_queue:async()=>({ok:true,cards:[card],drafts:{},operations:[]}),
   logs_inspect:async()=>({ok:true,evidence:{card,revision:'rev',comments:[comment],checklists:[]},links,suggestions:{},lanes:[]}),
   logs_save:async(card,revision,fields,expected,linkVersion)=>{window.saved={fields,linkVersion};return {ok:true,draft:{fields,version:'draft1'}};},
   audit_comment_links:async(card,command)=>{if(command)links={version:'link1',items:{field_note_posted_at:{value:command.value,comment_id:'c1',comment}}};return {ok:true,links,targets:{field_note_posted_at:['Field inspection note','timestamp']}};}
  }};
 });
 for(const file of ['web_shared/theme.css','analytics_web_assets/app.css','analytics_web_assets/logs_review_workspace.css','web_shared/audit_comment_links.css'])await p.addStyleTag({path:path.resolve(file)});
 for(const file of ['analytics_web_assets/audit_field_controls.js','web_shared/audit_comment_links.js','analytics_web_assets/logs_review_workspace.js','analytics_web_assets/logs_audit.js'])await p.addScriptTag({path:path.resolve(file)});
 await p.evaluate(()=>LogsAuditUI.open({start:'2026-04-06',end:'2026-04-12'}));
 await p.locator('[name=ems_estimator]').fill('Keep my draft');
 assert.equal(await p.getByLabel('Choose timing source comment').count(),0);
 await p.locator('.logs-review-comment').click({button:'right'});
 await p.getByRole('menuitem',{name:'Field inspection note'}).click();
 await p.getByRole('button',{name:'Save link',exact:true}).click();
 await p.waitForFunction(()=>document.querySelector('[name=field_note_posted_at]').value==='2026-04-08T20:14:00Z');
 assert.equal(await p.locator('[name=ems_estimator]').inputValue(),'Keep my draft');
 await p.locator('[data-save]').click();await p.waitForFunction(()=>window.saved);
 assert.equal(await p.evaluate(()=>saved.linkVersion),'link1');
 assert.equal(await p.evaluate(()=>saved.fields.field_note_posted_at),'2026-04-08T20:14:00Z');
 assert.equal(await p.locator('[name=initial_note]').inputValue(),'','no invented coordinator time');
 console.log('PASS: real audit integration, right-click linking, form refresh, preserved draft, shared link revision');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
