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
  await frame.locator('[data-go-dispatch]').click();
  assert.equal(await frame.locator('[data-panel="dispatch"]').isVisible(),true);
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
  assert.equal(await frame.locator('[data-panel="dispatch"]').isVisible(),false);
  assert.deepEqual(await page.evaluate(()=>calls),[false,true],'Return does not refetch');
  console.log('Operations embedded bridge and retry passed.');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);process.exitCode=1;});
