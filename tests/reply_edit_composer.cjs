const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require('playwright');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(5000);
 await page.emulateMedia({reducedMotion:'reduce'});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setContent('<div id="status-msg"></div>');
 for(const f of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/comment_editor.css','pipeline_web_assets/comment_threads.css'])await page.addStyleTag({path:path.resolve(f)});
 for(const f of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','web_shared/vendor/markdown-it/markdown-it.min.js','pipeline_web_assets/comment_markdown.js','web_shared/vendor/comment-editor.js','pipeline_web_assets/comment_threads.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(f)});
 await page.evaluate(()=>{
  document.documentElement.dataset.theme='dark';window.edits=[];window.fail=true;
  window.rows=[{id:'parent',root_id:'parent',card_id:'card',body:'Original',actor:'Sam',native:false,created_at:'2026-10-01'},
   {id:'reply',root_id:'parent',parent_id:'parent',card_id:'card',body:'Reply **bold**',actor:'Me',native:true,can_edit:true,provider_id:'provider',delivery:'sent',created_at:'2026-10-02'}];
  window.pywebview={api:{comment_thread_state:async()=>({ok:true,comments:rows}),
   edit_job_reply:async(card,id,text,expected)=>{edits.push({card,id,text,expected});if(fail)return {ok:false,error:'Conflict — draft kept'};rows=rows.map(r=>r.id===id?{...r,body:text}:r);return {ok:true,comment:rows[1],text};},
   post_job_comment:async()=>{throw Error('Must not post');},edit_job_comment:async()=>{throw Error('Wrong edit endpoint');}}};
  openAuditModal({ok:true,client:'Reply test',card_id:'card',selected_division:'EMS',audit:{found:true},crm:{},comments:[]});
 });
 const editor=page.locator('.comment-editor-content');
 await page.locator('[data-comment-stream] [data-comment-id="reply"] [data-comment-edit]').waitFor();
 assert.equal(await page.locator('[data-comment-id="reply"] [data-comment-delete]').count(),0);
 await editor.fill('Keep unsent draft');
 await page.locator('[data-comment-id="reply"] [data-open-thread]').first().click();
 await page.locator('.comment-thread-panel [data-comment-edit]').click();
 assert.equal(await page.locator('.comment-thread-panel').evaluate(el=>el.open),false);
 assert.equal(await editor.locator('strong').count(),1);
 await editor.fill('Updated @card');
 await page.getByRole('button',{name:'Save changes',exact:true}).click();
 await page.getByText('Conflict — draft kept',{exact:true}).waitFor();
 assert.equal(await editor.innerText(),'Updated @card');
 await page.evaluate(()=>fail=false);
 await page.getByRole('button',{name:'Save changes',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-comment-input]').value==='Keep unsent draft');
 assert.deepEqual(await page.evaluate(()=>edits[1]),{card:'card',id:'reply',text:'Updated @card',expected:'Reply **bold**'});
 assert.match(await page.locator('[data-comment-stream] [data-comment-id="reply"]').innerText(),/Updated @card/);
 await page.locator('[data-comment-stream] [data-comment-id="reply"] [data-open-thread]').first().click();
 assert.match(await page.locator('.comment-thread-messages').innerText(),/Updated @card/);
 await page.screenshot({path:path.join(process.env.TEMP,'oneloss-reply-edit.png')});
 assert.deepEqual(errors,[]);
 console.log('PASS reply popup edit, shared composer, ownership UI, draft retention, exact reply identity and refreshed thread');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
