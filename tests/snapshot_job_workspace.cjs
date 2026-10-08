const {chromium}=require('playwright'), http=require('node:http'), fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
const fixture={ok:true,client:'Sample restoration job',card_id:'card1',selected_division:'EMS',audit:{found:true},crm:{},info_sections:[{name:'Customer Information',fields:[{id:'customer_name',label:'Customer name',value:'Sample customer'},{id:'address',label:'Address',value:'123 Sample St'}]}],comments:[{id:'c1',text:'Ready for review',member:'Sam',source:'trello'}],division_trello_cards:[{division:'EMS',card_id:'card1',pinned:true}]};
fixture.division_trello_cards.push({division:'CONTENTS',card_id:'contents1',pinned:true},{division:'RECON',card_id:'recon1',pinned:true});
const server=http.createServer((req,res)=>{
 const pathname=new URL(req.url,'http://local').pathname;
 if(pathname==='/shell'||pathname==='/snapshot_web_assets/fixture')res.setHeader('Content-Type','text/html');
 if(pathname==='/shell')return res.end(`<iframe src="/snapshot_web_assets/fixture" style="width:100%;height:96vh;border:0"></iframe><script>window.calls=[];window.pywebview={api:new Proxy({}, {get:(_,name)=>(...args)=>{calls.push(name);if(name.includes('job_card_workspace'))return Promise.resolve(${JSON.stringify(fixture)});if(name.includes('refresh_job_comments')||name.includes('saved_job_comments'))return Promise.resolve({ok:true,comments:${JSON.stringify(fixture.comments)}});if(name.includes('comment_thread_state'))return Promise.resolve({ok:true,comments:[],pins:[],threads:[]});return Promise.resolve({ok:true});}})};</script>`);
 if(pathname==='/snapshot_web_assets/fixture')return res.end(`<link rel="stylesheet" href="/web_shared/theme.css"><link rel="stylesheet" href="/snapshot_web_assets/job_workspace.css"><body class="snapshot-panel"><h2>Snapshot report</h2><textarea id="report">Report draft stays here</textarea><main id="view-gen" style="height:650px;overflow-y:auto"><div id="audit-subview"><span id="audit-summary"></span><div id="audit-result"></div></div><div style="height:500px"></div></main><script src="/snapshot_web_assets/job_workspace.js"></script><script>SnapshotJobWorkspace.select({cardId:'card1',client:'Sample restoration job',division:'EMS'});</script></body>`);
 const file=path.resolve('.'+pathname);if(!file.startsWith(process.cwd()+path.sep)){res.statusCode=403;return res.end();}
 try{res.setHeader('Content-Type',pathname.endsWith('.js')?'application/javascript':pathname.endsWith('.css')?'text/css':pathname.endsWith('.html')?'text/html':'application/octet-stream');res.end(fs.readFileSync(file));}catch{res.statusCode=404;res.end();}
});
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:950}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(`http://127.0.0.1:${server.address().port}/shell`);
 const snapshot=page.frames().find(f=>f.url().endsWith('/snapshot_web_assets/fixture'));
 const comment=()=>page.frames().find(f=>f.url().includes('snapshot_comments=1'));
 const card=()=>page.frames().find(f=>f.url().includes('snapshot_card=1'));
 try { await page.waitForFunction(()=>calls.some(n=>n==='pipeline_job_card_workspace'),null,{timeout:10000}); }
 catch(error) { console.log('Calls',await page.evaluate(()=>calls),'Errors',errors,'Frames',page.frames().map(f=>f.url())); if(comment())console.log(await comment().locator('body').innerText());throw error; }
 await card().waitForSelector('[data-edit-job-info]');
 try { await card().waitForFunction(()=>document.querySelector('.job-info-section').textContent.includes('Sample customer'),null,{timeout:5000}); }
 catch(error) {console.log('Workspace errors',errors,await card().locator('body').innerText());throw error;}
 assert.equal(await card().getByRole('tab',{name:'Job Log',exact:true}).count(),0);
 assert.equal(await card().locator('.job-division-folder-tabs').count(),0);
 assert.equal(await card().locator('.card-quick-actions [data-add-job-log]').count(),0);
 assert.equal(await card().locator('[data-work-type-card]').count(),1);
 for(const name of ['Overview','Requirements','Files','Card Details']) {
   const tab=card().getByRole('tab',{name,exact:true});
   await tab.click();assert.equal(await tab.getAttribute('aria-selected'),'true');
 }
 await card().getByRole('tab',{name:'Overview',exact:true}).click();
 assert.equal(await card().locator('[data-job-members]').isVisible(),true);
 assert.equal(await card().locator('[data-edit-job-info]').isVisible(),true);
 await card().locator('.more-quick-menu > .tool-menu-trigger').click();
 assert.equal(await card().locator('[data-copy-customer-info]').isVisible(),true);
 await card().locator('.more-quick-menu > .tool-menu-trigger').click();
 assert.equal(await card().locator('.job-card-activity').isVisible(),false);
 await comment().waitForSelector('[data-comment-input]',{state:'attached'});
 assert.equal(await comment().locator('[data-comment-destination]').count(),1);
 assert.equal(await comment().locator('[data-comment-destination]').getAttribute('data-comment-destination'),'EMS');
 assert.equal(await comment().locator('[data-comment-division]').count(),0);
 await card().waitForFunction(()=>document.querySelector('.job-card-main').scrollHeight<=document.querySelector('.job-card-main').clientHeight+2);
 await comment().locator('[contenteditable="true"]').first().fill('Unsent reply');
 await comment().locator('[contenteditable="true"]').first().press('Escape');
 assert.equal(await comment().locator('.audit-overlay').count(),1,'Escape must not close comments');
 assert.equal(await comment().locator('[data-close]').isVisible(),false);
 await snapshot.evaluate(()=>{window.originalFrame=document.querySelector('iframe');SnapshotJobWorkspace.render();SnapshotJobWorkspace.select({cardId:'card1',client:'Sample restoration job',division:'EMS'});});
 assert.equal(await snapshot.evaluate(()=>originalFrame===document.querySelector('iframe')),true,'same-card refresh must retain conversation');
 assert.equal(await comment().locator('[data-comment-input]').inputValue(),'Unsent reply');
 assert.equal(await snapshot.locator('#report').inputValue(),'Report draft stays here');
 assert.equal(await comment().locator('[data-comment-pinned-filter]').count(),1,'real job-card pin filter');
 await card().locator('.modal-title').hover();
 await page.mouse.wheel(0,350);
 await page.waitForTimeout(250);
 assert.ok(await snapshot.evaluate(()=>document.querySelector('#view-gen').scrollTop)>100,'wheel over embedded job card must scroll Snapshot');
 const down=await snapshot.evaluate(()=>document.querySelector('#view-gen').scrollTop);
 await page.mouse.wheel(0,-200);
 await page.waitForTimeout(150);
 assert.ok(await snapshot.evaluate(()=>document.querySelector('#view-gen').scrollTop)<down,'reverse wheel must scroll upward');
 await snapshot.evaluate(()=>document.querySelector('#view-gen').scrollTop=0);
 await card().evaluate(()=>{
   const field=document.createElement('textarea');field.id='scroll-test-editor';field.style.cssText='position:fixed;top:20px;left:20px;width:200px;height:80px;z-index:9999';field.value=Array(40).fill('Editor line').join('\n');document.body.append(field);
 });
 await card().locator('#scroll-test-editor').hover();await page.mouse.wheel(0,150);await page.waitForTimeout(150);
 assert.equal(await snapshot.evaluate(()=>document.querySelector('#view-gen').scrollTop),0,'editor scroll must not move report');
 assert.ok(await card().locator('#scroll-test-editor').evaluate(el=>el.scrollTop)>0);
 await card().locator('#scroll-test-editor').evaluate(el=>el.remove());
 await comment().locator('.comment-stream').hover();await page.mouse.wheel(0,200);await page.waitForTimeout(150);
 assert.equal(await snapshot.evaluate(()=>document.querySelector('#view-gen').scrollTop),0,'comment wheel must not move report');
 await page.screenshot({path:require('node:os').tmpdir()+'/snapshot-job-workspace.png'});
 await page.setViewportSize({width:760,height:950});
 await page.waitForTimeout(100);
 const box=await comment().locator('[data-post-comment]').boundingBox();
 assert.ok(box && box.width>0 && box.y+box.height<950,'composer must stay reachable on narrow screens');
 await page.screenshot({path:require('node:os').tmpdir()+'/snapshot-job-workspace-narrow.png'});
 assert.deepEqual(errors,[]);
 console.log('PASS: full job-card tabs/actions, nested routing, permanent comments/pins, report and reply draft retention');
}finally{await browser.close();server.close();}})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
