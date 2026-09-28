const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.setContent('<div id="status-msg"></div>');
  for(const file of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css','pipeline_web_assets/comment_editor.css']) await page.addStyleTag({path:path.resolve(file)});
  for(const file of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/job_drafts.js','web_shared/vendor/markdown-it/markdown-it.min.js','pipeline_web_assets/comment_markdown.js','web_shared/vendor/comment-editor.js','pipeline_web_assets/app.js']) await page.addScriptTag({path:path.resolve(file)});
  await page.evaluate(()=>{
   document.documentElement.dataset.theme='dark';window.draft=null;window.version=0;window.posts=[];window.failPost=true;
   window.pywebview={api:{
    job_draft:async(card,division,kind,id,change)=>{if(change){draft=change.payload;version++;}return {ok:true,payload:draft,scope:'test',version};},
    post_job_comment:async(...args)=>{posts.push(args);return failPost?{ok:false,error:'Test offline failure'}:{ok:true,comment:{id:'posted',actor:'Me',text:args[2]}};},
   }};
   window.payload={ok:true,client:'Editor check',card_id:'ems-card',selected_division:'EMS',audit:{found:true},crm:{},comments:[],division_trello_cards:[{division:'CONTENTS',card_id:'contents-card',pinned:true}]};
   openAuditModal(payload);
  });
  const editor=page.locator('.comment-editor-content');
  const source=page.locator('[data-comment-input]');
  await editor.fill('Kitchen complete');await editor.press('Control+a');
  await page.locator('[data-comment-format="bold"]').click();
  assert.equal(await editor.locator('strong').innerText(),'Kitchen complete');
  assert.equal(await source.inputValue(),'**Kitchen complete**');
  await editor.press('Control+z');assert.equal(await editor.locator('strong').count(),0);
  await editor.press('Control+Shift+z');assert.equal(await editor.locator('strong').count(),1);
  await editor.press('Control+i');assert.equal(await editor.locator('em').count(),1);
  await page.waitForFunction(()=>draft?.text.includes('Kitchen complete'));
  const saved=await source.inputValue();
  await page.waitForFunction(value=>draft?.text===value,saved);
  await page.locator('[data-post-comment]').click();
  assert.equal(await source.inputValue(),saved);
  assert.equal(await page.locator('[data-comment-state]').innerText(),'Test offline failure');
  // A new modal recovers the same Markdown into rich content, without posting.
  await page.evaluate(()=>{document.querySelector('[data-comment-input]')._richEditor.destroy();document.querySelector('.audit-overlay').remove();openAuditModal(payload);});
  await page.getByRole('button',{name:'Restore draft',exact:true}).click();
  assert.equal(await editor.locator('strong').innerText(),'Kitchen complete');
  assert.equal(await source.inputValue(),saved);
  assert.equal(await page.evaluate(()=>posts.length),1);
  await editor.press('Control+a');await page.locator('[data-comment-format="link"]').click();
  await page.getByRole('textbox',{name:'Link address',exact:true}).fill('javascript:alert(1)');
  await page.locator('[data-apply-link]').click();assert.equal(await editor.locator('a').count(),0);
  await page.getByRole('textbox',{name:'Link address',exact:true}).fill('https://example.com/report');
  await page.locator('[data-apply-link]').click();assert.equal(await editor.locator('a').getAttribute('href'),'https://example.com/report');
  await page.evaluate(()=>{document.querySelector('[data-comment-input]').value='- Kitchen\n- Hall';});
  assert.equal(await editor.locator('li').count(),2);
  await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-rich-comment.png')});
  for(const width of [1280,1024]){
   await page.setViewportSize({width,height:900});
   assert.equal(await page.locator('.comment-compose').evaluate(el=>el.scrollWidth<=el.clientWidth+1),true);
   assert.equal(await page.locator('[data-post-comment]').isVisible(),true);
  }
  await page.evaluate(()=>{failPost=false;});await page.locator('[data-post-comment]').click();
  await page.waitForFunction(()=>document.querySelector('[data-comment-input]').value==='');
  assert.equal((await editor.innerText()).trim(),'');
  await page.waitForFunction(()=>draft===null);
  assert.deepEqual(errors,[]);
  console.log('PASS: rich formatting, undo/redo, Markdown transport, failed-send retention, draft restore, links, lists, clearing, responsive layout.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
