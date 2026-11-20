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
  const page=await context.newPage(); page.setDefaultTimeout(10000); page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(({admin,schema})=>{
   const results={employee_access_status:{ok:true,is_admin:admin,access_state:'approved'},employee_admin_snapshot:{ok:true,users:[{user_id:'fictional',email:'employee@example.invalid',status:'pending',role:'viewer',departments:[],revision:1}],franchises:[{code:'TEST',label:'Fictional office'}]},schema,load:{appearance:'dark',franchise_name:'Fictional office',supabase_url:'https://example.invalid'},settings_access:{ok:true,is_admin:admin,email:'employee@example.invalid',departments:['TEST']},
    supabase_status:{ok:true,configured:true,signed_in:true,reachable:true,backend:'supabase',user:{email:'employee@example.invalid',display_name:'Test Employee'},offline:{queued:0},trello_writes_paused:true},
    user_connections:{ok:true,connections:[{provider:'linguar',name:'OneLoss',state:'connected',action:'sign_out',action_label:'Sign out'},{provider:'trello',name:'Trello',state:'connected',label:'Trello',detail:'Test connection'},{provider:'companycam',name:'CompanyCam',state:'connected',label:'CompanyCam',detail:'Test connection'}]},
    employee_setup_status:{ok:true,all_done:false,done:5,total:7,is_admin:admin,steps:[{key:'trello',title:'Connect Trello',help:'Connect your work account.',detail:'Test setup',done:false}]},
    my_franchise_folders:{ok:true,departments:[{key:'TEST',label:'Fictional office',active:true,job_root:'C:/Fictional/Jobs',runs_dir:'C:/Fictional/Run',job_connected:true,runs_connected:true}]},get_dept_browsers:{ok:true,browsers:{},departments:[]},admin_users:{ok:true,users:[],franchises:['TEST']},admin_job_profiles:{ok:true,profiles:[],starters:[],franchises:['TEST']},property_managers:{ok:true,records:[]},dept_config:{ok:true,enabled:true,active:'TEST',fields:[{key:'snapshots_root',label:'Snapshots folder',kind:'dir',group:'Folders'},{key:'audit_base',label:'Job root',kind:'dir',group:'Folders'}],departments:[{key:'TEST',label:'Fictional office',overrides:{},is_base:true}],base:{},problems:[]},
    appearance_preferences:{mode:'dark',resolved:'dark'},get_panel_visibility:{},get_tech_roster:{ok:true,entries:[]}};
   window.calls=[]; window.callArgs=[]; window.pywebview={api:new Proxy({}, {get:(_,name)=>async(...args)=>{window.calls.push(String(name));window.callArgs.push({name:String(name),args});return structuredClone(results[name]??{ok:true});}})};
   window.addEventListener('load',()=>window.dispatchEvent(new Event('pywebviewready')));
  },{admin,schema});
  await page.goto('https://settings.test/settings_web_assets/index.html');
  await page.locator('#f-appearance').waitFor();
  await page.waitForFunction(()=>window.calls.includes('dept_config'));
  if(admin && await page.locator('[data-scope-tab="admin"]').isVisible()) await page.locator('[data-scope-tab="admin"]').click();
  await page.screenshot({path:path.join(out,admin?'admin.png':'employee.png'),fullPage:true});
  assert.equal(await page.locator('#connections-grid [data-provider="linguar"]').count(),0);
  assert.equal(await page.locator('#account-sync #sb-sign-out').count(),1);
  assert.equal(await page.locator('#authorize-trello').count(),0);
  assert.equal(await page.locator('#dept-fields [data-dept-group="Folders"]').count(),0);
  await page.evaluate(()=>{showSettingsScope('personal');document.getElementById('folder-owner').open=true;});
  await page.locator('#folder-owner').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,admin?'admin-folders.png':'employee-folders.png'),fullPage:true});
  if(admin){
    await page.locator('#d-snapshots_root').fill('C:/Fictional/Override');
    await page.getByRole('button',{name:'Save office folder overrides',exact:true}).click();
    assert.equal(await page.evaluate(()=>callArgs.find(c=>c.name==='save_department').args[1].snapshots_root),'C:/Fictional/Override');
    await page.locator('#f-snapshots_root').fill('C:/Fictional/Base');
    await page.locator('#d-snapshots_root').fill('C:/Fictional/Other');
    await page.locator('#save').click();
    assert.equal(await page.evaluate(()=>callArgs.find(c=>c.name==='save').args[0].snapshots_root),'C:/Fictional/Base');
  }
  assert.deepEqual(errors,[]); assert.deepEqual(blocked,[]);
  console.log(`${admin?'admin':'employee'}: rendered; no page errors or unexpected requests`);
  await context.close();
 }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
