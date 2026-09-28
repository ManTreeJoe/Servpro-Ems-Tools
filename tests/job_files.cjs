const {chromium}=require('playwright'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1000,height:900},colorScheme:'dark'});
 await page.setContent('<main style="max-width:760px;margin:24px"><section id="files" class="job-files-section"></section></main>');
 for(const file of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/job_files.css'])await page.addStyleTag({path:path.resolve(file)});
 await page.addScriptTag({path:path.resolve('pipeline_web_assets/job_files.js')});
 await page.evaluate(()=>{
  window.calls=[];window.opened=[];window.pywebview={api:{
   job_files:(client,relative)=>{calls.push(relative);return new Promise(resolve=>window.finishList=resolve)},
   job_file_preview:async(client,file,thumbnail)=>thumbnail ? {ok:false,error:'thumb offline'} : {ok:false,error:'This file is online-only. Download it in OneDrive, then retry.'},
   open_url:async url=>opened.push(url),job_file_open:async()=>({ok:false,error:'Unavailable'})}};
  window.viewer=JobFiles.mount(document.querySelector('#files'),{client:'Fixture job',attachments:[{name:'Policy.pdf',url:'https://trello.com/fixture'}]});
 });
 assert.deepEqual(await page.evaluate(()=>calls),[],'Mount must not load before Files selected');
 await page.evaluate(()=>viewer.activate());
 assert.match(await page.locator('[data-files-status]').textContent(),/Loading/);
 await page.evaluate(()=>finishList({ok:true,files:[{name:'Photos',relative:'Photos',directory:true,kind:'folder'},{name:'Policy.pdf',relative:'Policy.pdf',kind:'document',size:1500}]}));
 await page.getByRole('button',{name:/Photos Folder/}).click();
 assert.deepEqual(await page.evaluate(()=>calls),['','Photos']);
 await page.evaluate(()=>finishList({ok:true,files:[{name:'Kitchen.jpg',relative:'Photos/Kitchen.jpg',kind:'photo',offline:true,size:24000},{name:'Hall.jpg',relative:'Photos/Hall.jpg',kind:'photo',offline:true,size:24000}]}));
 await page.getByRole('button',{name:/Kitchen.jpg/}).click();
 await page.waitForFunction(()=>document.querySelector('[data-preview-content]').textContent.includes('online-only'));
 await page.getByRole('button',{name:'Next photo',exact:true}).click();
 assert.equal(await page.locator('[data-preview-name]').textContent(),'Hall.jpg');
 await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-job-files.png')});
 await page.evaluate(()=>{pywebview.api.job_file_preview=async()=>({ok:true,mime:'image/png',content:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a/s8AAAAASUVORK5CYII='});});
 await page.getByRole('button',{name:/Kitchen.jpg/}).click();
 await page.waitForFunction(()=>document.querySelector('[data-preview-content] img')?.complete);
 assert.match(await page.locator('[data-preview-content] img').getAttribute('src'),/^blob:/);
 await page.evaluate(()=>{pywebview.api.job_file_preview=async()=>({ok:true,mime:'application/pdf',content:btoa('%PDF-1.4\n%%EOF')});});
 await page.getByRole('button',{name:/Hall.jpg/}).click();
 await page.locator('[data-preview-content] iframe').waitFor();
 assert.equal(await page.locator('[data-preview-content] iframe').getAttribute('title'),'Hall.jpg');
 await page.locator('[data-files-source]').selectOption('trello');
 await page.getByRole('button',{name:/Policy.pdf/}).click();
 assert.deepEqual(await page.evaluate(()=>opened),['https://trello.com/fixture']);
 await page.locator('[data-files-source]').selectOption('folder');
 await page.evaluate(()=>finishList({ok:false,error:'Folder is unavailable'}));
 await page.waitForFunction(()=>document.querySelector('[data-files-status]').textContent==='Folder is unavailable');
 assert.equal(await page.locator('.job-file-row').count(),0);
 // Exercise the production modal and its off-screen refresh preparation.
 await page.setContent('<div id="status-msg"></div>');
 for(const file of ['web_shared/theme.css','pipeline_web_assets/app.css','web_shared/modal.css','pipeline_web_assets/job_workspace_tabs.css','pipeline_web_assets/job_files.css'])await page.addStyleTag({path:path.resolve(file)});
 for(const file of ['web_shared/modal.js','pipeline_web_assets/job_files.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(file)});
 await page.evaluate(()=>{
   window.calls=[]; window.pywebview={api:{job_files:async()=>{calls.push('list');return {ok:true,files:[{name:'Docs',relative:'Docs',directory:true,kind:'folder'}]}}}};
   window.fixture={ok:true,client:'Fixture job',card_id:'fixture-card',selected_division:'EMS',audit:{found:true},crm:{job_log:[]},comments:[],attachments:[]};
   window.workspace=openAuditModal(fixture);
 });
 assert.equal(await page.evaluate(()=>calls.length),0);
 await page.getByRole('tab',{name:'Files',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('.job-files-list')?.textContent.includes('Docs'));
 await page.locator('[data-comment-input]').fill('Preserve this draft');
 await page.evaluate(()=>{window.originalFiles=document.querySelector('.job-files-section');workspace.applyRefresh({...fixture,attachments:[{name:'New.pdf',url:'https://trello.com/new'}]});});
 assert.equal(await page.evaluate(()=>originalFiles===document.querySelector('.job-files-section')),true);
 assert.equal(await page.evaluate(()=>calls.length),1,'Refresh preparation must not rescan files');
 assert.equal(await page.locator('[data-comment-input]').inputValue(),'Preserve this draft');
 await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-job-files-modal.png')});
 console.log('PASS: lazy loading, folder navigation, failure recovery, photo navigation, attachment opening');
}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1});
