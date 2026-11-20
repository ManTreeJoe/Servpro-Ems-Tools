const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(process.env.SETTINGS_SOURCE||path.join(__dirname,'..'));
 const env={};for(const k of ['SystemRoot','WINDIR','TEMP','TMP','LOCALAPPDATA','PROGRAMFILES','PROGRAMFILES(X86)','PATH'])if(process.env[k])env[k]=process.env[k];
 const browser=await chromium.launch({channel:'msedge',headless:true,env});
 try{
 const context=await browser.newContext({serviceWorkers:'block'});const requests=[],errors=[];
 await context.route('**/*',r=>{const u=new URL(r.request().url());const p=path.resolve(root,'.'+u.pathname);if(u.origin==='https://settings.test'&&p.startsWith(root+path.sep)&&fs.existsSync(p)&&fs.statSync(p).isFile())return r.fulfill({path:p});requests.push(u.origin);return r.abort();});
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{window.pywebview={api:new Proxy({}, {get:(_,name)=>async()=>name==='settings_access'?{is_admin:false}:name==='schema'?{ok:false,error:'Sign in with Microsoft and wait for administrator approval.'}:name==='load'?{ok:false,error:'Access denied'}:{ok:true}})};window.addEventListener('load',()=>window.dispatchEvent(new Event('pywebviewready')));});
 await page.goto('https://settings.test/settings_web_assets/index.html');
 await page.waitForTimeout(1000);
 assert.deepEqual(errors,[], 'Denied schema must not crash Settings');
 await page.getByText('Sign in with Microsoft and wait for administrator approval.',{exact:true}).waitFor();
 assert.equal(await page.locator('#save').isEnabled(),false);
 assert.deepEqual(requests,[]);
 console.log('PASS denied schema shows actionable error; Save disabled; no page errors or provider requests');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
