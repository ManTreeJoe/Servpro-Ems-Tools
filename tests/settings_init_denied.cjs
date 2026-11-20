const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(process.env.SETTINGS_SOURCE||path.join(__dirname,'..'));
 const env={};for(const k of ['SystemRoot','WINDIR','TEMP','TMP','LOCALAPPDATA','PROGRAMFILES','PROGRAMFILES(X86)','PATH'])if(process.env[k])env[k]=process.env[k];
 const browser=await chromium.launch({channel:'msedge',headless:true,env});
 try{
 for (const admin of [false,true]) for (const deny of ['schema','load']) {
 const context=await browser.newContext({serviceWorkers:'block'});const requests=[],errors=[];
 await context.route('**/*',r=>{const u=new URL(r.request().url());const p=path.resolve(root,'.'+u.pathname);if(u.origin==='https://settings.test'&&p.startsWith(root+path.sep)&&fs.existsSync(p)&&fs.statSync(p).isFile())return r.fulfill({path:p});requests.push(u.origin);return r.abort();});
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(({admin,deny})=>{window.pywebview={api:new Proxy({}, {get:(_,name)=>async()=>name==='settings_access'?{is_admin:admin}:name==='schema'?(deny==='schema'?{ok:false,error:'Access denied; sign in and retry.'}:[]):name==='load'?{ok:false,error:'Access denied; sign in and retry.'}:{ok:true}})};window.addEventListener('load',()=>window.dispatchEvent(new Event('pywebviewready')));},{admin,deny});
 await page.goto('https://settings.test/settings_web_assets/index.html');
 await page.waitForTimeout(1000);
 assert.deepEqual(errors,[], 'Denied schema must not crash Settings');
 await page.getByText('Access denied; sign in and retry.',{exact:true}).waitFor();
 assert.equal(await page.locator('#save').isEnabled(),false);
 assert.deepEqual(requests,[]);
 await Promise.all([page.waitForEvent('load'),page.getByRole('button',{name:'Retry',exact:true}).click()]);
 await page.getByText('Access denied; sign in and retry.',{exact:true}).waitFor();
 assert.deepEqual(errors,[]);
 assert.equal(await page.locator('[data-nav-group="office"]').count(),0);
 console.log(`PASS ${admin?'admin':'employee'} ${deny} denied: safe layout, disabled Save, working Retry`);
 await context.close();
 }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
