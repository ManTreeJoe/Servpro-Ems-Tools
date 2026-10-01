const {chromium}=require('playwright'),fs=require('node:fs'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1200,height:800}});
 await page.setContent(fs.readFileSync('snapshot_web_assets/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(/<link\b[^>]*>/gi,''));
 await page.addStyleTag({path:path.resolve('web_shared/theme.css')});
 const source=fs.readFileSync('snapshot_web_assets/app.js','utf8');
 await page.addScriptTag({content:`
 const $=s=>document.querySelector(s),esc=s=>String(s||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),titleCase=s=>s;
 const state={queue:{search:'',board:'all',lane:'all',showAll:false},candidates:[
 {client:'Pending example',snapshot:true,card_id:'pending',lane:'Snapshot',board:'Estimating'},
 {client:'Saved example',snapshot:true,card_id:'saved',lane:'Snapshot',snapshot_generated:true,snapshot_revision:2}]};
 function startNew(client,card){window.selected={client,card};}
 ${source.slice(source.indexOf('function renderCandidateQueue()'),source.indexOf('function pickSnapshotDestination('))}
 renderCandidateQueue();`});
 assert.equal(await page.locator('#queue-count').textContent(),'1 need a snapshot');
 assert.equal(await page.locator('.generated-snapshots').getAttribute('open'),null);
 assert.equal(await page.locator('#recent-exports').getAttribute('open'),null);
 assert.equal(await page.getByText('Saved example',{exact:true}).isVisible(),false);
 await page.getByRole('button',{name:'Create snapshot',exact:true}).click();
 assert.deepEqual(await page.evaluate(()=>window.selected),{client:'Pending example',card:'pending'});
 await page.locator('.generated-snapshots summary').click();
 await page.getByRole('button',{name:'Review / recreate'}).click();
 assert.deepEqual(await page.evaluate(()=>window.selected),{client:'Saved example',card:'saved'});
 await page.locator('.generated-snapshots summary').click();
 await page.screenshot({path:path.join(process.env.TEMP,'snapshot-simplified-queue.png')});
 await page.evaluate(()=>{state.candidates=[];renderCandidateQueue();});
 assert.match(await page.locator('#candidates').textContent(),/No pending snapshots in the loaded queue/);
 console.log('PASS: pending first, saved collapsed, exports collapsed, exact card routing, empty state');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
