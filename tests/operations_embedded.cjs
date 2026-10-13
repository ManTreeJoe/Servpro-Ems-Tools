const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert/strict');
(async()=>{
 const root=path.resolve('.');
 const server=http.createServer((req,res)=>{
  const pathname=new URL(req.url,'http://local').pathname;
  if(pathname==='/host')return res.end('<script>window.calls=[];window.pywebview={api:{operations_bootstrap:async(force)=>{calls.push(force);return {ok:false,error:"Fixture data unavailable"}}}};</script><iframe src="/operations_web_assets/index.html?embedded=1"></iframe>');
  const file=path.join(root,pathname);
  if(!file.startsWith(root)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);return res.end('Not found');}
  res.setHeader('Content-Type',file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'application/octet-stream');
  res.end(fs.readFileSync(file));
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage();
  await page.goto(`http://127.0.0.1:${server.address().port}/host`);
  await page.waitForFunction(()=>calls.length===1,{},{timeout:7000});
  const frame=page.frames().find(f=>f.url().includes('operations_web_assets'));
  assert.match(await frame.locator('[data-status]').textContent(),/Fixture data unavailable/);
  await frame.locator('[data-refresh]').click();
  await page.waitForFunction(()=>calls.length===2);
  assert.deepEqual(await page.evaluate(()=>calls),[false,true]);
  await page.evaluate(()=>{window.navigation=[];window.addEventListener('message',e=>{if(e.data?.type==='ems-navigate')navigation.push(e.data.key);});});
  await frame.locator('.day-board [data-open-schedule]').click();
  await page.waitForFunction(()=>navigation.includes('run_doc_editor'));
  assert.equal(await frame.locator('[data-panel="dispatch"]').count(),0);
  await frame.evaluate(()=>{
    state.data={source:'shared',generated_at:new Date().toISOString(),overview:{active_jobs:47,clients:100,overdue:2,stalled:8,due_today:3,divisions:{EMS:45,CONTENTS:2,RECON:0}},jobs:[],reports:{lane_counts:[{label:'Pending coverage',value:8}]},schedule:{ok:true,date:'2026-10-12',today_visits:12,tbs:7,pending:4,hold:2,past_visits:1,needs_link:3}};
    renderSignals();renderHome();
  });
  assert.equal(await frame.locator('[data-schedule-count=today_visits]').innerText(),'12');
  assert.equal(await frame.locator('[data-metric=due_today]').innerText(),'3');
  assert.match(await frame.locator('[data-lane-summary]').innerText(),/8 of 47 active cards/);
  for(const theme of ['light','dark']){
    await frame.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
    const fonts=await frame.evaluate(()=>['body','h1','h2','.signal strong','.priority-feed','select'].map(selector=>{
      const el=document.querySelector(selector);return el?getComputedStyle(el).fontFamily:'';
    }).filter(Boolean));
    assert.ok(fonts.every(font=>font.includes('Segoe UI')&&!font.includes('Georgia')&&!font.includes('Times')),'All Operations typography uses the shared sans-serif stack');
  }
  await frame.evaluate(()=>{
    state.data.attention={ok:true,covered_cards:2,active_cards:47,schedule_ok:true,items:[
      {id:'a',category:'Timing',card_id:'a',title:'Example job',action:'Contact insured',detail:'5 min remaining'},
      {id:'s',category:'Schedule',title:'Unlinked visit',action:'Review schedule',detail:'Job link missing'}]};
    renderFollowups();
  });
  assert.equal(await frame.locator('[data-followups] button').count(),2);
  await frame.locator('[data-followup-filter]').selectOption('Schedule');
  assert.equal(await frame.locator('[data-followups] button').count(),1);
  await page.evaluate(()=>navigation=[]);
  await frame.locator('[data-followup-schedule]').click();
  await page.waitForFunction(()=>navigation.includes('run_doc_editor'));
  await frame.locator('[data-followup-filter]').selectOption('Billing');
  assert.match(await frame.locator('[data-followups]').innerText(),/No follow-ups found/);
  await frame.locator('[data-followup-filter]').selectOption('All');
  assert.equal(await frame.locator('[data-tool="job_notes_web"],[data-tool="photo_folders_web"]').count(),0);
  await page.setViewportSize({width:1440,height:950});
  await page.evaluate(()=>{document.querySelector('iframe').style.cssText='width:100%;height:920px;border:0';});
  await page.screenshot({path:path.join(require('os').tmpdir(),'operations-shared-schedule.png')});
  await frame.evaluate(()=>{state.data.schedule={ok:false};renderHome();showView('jobs');});
  assert.equal(await frame.locator('[data-schedule-count=today_visits]').innerText(),'—');
  await page.evaluate(()=>{
   const frame=document.querySelector('iframe');
   const item={key:'operations',src:frame.getAttribute('src')};
   window.state={frames:new Map([['operations',frame]]),frameOrder:['operations']};
   window.findItem=()=>item;window.MAX_WARM_PANELS=4;
   window.$=()=>({classList:{add(){},toggle(){}}});window.$$=()=>[];
  });
  const shell=fs.readFileSync('home_web_assets/app.js','utf8');
  await page.addScriptTag({content:shell.slice(shell.indexOf('function navigate('),shell.indexOf('\nfunction findItem('))});
  await page.evaluate(()=>navigate('operations'));
  assert.equal(await frame.locator('[data-panel="home"]').isVisible(),true);
  assert.equal(await frame.locator('[data-panel="jobs"]').isVisible(),false);
  assert.deepEqual(await page.evaluate(()=>calls),[false,true],'Return does not refetch');
  console.log('Operations embedded bridge and retry passed.');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);process.exitCode=1;});
