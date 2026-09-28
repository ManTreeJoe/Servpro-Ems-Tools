const {chromium}=require('playwright'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:850,height:700}});
 await page.setContent('<main style="max-width:760px;padding:20px"><section id="files" class="job-files-section"></section></main>');
 for(const f of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/job_files.css'])await page.addStyleTag({path:path.resolve(f)});
 await page.addScriptTag({path:path.resolve('pipeline_web_assets/job_files.js')});
 await page.evaluate(()=>{
  document.documentElement.dataset.theme='dark';window.opened=[];
  const folder=(name,relative=name)=>({name,relative,directory:true,kind:'folder'});
  const listings={'':[folder('Pics'),folder('Docs')],Pics:[folder('Initial','Pics/Initial'),folder('Demo','Pics/Demo')],'Pics/Initial':[{name:'Kitchen.jpg',relative:'Pics/Initial/Kitchen.jpg',kind:'photo',offline:true,size:100}],Docs:[{name:'Authorization.pdf',relative:'Docs/Authorization.pdf',kind:'document',size:500}]};
  window.pywebview={api:{job_files:async(_,p)=>({ok:true,files:listings[p]}),job_folder_open:async(_,p)=>{opened.push(p);return {ok:true};},job_file_preview:async()=>({ok:true,mime:'application/pdf',content:btoa('%PDF-1.4\n%%EOF')})}};
  JobFiles.mount(document.querySelector('#files'),{client:'Fixture'}).activate();
 });
 assert.equal(await page.locator('[data-files-up],[data-files-source],[data-file-filter]').count(),0);
 await page.getByRole('button',{name:/Initial (Open album|1 photo)/}).click();
 await page.getByRole('button',{name:'Open folder ↗',exact:true}).click();
 assert.deepEqual(await page.evaluate(()=>opened),['Pics/Initial']);
 await page.locator('[data-library="document"]').click();
 await page.getByRole('button',{name:/Authorization.pdf/}).click();
 await page.locator('[data-preview-content] iframe').waitFor();
 assert.equal(await page.locator('[data-preview-content] iframe').getAttribute('title'),'Authorization.pdf');
 await page.locator('[data-library="photo"]').click();
 await page.getByRole('button',{name:/Demo (Open album|0 photos)/}).waitFor();
 await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-stage-folders.png')});
 await page.setViewportSize({width:430,height:700});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 console.log('PASS: Pics stages, exact Open folder, Docs PDF preview and narrow layout');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
