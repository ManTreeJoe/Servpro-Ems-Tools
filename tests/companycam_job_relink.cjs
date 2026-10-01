const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage();
  await page.setContent('<div id="status-msg"></div>');
  for(const f of ['web_shared/theme.css','web_shared/modal.css','pipeline_web_assets/app.css'])await page.addStyleTag({path:path.resolve(f)});
  await page.evaluate(()=>document.documentElement.dataset.theme='dark');
  for(const f of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/companycam_relink.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(f)});
  await page.evaluate(()=>{window.pins=[];window.fail=true;window.pywebview={api:{companycam_search:async()=>({ok:true,candidates:[{id:'123',name:'Correct project',address:'123 Main',photo_count:29},{id:'gone',name:'Deleted',unavailable:true}]}),companycam_pin:async(...args)=>{pins.push(args);return fail?{ok:false,error:'Save unavailable'}:{ok:true};}}};});
  await page.evaluate(()=>openAuditModal({ok:true,client:'Test job',card_id:'exact-card',audit:{found:true},crm:{},comments:[]}));
  await page.getByRole('button',{name:'CompanyCam',exact:false}).first().click();
  assert.equal(await page.getByRole('button',{name:'Change project…',exact:true}).count(),1,'CompanyCam menu must let users correct a wrong link');
  await page.getByRole('button',{name:'Change project…',exact:true}).click();
  await page.waitForSelector('[data-cc-project="123"]');
  assert.equal(await page.locator('[data-cc-project="123"]').evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2));}),true,'Picker must be above job workspace');
  assert.equal(await page.locator('[data-cc-project="gone"]').isDisabled(),true);
  page.once('dialog',d=>d.dismiss());await page.locator('[data-cc-project="123"]').click();
  assert.equal(await page.evaluate(()=>pins.length),0);
  page.once('dialog',d=>d.accept());await page.locator('[data-cc-project="123"]').click();
  assert.match(await page.locator('[data-cc-message]').textContent(),/Save unavailable/);
  assert.equal(await page.locator('[data-cc-project="123"]').isEnabled(),true);
  await page.screenshot({path:require('os').tmpdir()+'/companycam-relink.png'});
  await page.evaluate(()=>fail=false);
  page.once('dialog',d=>d.accept());await page.locator('[data-cc-project="123"]').click();
  assert.deepEqual(await page.evaluate(()=>pins),[['Test job','123','exact-card'],['Test job','123','exact-card']]);
  assert.equal(await page.locator('[data-cc-results]').count(),0);
  console.log('PASS CompanyCam relink control');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
