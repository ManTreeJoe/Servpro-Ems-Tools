const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(4000);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.setContent('<div id="status-msg"></div>');
  for(const file of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css','pipeline_web_assets/comment_editor.css'])await page.addStyleTag({path:path.resolve(file)});
  for(const file of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','web_shared/vendor/markdown-it/markdown-it.min.js','pipeline_web_assets/comment_markdown.js','web_shared/vendor/comment-editor.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(file)});
  await page.evaluate(()=>{
   document.documentElement.dataset.theme='dark';window.memberCalls=[];window.posts=[];
   window.pywebview={api:{job_comment_members:async card=>{memberCalls.push(card);return {ok:true,members:card==='ems-card'?[{id:'1',name:'Sam Example',username:'sam_example'},{id:'2',name:'Other Person',username:'otherperson'}]:[{id:'3',name:'Contents Person',username:'contentsuser'}]};},post_job_comment:async(...args)=>{posts.push(args);return {ok:true,comment:{id:'posted',actor:'Me',text:args[2]}};}}};
   openAuditModal({ok:true,client:'Mention test',card_id:'ems-card',selected_division:'EMS',audit:{found:true},crm:{},comments:[],division_trello_cards:[{division:'CONTENTS',card_id:'contents-card',pinned:true}]});
  });
  const editor=page.locator('.comment-editor-content');
  await editor.fill('@sa');await editor.press('End');
  await page.getByRole('option',{name:/Sam Example/}).waitFor();
  assert.deepEqual(await page.evaluate(()=>memberCalls),['ems-card']);
  await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-comment-mentions.png')});
  await editor.press('Enter');
  assert.match(await editor.innerText(),/@sam_example/);
  await page.locator('[data-post-comment]').click();
  assert.equal(await page.evaluate(()=>posts[0][2]),'@sam_example');
  await editor.fill('mail@example.com');await editor.press('End');
  assert.equal(await page.getByRole('listbox',{name:'Mention suggestions'}).isVisible(),false);
  await editor.fill('@');await editor.press('End');
  await page.getByRole('option',{name:/Sam Example/}).waitFor();
  await editor.press('Escape');
  assert.equal(await page.locator('.audit-overlay').count(),1);
  assert.equal(await page.getByRole('listbox',{name:'Mention suggestions'}).isVisible(),false);
  await page.locator('[data-comment-destination="EMS"]').click();
  await page.locator('[data-comment-destination="CONTENTS"]').click();
  await editor.fill('@co');await editor.press('End');
  await page.getByRole('option',{name:/Contents Person/}).click();
  assert.match(await editor.innerText(),/@contentsuser/);
  assert.deepEqual(await page.evaluate(()=>memberCalls),['ems-card','contents-card']);
  await page.evaluate(()=>{
   window.realTargets=document.querySelector('[data-comment-input]')._mentionTargets;
   document.querySelector('[data-comment-input]')._mentionTargets=()=>[{cardId:'slow-card',division:'RECON'}];
   window.memberApi=pywebview.api.job_comment_members;
   pywebview.api.job_comment_members=card=>card==='slow-card'?new Promise(resolve=>window.slowMembers=resolve):memberApi(card);
  });
  await editor.fill('@');await editor.press('End');await page.waitForFunction(()=>typeof slowMembers==='function');
  assert.match(await page.locator('.comment-mention-status').innerText(),/Loading/);
  await page.evaluate(()=>{document.querySelector('[data-comment-input]')._mentionTargets=realTargets;});
  await editor.fill('@co');await editor.press('End');
  await page.getByRole('option',{name:/Contents Person/}).waitFor();
  await page.evaluate(()=>slowMembers({ok:true,members:[{name:'Wrong old board',username:'wrong'}]}));
  assert.equal(await page.getByRole('option',{name:/Wrong old board/}).count(),0);
  await editor.press('Escape');
  await page.evaluate(()=>{
   document.querySelector('[data-comment-input]')._mentionTargets=()=>[{cardId:'failure-card',division:'EMS'}];
   window.failMembers=true;pywebview.api.job_comment_members=async()=>failMembers?{ok:false,error:'offline'}:{ok:true,members:[{name:'Recovered Member',username:'recovered'}]};
  });
  await editor.fill('@re');await editor.press('End');
  await page.getByRole('button',{name:'Retry',exact:true}).waitFor();
  assert.equal(await page.getByRole('listbox',{name:'Mention suggestions'}).getByRole('option').count(),0);
  await page.evaluate(()=>{failMembers=false;});await page.getByRole('button',{name:'Retry',exact:true}).click();
  await page.getByRole('option',{name:/Recovered Member/}).waitFor();
  await editor.press('Tab');assert.match(await editor.innerText(),/@recovered/);
  assert.deepEqual(errors,[]);
  console.log('PASS: @ suggestions, exact usernames in Markdown posting, keyboard/mouse selection, email exclusion, Escape, destination isolation, cached requests.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
