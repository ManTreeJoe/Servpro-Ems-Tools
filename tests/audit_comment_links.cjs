const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1200,height:850}});
 await page.setContent('<dialog id="audit"><article data-comment-id="c1"><p>Contents started yesterday.</p></article><article data-comment-id="c2"><p>Initial field note</p></article><input id="draft" value="Keep my draft"></dialog>');
 await page.addStyleTag({path:path.resolve('web_shared/theme.css')});await page.addStyleTag({path:path.resolve('web_shared/audit_comment_links.css')});
 await page.addScriptTag({path:path.resolve('analytics_web_assets/audit_field_controls.js')});
 await page.addScriptTag({path:path.resolve('web_shared/audit_comment_links.js')});
 assert.deepEqual(await page.evaluate(()=>[
  AuditFieldControls.pacificParts('2026-10-01T22:14:00Z'),
  AuditFieldControls.pacificParts('2026-10-02T01:14:00Z'),
  AuditFieldControls.pacificParts('2026-01-02T01:14:00Z'),
  AuditFieldControls.pacificParts('2026-11-01T08:30:00Z'),
  AuditFieldControls.pacificParts('2026-11-01T09:30:00Z')
 ]),[
  {day:'2026-10-01',time:'15:14',zone:'Pacific'},
  {day:'2026-10-01',time:'18:14',zone:'Pacific'},
  {day:'2026-01-01',time:'17:14',zone:'Pacific'},
  {day:'2026-11-01',time:'01:30',zone:'-07:00'},
  {day:'2026-11-01',time:'01:30',zone:'-08:00'}
 ]);
 await page.evaluate(()=>{
  window.commands=[];window.links={version:null,items:{}};
  const targets={contents_start:['Contents work started','date'],field_note_posted_at:['Field inspection note','timestamp']};
  window.pywebview={api:{audit_comment_links:async(card,command)=>{
   if(command){commands.push(command);if(command.previous&&command.previous!==command.target)links.items[command.previous]=null;links.items[command.target]=command.remove?null:{comment_id:command.comment_id,value:command.value};links.version=String(commands.length);}
   return {ok:true,links:structuredClone(links),targets};
  }}};
  AuditCommentLinks.bind(document.querySelector('#audit'),target=>{const row=target.closest('[data-comment-id]');return row?{row,card:'card',comment:{id:row.dataset.commentId,text:row.textContent,author:'Test',date:'2026-04-08T20:14:00Z'}}:null;});
  document.querySelector('#audit').showModal();
 });
 await page.locator('[data-comment-id=c1]').click({button:'right'});
 await page.getByRole('menuitem',{name:'Contents work started',exact:true}).click();
 assert.equal(await page.getByLabel('Event date',{exact:true}).inputValue(),'','work date is not inferred from posting time');
 await page.getByRole('button',{name:'Save link',exact:true}).click();assert.equal(await page.evaluate(()=>commands.length),0);
 await page.getByLabel('Event date',{exact:true}).fill('04/07/2026');
 await page.screenshot({path:path.join(require('node:os').tmpdir(),'audit-comment-link.png')});
 await page.getByRole('button',{name:'Save link',exact:true}).click();
 await page.waitForFunction(()=>commands.length===1);
 assert.equal(await page.locator('#draft').inputValue(),'Keep my draft');
 assert.match(await page.locator('[data-comment-id=c1]').innerText(),/Linked: Contents work started/);
 await page.locator('[data-comment-id=c1]').click({button:'right'});
 await page.getByRole('menuitem',{name:'Edit link: Contents work started'}).click();
 assert.equal(await page.getByLabel('Event date',{exact:true}).inputValue(),'04/07/2026');
 await page.getByLabel('Event date',{exact:true}).fill('04/06/2026');await page.getByRole('button',{name:'Save link',exact:true}).click();
 await page.waitForFunction(()=>commands.length===2);
 await page.locator('[data-comment-id=c1]').click({button:'right'});await page.getByRole('menuitem',{name:'Edit link: Contents work started'}).click();
 await page.getByRole('button',{name:'Unlink',exact:true}).click();await page.waitForFunction(()=>commands.length===3);
 assert.equal(await page.locator('[data-comment-id=c1] [data-audit-link-badges]').innerText(),'');
 await page.locator('[data-comment-id=c2]').click({button:'right'});await page.getByRole('menuitem',{name:'Field inspection note',exact:true}).click();
 assert.equal(await page.getByLabel('Event time',{exact:true}).inputValue(),'13:14','UTC posting timestamp must display in Pacific');
 assert.deepEqual(await page.evaluate(()=>AuditCommentLinks.inspectionSuggestion('Initial Inspection performed Thursday, 10/1/26\nArrival Time:12:00PM')), {day:'10/01/2026',time:'12:00'});
 assert.deepEqual(await page.evaluate(()=>AuditCommentLinks.inspectionSuggestion('**Date:**4/8\n**Time of Inspection:**11:00')), {day:'',time:''});
 await page.getByLabel('Inspection date',{exact:true}).fill('04/08/2026');
 await page.getByLabel('Inspection time',{exact:true}).fill('11:00');
 await page.getByText('Save this confirmed inspection time (Pacific)',{exact:true}).click();
 await page.screenshot({path:require('node:path').join(process.env.TEMP,'inspection-link-editor.png')});
 await page.getByRole('button',{name:'Save link',exact:true}).click();await page.waitForFunction(()=>commands.length===4);
 assert.equal(await page.evaluate(()=>commands[3].value),'2026-04-08T20:14:00Z');
 assert.equal(await page.evaluate(()=>commands[3].inspection),'2026-04-08T11:00-07:00');
 assert.equal(await page.locator('#audit').isVisible(),true);
 console.log('PASS: right-click, modal layering, explicit work date, edit, unlink, timestamp, badges, draft preservation');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
