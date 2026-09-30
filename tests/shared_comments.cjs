const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{for(const host of ['daily-run','snapshot']){
  const page=await browser.newPage({viewport:{width:1100,height:850}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('http://comments.test/**',r=>r.fulfill({contentType:'text/html',body:`<body class="${host==='snapshot'?'snapshot-panel':''}"><main>Job workspace</main></body>`}));
  await page.goto('http://comments.test/');
  await page.evaluate(()=>document.documentElement.dataset.theme='dark');
  for(const file of ['web_shared/theme.css','pipeline_web_assets/comment_editor.css','pipeline_web_assets/comment_reactions.css','web_shared/comments_composer.css','web_shared/comment_display.css'])await page.addStyleTag({path:path.resolve(file)});
  await page.evaluate(()=>{
   window.calls=[];window.failContents=false;window.slow=false;
   window.pywebview={api:{
    comment_destinations:async()=>({ok:true,cards:[{division:'EMS',card_id:'a'.repeat(24)},{division:'CONTENTS',card_id:'c'.repeat(24)}]}),
    drawer_comments:async(...args)=>{calls.push(['read',...args]);if(slow)await new Promise(r=>setTimeout(r,400));return {ok:true,comments:[{id:'b'.repeat(24),author:'Test user',initials:'TU',text:'**Bold update** and *italic* [safe](https://example.com)\n\n@sam_test please review the photos.',kind:'comment'}]};},
    drawer_post:async(...args)=>{calls.push(['post',...args]);return {ok:!(failContents&&args[1]==='c'.repeat(24))};},
    job_comment_members:async id=>{calls.push(['members',id]);return {ok:true,members:[{username:'sam_test',name:'Sam Test'}]};},
    job_comment_reactions:async(...args)=>{calls.push(['react',...args]);return {ok:true,account:'Tester',choices:[{name:'Thumbs up',emoji:'👍',code:'1F44D',category:'People'}],reactions:[]};},
    invalidate_comments_cache:async()=>({ok:true})
   }};
   window.row={client:'Test job',trello_card_id:'a'.repeat(24),division:'EMS'};
  });
  for(const file of ['web_shared/vendor/markdown-it/markdown-it.min.js','pipeline_web_assets/comment_markdown.js','web_shared/vendor/comment-editor.js','pipeline_web_assets/comment_reactions.js','web_shared/comments_composer.js','web_shared/audit_detail.js'])await page.addScriptTag({path:path.resolve(file)});
  await page.evaluate(()=>AuditDetail.openCommentsDrawer(row,{}));
  await page.locator('.cmt-txt strong').waitFor();assert.equal(await page.locator('.cmt-txt strong').innerText(),'Bold update');
  assert.equal(await page.locator('.cmt-txt .comment-mention').innerText(),'@sam_test');
  const editor=page.locator('.cmt-compose .comment-editor-content');
  await editor.fill('@sam');await page.getByRole('option').filter({hasText:'Sam Test'}).click();
  assert.match(await editor.innerText(),/@sam_test/);
  await page.locator('[data-comment-format=bold]').first().click();await page.keyboard.type(' formatted');
  assert.match(await page.locator('#cmt-new').inputValue(),/\*\*/);
  await page.locator('[data-reactions-open]').click();await page.locator('[data-emoji-code="1F44D"]').click();
  assert((await page.evaluate(()=>calls)).some(c=>c[0]==='react'&&c[1]==='a'.repeat(24)&&c[3]==='1F44D'));
  // Per-card drafts survive division changes; read identity follows the pill.
  const draft=await page.locator('#cmt-new').inputValue();
  await page.locator('.drawer-divisions button').filter({hasText:'Contents'}).click();
  await page.waitForFunction(()=>document.querySelector('#cmt-drawer')._row.trello_card_id==='c'.repeat(24));
  assert.equal(await page.locator('#cmt-new').inputValue(),'');
  await page.locator('.drawer-divisions button').filter({hasText:'EMS'}).click();
  await page.waitForFunction(()=>document.querySelector('#cmt-new').value.includes('@sam_test'));
  assert.equal(await page.locator('#cmt-new').inputValue(),draft);
  // Multi-post preserves partial failures and never reselects successful cards.
  await page.locator('[data-comment-destination=CONTENTS]').click();
  await page.evaluate(()=>failContents=true);await page.locator('#cmt-post').click();
  await page.waitForFunction(()=>document.querySelector('.drawer-comment-status').textContent.includes('not confirmed'));
  assert.equal(await page.locator('[data-comment-destination=EMS]').getAttribute('aria-pressed'),'false');
  assert.equal(await page.locator('#cmt-new').inputValue(),draft);
  await page.evaluate(()=>{failContents=false;slow=true;});await page.locator('#cmt-post').click();
  await page.waitForFunction(()=>document.querySelector('#cmt-new').value==='');
  // Refresh keeps existing content instead of inserting a loading text row.
  await page.locator('#cmt-refresh').click();assert.equal(await page.locator('.cmt-txt strong').count(),1);
  await page.waitForTimeout(500);
  assert.deepEqual(errors,[]);
  await page.screenshot({path:path.join(process.env.TEMP,`oneloss-${host}-comments.png`)});
  await page.setViewportSize({width:440,height:760});
  assert(await page.locator('#cmt-post').evaluate(el=>{const r=el.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.bottom<=innerHeight;}));
  await page.screenshot({path:path.join(process.env.TEMP,`oneloss-${host}-comments-narrow.png`)});
  await page.close();console.log('PASS: '+host+' shared formatting, mentions, reactions, exact-card reads, drafts, multi-post and stable refresh');
 }}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
