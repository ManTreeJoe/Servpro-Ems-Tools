// Synthetic Microsoft/approval regression suite. All requests intercepted before pages exist.
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
(async()=>{
 const env={};for(const k of ['SystemRoot','WINDIR','TEMP','TMP','LOCALAPPDATA','PROGRAMFILES','PROGRAMFILES(X86)','PATH'])if(process.env[k])env[k]=process.env[k];
 const browser=await chromium.launch({channel:'msedge',headless:true,env});
 try{
 const ctx=await browser.newContext({serviceWorkers:'block'});const unexpected=[];
 await ctx.route('**/*',async r=>{const u=new URL(r.request().url()),rel=decodeURIComponent(u.pathname).slice(1),f=path.resolve(root,rel);
  if(u.origin==='https://settings.test' && /^(settings_web_assets|web_shared)\/[\w./-]+\.(html|js|css|svg|png|woff2?)$/.test(rel)&&f.startsWith(root+path.sep)&&fs.existsSync(f))return r.fulfill({path:f});
  unexpected.push(u.origin+u.pathname);await r.abort();});
 const p=await ctx.newPage();p.setDefaultTimeout(10000);
 await p.goto('https://settings.test/settings_web_assets/index.html');
 await p.evaluate(()=>{window.calls=[];window.pywebview={api:{supabase_sign_in_microsoft:async(...a)=>{calls.push(['microsoft',...a]);return {ok:true}},supabase_sign_in_password:async()=>{calls.push(['password'])}}};window.refreshSupabase=async()=>{};window.renderConnections=async()=>{};bindSupabaseControls();openSupabaseSignIn();});
 assert.equal(await p.locator('#sb-email').inputValue(),'');
 assert.equal(await p.locator('#sb-password').isVisible(),false);
 assert.equal(await p.locator('#sb-password-signin').evaluate(el=>!!el.closest('[hidden][inert]')),true);
 await p.locator('#sb-microsoft-signin').click();
 assert.deepEqual(await p.evaluate(()=>calls),[['microsoft']]);
 console.log('PASS Microsoft button accepts empty fields; password controls hidden/inert');
 await p.close();
 for(const admin of [false,true]){
 const page=await ctx.newPage();await page.setContent('<main><section id="user-access-card"></section></main><button data-scope-tab="admin" class="active"></button>');
 await page.evaluate(admin=>{window.decisions=[];window.pywebview={api:{employee_access_status:async()=>({is_admin:admin}),employee_admin_snapshot:async()=>({ok:true,users:[{user_id:'test-user',email:'user@example.invalid',status:'pending',role:'viewer',departments:[],revision:1}],franchises:[{code:'TEST',label:'Test office'}]}),employee_decide_user:async(...args)=>{decisions.push(args);return {ok:true}}}};},admin);
 await page.addScriptTag({content:fs.readFileSync(path.join(root,'settings_web_assets/employee_admin.js'),'utf8')});
 await page.evaluate(()=>window.dispatchEvent(new Event('pywebviewready')));
 if(admin){await page.locator('#employee-access-card form').waitFor();
 for(const role of ['viewer','editor','admin']){await page.getByRole('combobox').selectOption(role);await page.getByRole('checkbox').check();await page.getByRole('button',{name:'Approve and save'}).click();await page.waitForFunction(n=>decisions.length===n, ['viewer','editor','admin'].indexOf(role)+1);}
 assert.deepEqual(await page.evaluate(()=>decisions),['viewer','editor','admin'].map(r=>['test-user','approve',r,['TEST'],1]));
 }else{assert.equal(await page.locator('#employee-access-card').count(),0);}
 await page.close();console.log(`PASS ${admin?'admin can assign franchise and all three roles':'employee has no approval panel'}`);
 }
 const gate=await ctx.newPage();await gate.setContent('<main id="workspace"></main>');
 await gate.evaluate(()=>{window.pywebview={api:{settings_employee_access_status:async()=>({access_state:'pending',email:'test@example.invalid'})}};window.admitted=false;});
 await gate.addScriptTag({content:fs.readFileSync(path.join(root,'home_web_assets/employee_access.js'),'utf8')});
 await gate.evaluate(()=>{OneLossEmployeeAccess.ensure().then(()=>{admitted=true;document.querySelector('main').textContent='Jobs';});});
 await gate.getByRole('heading',{name:'Your account is waiting for approval'}).waitFor();
 assert.equal(await gate.evaluate(()=>admitted),false);assert.equal(await gate.locator('iframe').count(),0);assert.equal(await gate.locator('main').innerText(),'');
 console.log('PASS pending user receives approval screen, no jobs admitted');
 assert.deepEqual(unexpected,[]);console.log('PASS no unexpected requests');await ctx.close();
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
