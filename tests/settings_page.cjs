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
  await page.locator('#f-appearance').waitFor({state:'attached'});
  await page.waitForFunction(()=>window.calls.includes('dept_config'));
  await page.waitForFunction(()=>window.SettingsLayout?.ready);
  assert.deepEqual(await page.locator('[data-nav-group]').evaluateAll(nodes=>nodes.map(n=>n.dataset.navGroup)),admin?['you','office','maintenance','advanced/support']:['you']);
  if(admin){
    await page.locator('#employee-access-card form').waitFor({state:'attached'});
    assert.equal(await page.locator('#employee-access-card').isVisible(),false);
    await page.locator('[data-settings-topic="people"]').click();
    assert(await page.locator('#employee-access-card').isVisible());
    assert.equal(await page.locator('#employee-access-card').getAttribute('data-topic'),'people');
    await page.screenshot({path:path.join(out,'admin-people.png'),fullPage:true});
    await page.locator('[data-settings-topic="profile"]').click();
  }else{
    assert.equal(await page.locator('#employee-access-card').count(),0);
    assert.equal(await page.locator('[data-settings-topic="people"]').count(),0);
    await page.evaluate(()=>SettingsLayout.select('people'));
    assert.equal(await page.locator('#employee-access-card').count(),0);
  }
  assert.equal(await page.locator('#open-app-updates').count(),1);
  assert((await page.locator('#settings-health-row').innerText()).includes('Trello writes paused: Yes'));
  assert.equal(await page.locator('#authorize-trello').count(),0);
  assert.equal(await page.locator('[data-setup="trello-auto"]').count(),0);
  await page.screenshot({path:path.join(out,admin?'admin.png':'employee.png'),fullPage:true});
  assert.equal(await page.locator('#connections-grid [data-provider="linguar"]').count(),0);
  assert.equal(await page.locator('#account-sync #sb-sign-out').count(),1);
  assert.equal(await page.locator('#authorize-trello').count(),0);
  assert.equal(await page.locator('#dept-fields [data-dept-group="Folders"]').count(),0);
  await page.locator('[data-settings-topic="folders"]').click();
  assert(await page.locator('#folder-owner').isVisible());
  await page.screenshot({path:path.join(out,admin?'admin-folders.png':'employee-folders.png'),fullPage:true});
  if(admin){
    await page.locator('#d-snapshots_root').fill('C:/Fictional/Override');
    await page.getByRole('button',{name:'Save office folder overrides',exact:true}).click();
    assert.equal(await page.evaluate(()=>callArgs.find(c=>c.name==='save_department').args[1].snapshots_root),'C:/Fictional/Override');
    await page.locator('#f-snapshots_root').fill('C:/Fictional/Base');
    await page.locator('#d-snapshots_root').fill('C:/Fictional/Other');
    await page.locator('#save').click();
    assert.equal(await page.evaluate(()=>callArgs.find(c=>c.name==='save').args[0].snapshots_root),'C:/Fictional/Base');
    await page.locator('[data-settings-topic="advanced"]').click();
    assert.equal(await page.locator('#f-supabase_url').isVisible(),false);
    const before=await page.evaluate(()=>calls.filter(n=>n==='open_config_file').length);
    await page.locator('#open-config-file').click();
    assert(await page.locator('#settings-confirm').isVisible());
    assert((await page.locator('#settings-confirm').innerText()).includes('contains credentials'));
    assert.equal(await page.evaluate(()=>calls.filter(n=>n==='open_config_file').length),before);
    await page.screenshot({path:path.join(out,'advanced-confirm.png'),fullPage:true});
    await page.locator('#settings-confirm-cancel').click();
    assert.equal(await page.evaluate(()=>calls.filter(n=>n==='open_config_file').length),before);
    await page.locator('#open-config-file').click();
    await page.locator('#settings-confirm-continue').click();
    assert.equal(await page.evaluate(()=>calls.filter(n=>n==='open_config_file').length),before+1);
    await page.getByRole('button',{name:'Configure server URL',exact:true}).click();
    await page.locator('#settings-confirm-continue').click();
    assert(await page.locator('#f-supabase_url').isVisible());
    await page.locator('#reload').click();
    await page.waitForFunction(()=>document.getElementById('f-supabase_url')?.hidden===false || !!document.querySelector('#support-fields .support-gate'));
    assert.equal(await page.locator('#open-config-file').count(),1);
    assert.equal(await page.locator('#f-supabase_url').count(),1);
    assert.equal(await page.locator('#f-supabase_url').isVisible(),false);
    await page.locator('#open-config-file').click();
    await page.locator('#settings-confirm-continue').click();
    assert.equal(await page.evaluate(()=>calls.filter(n=>n==='open_config_file').length),before+2);
    await page.locator('[data-settings-topic="appearance"]').click();
    await page.screenshot({path:path.join(out,'appearance.png'),fullPage:true});
  } else {
    await page.evaluate(()=>SettingsLayout.select('advanced'));
    assert.equal(await page.locator('#open-config-file').isVisible(),false);
  }
  // Access can expire after initial successful render. Reload uses the same
  // validation and never installs a denied object as configuration.
  await page.evaluate(()=>{const original=pywebview.api;window.pywebview.api=new Proxy(original,{get:(target,name)=>name==='load'?async()=>({ok:false,error:'Reload access denied'}):target[name]});});
  await page.locator('#reload').click();
  await page.locator('#status').filter({hasText:'Reload access denied'}).waitFor();
  assert.equal(await page.locator('#save').isEnabled(),false);
  assert.equal(await page.getByRole('button',{name:'Retry',exact:true}).count(),1);
  assert.deepEqual(errors,[]); assert.deepEqual(blocked,[]);
  console.log(`${admin?'admin':'employee'}: rendered; no page errors or unexpected requests`);
  await context.close();
 }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
