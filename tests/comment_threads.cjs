const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require('playwright');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('http://localhost:8765/**',route=>route.fulfill({body:'<html></html>',contentType:'text/html'}));
 await page.goto('http://localhost:8765/');
 await page.setContent('<div id="status-msg"></div>');
 for(const file of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css','pipeline_web_assets/comment_editor.css','pipeline_web_assets/comment_threads.css']) await page.addStyleTag({path:path.resolve(file)});
 for(const file of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/job_drafts.js','web_shared/vendor/markdown-it/markdown-it.min.js','pipeline_web_assets/comment_markdown.js','web_shared/vendor/comment-editor.js','pipeline_web_assets/comment_threads.js','pipeline_web_assets/app.js']) await page.addScriptTag({path:path.resolve(file)});
 await page.evaluate(()=>{
  document.documentElement.dataset.theme='dark'; window.rows=[];window.replyCalls=[];window.ordinary=0;window.fail=true;window.draft=null;
  window.pywebview={api:{
   comment_thread_state:async()=>({ok:true,comments:rows}),
   job_draft:async(c,d,k,i,change)=>{if(change)draft=change.payload;return {ok:true,payload:draft,scope:'test',version:1};},
   pin_job_comment:async(card,id,pinned)=>{const r={card_id:card,id,root_id:id,body:'Original message',actor:'Sam',pinned,native:false,provider_id:id,created_at:'2026-10-01T12:00:00Z'};rows=[r];return {ok:true,comment:r};},
   post_job_comment:async()=>{ordinary++;return {ok:false};},
   reply_job_comment:async(card,parent,text,op)=>{replyCalls.push({card,parent,text,op});if(fail)return {ok:false,error:'Offline test'};const r={card_id:card,id:'oneloss:'+op,root_id:rows.find(r=>r.id===parent)?.root_id||parent,parent_id:parent,actor:'Nathan',native:true,body:text,created_at:rows.some(r=>r.native)?'2026-10-06T13:00:00Z':'2026-10-06T12:00:00Z',delivery:'sent',provider_id:rows.some(r=>r.native)?'echo-'+op:'echo',operation_id:op};rows.push(r);return {ok:true,comment:r,parent:rows[0]};}
  }};
  window.payload={ok:true,client:'Thread check',card_id:'card',selected_division:'EMS',audit:{found:true},crm:{},comments:[{id:'parent',external_id:'parent',source:'trello',actor:'Sam',text:'Original message',at:'2026-10-01T12:00:00Z'}]};
  openAuditModal(payload);
 });
 await page.locator('[data-pin-comment]').click();
 await page.waitForFunction(()=>document.querySelector('[data-comment-pinned="true"]'));
 await page.locator('[data-comment-pinned-filter]').click();
 assert.equal(await page.locator('[data-comment-stream] article:visible').count(),1);
 await page.locator('[data-comment-all]').click();
 await page.locator('[data-reply-comment]').click();
 await page.locator('[data-reply-comment]').click();
 assert.match(await page.locator('.comment-reply-banner').innerText(),/Replying to Sam/);
 await page.locator('[contenteditable=true]').fill('A linked reply');
 await page.locator('[data-post-comment]').click();
 assert.equal(await page.locator('[data-comment-state]').innerText(),'Offline test');
 assert.equal(await page.locator('[data-comment-input]').inputValue(),'A linked reply');
 await page.evaluate(()=>fail=false);
 await page.locator('[data-post-comment]').click();
 await page.waitForFunction(()=>document.querySelectorAll('[data-comment-stream] article').length===2);
 const calls=await page.evaluate(()=>replyCalls);
 assert.equal(calls[0].op,calls[1].op);assert.equal(await page.evaluate(()=>ordinary),0);
 assert.equal(await page.locator('[data-comment-input]').inputValue(),'');
 assert.equal(await page.locator('.comment-reply-banner').isVisible(),false);
 assert.equal(await page.locator('[data-comment-destination="EMS"]').isEnabled(),true);
 // Pins never move the original above the newer reply.
 assert.match(await page.locator('[data-comment-stream] article').first().innerText(),/A linked reply/);
 await page.locator('[contenteditable=true]').fill('Unsent regular draft');
 await page.locator('[data-comment-stream] [data-open-thread]').first().click();
 assert.equal(await page.locator('.comment-thread-messages article').count(),1);
 assert.match(await page.locator('.comment-thread-original').innerText(),/Original message/);
 assert.equal(await page.locator('dialog.comment-thread-panel').evaluate(el=>el.open),true);
 await page.locator('[data-thread-input]').fill('Separate thread draft');
 assert.equal(await page.locator('[data-comment-input]').inputValue(),'Unsent regular draft');
 await page.keyboard.press('Escape');
 assert.equal(await page.locator('.audit-card').isVisible(),true);
 await page.locator('[data-comment-stream] [data-open-thread]').first().click();
 assert.equal(await page.locator('[data-thread-input]').inputValue(),'Separate thread draft');
 await page.evaluate(()=>fail=true);
 await page.getByRole('button',{name:'Send reply',exact:true}).click();
 assert.equal(await page.locator('[data-thread-status]').innerText(),'Offline test');
 assert.equal(await page.locator('[data-thread-input]').inputValue(),'Separate thread draft');
 await page.evaluate(()=>fail=false);
 await page.getByRole('button',{name:'Send reply',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-thread-input]').value==='');
 const threadCalls=await page.evaluate(()=>replyCalls);
 assert.equal(threadCalls.at(-1).op,threadCalls.at(-2).op);
 assert.equal(threadCalls.at(-1).parent,'parent');
 assert.equal(await page.locator('[data-comment-input]').inputValue(),'Unsent regular draft');
 assert.match(await page.locator('.comment-thread-messages article').first().innerText(),/Separate thread draft/);
 await page.setViewportSize({width:600,height:720});
 const bounds=await page.locator('.comment-thread-panel').boundingBox();
 assert.ok(bounds.x>=0 && bounds.x+bounds.width<=600 && bounds.y+bounds.height<=720);
 assert.ok((await page.locator('.comment-thread-messages').boundingBox()).height>100,'Replies retain useful space on narrow screens');
 await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-floating-thread.png')});
 await page.getByRole('button',{name:'Close thread',exact:true}).click();
 await page.setViewportSize({width:1440,height:1000});
 const streamBounds=await page.locator('[data-comment-stream]').boundingBox();
 const streamScroll=await page.locator('[data-comment-stream]').evaluate(el=>el.scrollTop);
 await page.locator('[data-comment-stream] [data-open-thread]').first().click();
 assert.deepEqual(await page.locator('[data-comment-stream]').boundingBox(),streamBounds,'Opening thread must not reflow feed');
 await page.locator('[data-thread-input]').fill('Keep this thread draft');
 await page.locator('.comment-thread-panel').evaluate(el=>Promise.all(el.getAnimations().map(a=>a.finished)));
 await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-floating-thread-desktop.png')});
 await page.mouse.click(20,500);
 assert.equal(await page.locator('dialog.comment-thread-panel').evaluate(el=>el.open),false);
 assert.equal(await page.locator('.audit-card').isVisible(),true);
 assert.equal(await page.locator('[data-comment-stream]').evaluate(el=>el.scrollTop),streamScroll);
 await page.locator('[data-comment-stream] [data-open-thread]').first().click();
 assert.equal(await page.locator('[data-thread-input]').inputValue(),'Keep this thread draft');
 await page.emulateMedia({reducedMotion:'reduce'});
 assert.equal(await page.locator('.comment-thread-panel').evaluate(el=>getComputedStyle(el).animationName),'none');
 await page.getByRole('button',{name:'Close thread',exact:true}).click();
 await page.locator('[data-comment-pinned-filter]').click();
 assert.equal(await page.locator('[data-comment-stream] article:visible').count(),1);
 await page.locator('[data-comment-all]').click();
 // Saved metadata keeps its own projection after an ordinary provider refresh.
 await page.evaluate(()=>state.openWorkspace.conversation.applyInitialRefresh('card',[...payload.comments,{id:'echo',external_id:'echo',actor:'Nathan',text:'Echo',at:'2026-10-06T12:00:00Z'}],true));
 assert.equal(await page.locator('[data-comment-stream] article').count(),3);
 await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-comment-threads.png')});
 assert.deepEqual(errors,[]);
 console.log('PASS: shared pins, unchanged order, reply retry identity, no ordinary fallback, thread view, draft preservation, echo deduplication.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
