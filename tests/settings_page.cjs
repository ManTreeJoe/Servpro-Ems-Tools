// Real Settings HTML; synthetic API and local assets only. No app modules/providers.
const {chromium}=require('playwright');
const fs=require('node:fs'); const path=require('node:path'); const assert=require('node:assert/strict');
const root=path.resolve(process.env.SETTINGS_SOURCE || path.join(__dirname,'..'));
const out=path.resolve(process.env.SETTINGS_SHOTS || path.join(root,'test-results/settings'));
const source=fs.readFileSync(path.join(root,'settings_web.py'),'utf8');
const personal=new Set([...source.split('_PERSONAL_FIELDS = {')[1].split('\n}')[0].matchAll(/"([a-z_]+)"/g)].map(m=>m[1]));
const groups=Object.fromEntries([...source.split('_FIELD_GROUPS = {')[1].split('\n}')[0].matchAll(/"([a-z_]+)": "([^"]+)"/g)].map(m=>[m[1],m[2]]));
const schema=[...source.split('FIELDS = [')[1].split('\n]')[0].matchAll(/\("([a-z_]+)",\s*"([^"]+)",\s*"([^"]+)"/g)].map(m=>({key:m[1],label:m[2],kind:m[3],scope:personal.has(m[1])?'personal':'admin',group:groups[m[1]],managed_connection:m[1]==='trello_token',choices:m[1]==='appearance'?['system','light','dark']:['auto','1.0','1.25']}));
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const env={}; for(const key of ['SystemRoot','WINDIR','TEMP','TMP','LOCALAPPDATA','PROGRAMFILES','PROGRAMFILES(X86)','PATH']) if(process.env[key]) env[key]=process.env[key];
 const browser=await chromium.launch({channel:'msedge',headless:true,env});
 try{
 for(const admin of [false,true]){
  const context=await browser.newContext({serviceWorkers:'block',viewport:{width:1280,height:960}});
  const blocked=[]; const errors=[];
  await context.route('**/*',async route=>{
   const url=new URL(route.request().url()); const rel=decodeURIComponent(url.pathname).replace(/^\//,'');
   if(url.origin==='https://settings.test' && /^(settings_web_assets|web_shared)\/[\w./-]+\.(html|css|js|svg|png|woff2?)$/.test(rel)){
    const file=path.resolve(root,rel); if(file.startsWith(root+path.sep) && fs.existsSync(file)) return route.fulfill({path:file});
   }
   blocked.push(url.href); return route.abort();
  });
  const page=await context.newPage(); page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(({admin,schema})=>{
   const results={schema,load:{appearance:'dark',franchise_name:'Fictional office',supabase_url:'https://example.invalid'},settings_access:{ok:true,is_admin:admin,email:'employee@example.invalid',departments:['TEST']},
    supabase_status:{ok:true,configured:true,signed_in:true,reachable:true,backend:'supabase',user:{email:'employee@example.invalid',display_name:'Test Employee'},offline:{queued:0},trello_writes_paused:true},
    user_connections:{ok:true,connections:[{provider:'trello',name:'Trello',state:'connected',label:'Trello',detail:'Test connection'},{provider:'companycam',name:'CompanyCam',state:'connected',label:'CompanyCam',detail:'Test connection'}]},
    employee_setup_status:{ok:true,all_done:false,done:5,total:7,is_admin:admin,steps:[{key:'trello',title:'Connect Trello',help:'Connect your work account.',detail:'Test setup',done:false}]},
    my_franchise_folders:{ok:true,departments:[]},get_dept_browsers:{ok:true,browsers:{},departments:[]},admin_users:{ok:true,users:[],franchises:['TEST']},admin_job_profiles:{ok:true,profiles:[],starters:[],franchises:['TEST']},property_managers:{ok:true,records:[]},dept_config:{ok:true,enabled:false,fields:[],departments:[],base:{},problems:[]},
    appearance_preferences:{mode:'dark',resolved:'dark'},get_panel_visibility:{},get_tech_roster:{ok:true,entries:[]}};
   window.calls=[]; window.pywebview={api:new Proxy({}, {get:(_,name)=>async(...args)=>{window.calls.push(String(name));return structuredClone(results[name]??{ok:true});}})};
   window.addEventListener('load',()=>window.dispatchEvent(new Event('pywebviewready')));
  },{admin,schema});
  await page.goto('https://settings.test/settings_web_assets/index.html');
  await page.locator('#f-appearance').waitFor();
  await page.waitForFunction(()=>window.calls.includes('dept_config'));
  if(admin && await page.locator('[data-scope-tab="admin"]').isVisible()) await page.locator('[data-scope-tab="admin"]').click();
  await page.screenshot({path:path.join(out,admin?'admin.png':'employee.png'),fullPage:true});
  assert.deepEqual(errors,[]); assert.deepEqual(blocked,[]);
  console.log(`${admin?'admin':'employee'}: rendered; no page errors or unexpected requests`);
  await context.close();
 }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
