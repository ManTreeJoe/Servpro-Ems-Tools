const {chromium}=require('playwright'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:440,height:650}});
 await page.setContent('<main id="stream" style="padding:16px"></main>');
 for(const f of ['web_shared/theme.css','pipeline_web_assets/app.css','web_shared/comment_display.css'])await page.addStyleTag({path:path.resolve(f)});
 for(const f of ['web_shared/vendor/markdown-it/markdown-it.min.js','pipeline_web_assets/comment_markdown.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(f)});
 const result=await page.evaluate(()=>{
  document.documentElement.dataset.theme='dark';
  const text='@sam_test **please review**\n\nEmail sam@example.com, [@link](https://example.com/@url), `@code`\n\n```\n@block\n```\n\n<script>alert(1)</script>';
  const host=document.createElement('div');host.innerHTML=CommentMarkdown.display(text);
  document.querySelector('#stream').innerHTML=['Nathan Bupte','Laura Barajas','Fernando Estrada'].map((actor,i)=>renderJobComment({actor,text:i?'@nathan_bupte can you review the uploaded photos?':text,source:'trello'})).join('');
  return {chips:[...host.querySelectorAll('.comment-mention')].map(x=>x.textContent),scripts:host.querySelectorAll('script').length,plain:CommentMarkdown.render(text),raw:document.querySelector('[data-comment-raw]').dataset.commentRaw,colors:['Nathan Bupte','nathan bupte','Laura Barajas'].map(CommentMarkdown.avatarColor),initials:CommentMarkdown.initials('Nathan Bupte'),text};
 });
 assert.deepEqual(result.chips,['@sam_test']);assert.equal(result.scripts,0);assert(!result.plain.includes('comment-mention'));assert.equal(result.raw,result.text);assert.equal(result.colors[0],result.colors[1]);assert.notEqual(result.colors[0],result.colors[2]);assert.equal(result.initials,'NB');
 await page.screenshot({path:path.join(process.env.TEMP,'oneloss-jobs-comment-reference.png')});
 console.log('PASS: shared mention chips, email/link/code exclusions, safe Markdown, raw-text preservation and stable avatar identity');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
