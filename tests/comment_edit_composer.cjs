const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require('playwright');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.setContent('<div id="status-msg"></div>');
 for(const f of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/comment_editor.css'])await page.addStyleTag({path:path.resolve(f)});
 for(const f of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','web_shared/vendor/markdown-it/markdown-it.min.js','pipeline_web_assets/comment_markdown.js','web_shared/vendor/comment-editor.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(f)});
 await page.evaluate(()=>{
  window.edits=[];window.groups=[];window.fail=true;
  window.pywebview={api:{job_comment_members:async()=>({ok:true,members:[]}),oneloss_comment_members:async()=>({ok:true,members:[]}),
   job_comment_card_members:async card=>{groups.push(card);return {ok:true,members:[{username:'sam_example'},{username:'laura'}]};},
   edit_job_comment:async(...args)=>{edits.push(args);return fail?{ok:false,error:'Offline — retry'}:{ok:true,text:args[3]};},
   post_job_comment:async()=>{throw Error('Must edit, never post');}}};
  openAuditModal({ok:true,client:'Edit test',card_id:'ems-card',selected_division:'EMS',audit:{found:true},crm:{},
   comments:[{id:'comment1',text:'Original **bold**',actor:'Me',can_manage:true,source:'trello'}]});
 });
 const editor=page.locator('.comment-editor-content');
 await editor.fill('Keep this unsent draft');
 await page.locator('[data-comment-edit]').click();
 await page.getByRole('button',{name:'Save changes',exact:true}).waitFor();
 assert.match(await editor.innerText(),/Original bold/);
 assert.equal(await editor.locator('strong').count(),1);
 await editor.fill('@mem');await editor.press('End');
 await page.getByRole('option',{name:/Members of this card/}).click();
 assert.match(await editor.innerText(),/@sam_example @laura/);
 assert.deepEqual(await page.evaluate(()=>groups),['ems-card']);
 await page.getByRole('button',{name:'Save changes',exact:true}).click();
 await page.getByText('Offline — retry',{exact:true}).waitFor();
 assert.match(await editor.innerText(),/@sam_example/);
 await page.evaluate(()=>fail=false);
 await page.screenshot({path:path.join(process.env.TEMP,'oneloss-comment-edit-composer.png')});
 await page.getByRole('button',{name:'Save changes',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-comment-input]').value==='Keep this unsent draft');
 assert.equal(await page.evaluate(()=>edits[1][1]),'comment1');
 assert.equal(await page.evaluate(()=>edits[1][2]),'trello');
 assert.equal(await page.locator('[data-comment-id="comment1"]').count(),1);
 await page.locator('[data-comment-edit]').click();
 await editor.fill('Discard this edit');
 await page.getByRole('button',{name:'Cancel edit'}).click();
 assert.equal(await editor.innerText(),'Keep this unsent draft');
 console.log('PASS rich editing, assigned group expansion, original ID, failed-save retention, save/cancel draft restoration');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
