const {chromium}=require('playwright');
const {readFileSync}=require('node:fs');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try{
    const page=await browser.newPage();
    await page.setContent('<main id="workspace"></main>');
    await page.evaluate(()=>{
      window.statusValue={access_state:'signed_out'};
      window.pywebview={api:{
        settings_employee_access_status:async()=>statusValue,
        settings_supabase_sign_in_microsoft:async()=>{statusValue={access_state:'pending',email:'new@example.com'};return {ok:true};},
        settings_employee_sign_out:async()=>{statusValue={access_state:'signed_out'};},
      }};
    });
    await page.addScriptTag({content:readFileSync('home_web_assets/employee_access.js','utf8')});
    await page.evaluate(()=>{window.admitted=false;OneLossEmployeeAccess.ensure().then(()=>{admitted=true;});});
    await page.getByRole('button',{name:'Sign in with Microsoft',exact:true}).click();
    await page.getByRole('heading',{name:'Your account is waiting for approval'}).waitFor();
    assert.equal(await page.evaluate(()=>admitted),false);
    assert.equal(await page.locator('iframe').count(),0);
    await page.evaluate(()=>{statusValue={access_state:'approved',role:'viewer'};});
    await page.getByRole('button',{name:'Check approval'}).click();
    await page.waitForFunction(()=>admitted);
    assert.equal(await page.locator('section[aria-label="OneLoss employee sign-in"]').count(),0);
    console.log('PASS: Microsoft-only entry, pending blocks workspace, approval admits user.');
    // A browser may complete authentication while the original bridge promise never returns.
    await page.reload();
    await page.setContent('<main></main>');
    await page.evaluate(()=>{
      window.statusValue={access_state:'signed_out'};
      window.pywebview={api:{settings_employee_access_status:async()=>statusValue,
        settings_supabase_sign_in_microsoft:()=>new Promise(()=>{})}};
    });
    await page.addScriptTag({content:readFileSync('home_web_assets/employee_access.js','utf8')});
    await page.evaluate(()=>{window.admitted=false;OneLossEmployeeAccess.ensure().then(()=>{admitted=true;});});
    await page.getByRole('button',{name:'Sign in with Microsoft',exact:true}).click();
    await page.evaluate(()=>{statusValue={access_state:'pending',email:'new@example.com'};});
    await page.getByRole('heading',{name:'Your account is waiting for approval'}).waitFor();
    assert.equal(await page.evaluate(()=>admitted),false);
    await page.evaluate(()=>{statusValue={access_state:'approved',role:'editor'};});
    await page.getByRole('button',{name:'Check approval'}).click();
    await page.waitForFunction(()=>admitted);
    console.log('PASS: browser completion reaches pending/approved even when the original bridge response is lost.');

  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
