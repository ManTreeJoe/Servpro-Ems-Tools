const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage();
 await page.setContent('<div id="root"><div class="activity-head"></div><label class="comment-search"></label><span data-comment-count></span><div data-comment-stream></div><div class="comment-compose"><div class="comment-send-row"></div><textarea>Draft</textarea></div></div>');
 await page.addScriptTag({path:path.resolve('pipeline_web_assets/job_conversation.js')});
 await page.evaluate(()=>{
  window.remoteCalls=0;window.savedCalls=0;
  window.options={cardId:'one',division:'EMS',comments:[],initialComplete:false,followWorkspace:true,
   render:row=>`<p>${row.text}</p>`,fetchSaved:async()=>{savedCalls++;return {ok:true,cached:true,comments:[{id:'saved',text:'Saved comment'}]};},fetch:async()=>{remoteCalls++;return {ok:true,comments:[]};}};
  window.conversation=JobConversation.mount(document.querySelector('#root'),options);
 });
 await page.waitForFunction(()=>document.querySelector('[data-comment-stream]').textContent.includes('Saved comment'),{},{timeout:1500});
 assert.equal(await page.evaluate(()=>remoteCalls),0);
 assert.equal(await page.locator('textarea').inputValue(),'Draft');
 await page.evaluate(()=>conversation.applyInitialRefresh('one',[{id:'live',text:'Live comment'}],true));
 assert.equal(await page.locator('[data-comment-stream]').innerText(),'Live comment');
 // A cache response arriving after a successful empty remote snapshot must not resurrect comments.
 await page.evaluate(()=>{
  document.querySelector('#root').remove();
  const root=document.createElement('div');root.id='root';root.innerHTML='<div class="activity-head"></div><label class="comment-search"></label><div data-comment-stream></div><div class="comment-compose"></div>';document.body.append(root);
  window.conversation=JobConversation.mount(root,{...options,fetchSaved:()=>new Promise(resolve=>window.finishSaved=resolve)});
 });
 await page.waitForFunction(()=>!!window.finishSaved);
 await page.evaluate(()=>{conversation.applyInitialRefresh('one',[],true);finishSaved({ok:true,cached:true,comments:[{id:'old',text:'Deleted comment'}]});});
 await page.evaluate(()=>new Promise(resolve=>setTimeout(resolve,0)));
 assert(!await page.locator('[data-comment-stream]').innerText().then(t=>t.includes('Deleted comment')));
 console.log('PASS: initial saved comments load without remote duplication; live updates win and drafts survive.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
