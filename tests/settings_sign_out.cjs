const {chromium}=require('playwright');
const fs=require('node:fs'); const path=require('node:path'); const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const context=await browser.newContext({serviceWorkers:'block'});
  const blocked=[]; let loads=0, signedOut=false, fail=true;
  await context.route('**/*', async route=>{
   const url=new URL(route.request().url());
   if(url.origin!=='https://signout.test'){blocked.push(url.href);return route.abort();}
   if(url.pathname==='/'){
    loads++;
    return route.fulfill({contentType:'text/html',body:signedOut
     ? '<body><script src="/home_web_assets/employee_access.js"></script><script>window.pywebview={api:{settings_employee_access_status:async()=>({access_state:"signed_out"})}};OneLossEmployeeAccess.ensure();</script>'
     : '<iframe src="/settings_web_assets/index.html"></iframe>'});
   }
   const file=path.resolve('.'+decodeURIComponent(url.pathname));
   if(file.startsWith(process.cwd()+path.sep)&&fs.existsSync(file))return route.fulfill({path:file});
   return route.fulfill({status:404,body:''});
  });
  const page=await context.newPage();
  await page.exposeFunction('fakeSignOut',()=>{if(fail)return {ok:false,error:'Synthetic failure'};signedOut=true;return {ok:true};});
  await page.goto('https://signout.test/');
  const frame=page.frames().find(f=>f.url().includes('settings_web_assets'));
  await frame.waitForFunction(()=>typeof bindSupabaseControls==='function');
  await frame.evaluate(()=>{window.pywebview={api:{supabase_sign_out:()=>window.fakeSignOut()}};bindSupabaseControls();});
  await frame.locator('#sb-sign-out').evaluate(b=>b.click());
  await frame.waitForFunction(()=>document.querySelector('#sb-msg').textContent==='Synthetic failure');
  assert.equal(loads,1,'Failed sign-out must not reload');
  fail=false;
  await frame.locator('#sb-sign-out').evaluate(b=>b.click());
  await page.getByRole('heading',{name:'Welcome to OneLoss'}).waitFor();
  await page.getByRole('button',{name:'Sign in with Microsoft',exact:true}).waitFor();
  assert.equal(loads,2);assert.equal(page.frames().length,1,'Old tool frames must unload');
  assert.deepEqual(blocked,[]);
  console.log('PASS: failed sign-out stays put; successful sign-out reloads the parent shell, removes tool frames, and returns to Microsoft login. No provider requests.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

