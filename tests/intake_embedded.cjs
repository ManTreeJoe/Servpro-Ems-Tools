const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert/strict');
(async()=>{
 const root=path.resolve('.');
 const server=http.createServer((req,res)=>{
  const pathname=new URL(req.url,'http://local').pathname;
  if(pathname==='/host')return res.end(`<script>window.calls=[];window.pywebview={api:new Proxy({}, {get:(target,key)=>async(...args)=>{calls.push(key);if(String(key).endsWith('new_loss_templates'))return {ok:true,default_template_id:'res',templates:[{id:'res',name:'EMS Residential Template',kind:'water'}]};return {ok:true};}})};</script><iframe style="width:1200px;height:900px" src="/pipeline_web_assets/index.html?intake_only=1"></iframe>`);
  const file=path.resolve(root,'.'+pathname);
  if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);return res.end('Not found');}
  res.setHeader('Content-Type',file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':'application/octet-stream');
  res.end(fs.readFileSync(file));
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:960}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/host`);
  const shell=fs.readFileSync('home_web_assets/app.js','utf8');
  await page.addScriptTag({content:shell.slice(shell.indexOf('function openNewLossWhenReady('),shell.indexOf('function openRequestedBrowserPanel('))});
  await page.evaluate(()=>openNewLossWhenReady(document.querySelector('iframe')));
  const frame=page.frames().find(f=>f.url().includes('pipeline_web_assets'));
  await frame.waitForSelector('#nl-loss_type');
  await frame.waitForFunction(()=>document.querySelector('#nl-loss_type').value==='res');
  assert.equal(await frame.locator('#nl-insured_name').isVisible(),true);
  assert.equal(await frame.locator('#new-loss-btn').isVisible(),false);
  assert.equal((await page.evaluate(()=>calls)).some(name=>name.includes('board_view')),false);
  await frame.locator('#nl-insured_name').fill('Test customer');
  assert.equal(await frame.locator('#nl-card_name').inputValue(),'Test customer');
  assert.deepEqual(errors,[]);
  console.log('PASS: real embedded Jobs intake boot, shared bridge, visible dialog, no background board load.');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);process.exitCode=1;});
