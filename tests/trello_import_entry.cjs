// Render the production job import dialog without accessing customer data.
const {chromium}=require('playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage();
  await page.setContent('<body></body>');
  const source=fs.readFileSync('pipeline_web_assets/app.js','utf8');
  const dialog=source.slice(source.indexOf('async function openJobFileImportModal('),source.indexOf('async function openCompanyCamPullModal('));
  await page.addScriptTag({content:'function escapeHtml(s){return s;}\n'+dialog});
  await page.evaluate(()=>openJobFileImportModal({client:'Test job',card_id:'test-card'},{}));
  const buttons=await page.locator('.job-file-import-actions button').allTextContents();
  console.log('Rendered import actions:',buttons.join(', '));
  assert.ok(buttons.some(text=>/trello/i.test(text)), 'Job Import files dialog must expose Pull from Trello attachments');
  await page.evaluate(()=>{window.pulls=[];window.openTrelloAttachmentsModal=async payload=>pulls.push(payload);});
  await page.locator('[data-import-trello]').click();
  assert.deepEqual(await page.evaluate(()=>pulls),[{cardId:'test-card',client:'Test job'}]);
  await page.locator('[data-close]').click();
  await page.evaluate(()=>openJobFileImportModal({client:'Unlinked job'},{}));
  assert.equal(await page.locator('[data-import-trello]').isDisabled(),true);
  await page.locator('[data-close]').click();
  await page.addScriptTag({path:'web_shared/trello_attachments.js'});
  await page.evaluate(()=>{
   window.downloads=[];
   window.pywebview={api:{
    list_card_attachments:async id=>({ok:true,attachments:[{id:'attachment-1',name:'photo.jpg',is_image:true,is_upload:true,url:'https://trello.com/example',size:123}]}),
    download_card_attachments:async (...args)=>{downloads.push(args);return {ok:true,saved:['photo.jpg'],count:1};}
   }};
   return openJobFileImportModal({client:'Test job',card_id:'exact-division-card'},{});
  });
  await page.locator('[data-import-trello]').click();
  await page.locator('#ta-sel-all').click();
  await page.locator('#ta-download').click();
  assert.deepEqual(await page.evaluate(()=>downloads),[['exact-division-card',['attachment-1'],'Test job']]);
  await page.locator('#ta-close').click();
  assert.equal(await page.locator('[data-import-pick]').isVisible(),true);
  console.log('PASS: Trello source passes exact current card and client; unlinked job cannot import.');
 } finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
