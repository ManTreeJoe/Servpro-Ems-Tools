const {chromium}=require('playwright');
const path=require('node:path'),fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1000,height:780}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.setContent('<button id="open">Members</button>');
  for(const f of ['web_shared/theme.css','pipeline_web_assets/job_members.css'])await page.addStyleTag({path:path.resolve(f)});
  await page.evaluate(()=>{
   document.documentElement.dataset.theme='dark';window.calls=[];window.fail=false;
   window.pywebview={api:{personal_job_members:async()=>({ok:true,people:[{id:'sam',name:'Sam Example',username:'ol.sam.abcdef12',member:false},{id:'jo',name:'Jo Manager',username:'ol.jo.abc12345',member:true}],muted:false}),
    set_personal_job_member:async(...args)=>{calls.push(args);return {ok:!fail,error:'Not confirmed. Refresh and retry.'};},mute_personal_job:async()=>({ok:true})}};
  });
  await page.addScriptTag({path:path.resolve('pipeline_web_assets/job_members.js')});
  await page.evaluate(()=>openJobMembers('exact-card'));
  await page.getByLabel('Sam Example').check();assert.deepEqual(await page.evaluate(()=>calls[0]),['exact-card','sam',true]);
  await page.evaluate(()=>fail=true);await page.getByLabel('Jo Manager').click();await page.getByText('Not confirmed. Refresh and retry.').waitFor();assert(await page.getByLabel('Jo Manager').isChecked());
  await page.screenshot({path:path.join(process.env.TEMP,'oneloss-job-members.png')});
  await page.setViewportSize({width:390,height:740});assert(await page.locator('dialog').evaluate(e=>e.getBoundingClientRect().right<=innerWidth));
  await page.keyboard.press('Escape');await page.locator('dialog').waitFor({state:'detached'});
  const html=fs.readFileSync('notifications_web_assets/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'').replace(/<link\b[^>]*>/gi,'');
  await page.setViewportSize({width:1000,height:780});await page.setContent(html);
  for(const f of ['web_shared/theme.css','notifications_web_assets/personal.css'])await page.addStyleTag({path:path.resolve(f)});
  await page.evaluate(()=>{
   document.documentElement.dataset.theme='dark';window.calls=[];window.fail=false;window.muted=false;window.posts=[];
   window.addEventListener('message',e=>posts.push(e.data));
   window.pywebview={api:{personal_inbox:async(filter,unread)=>{calls.push(['inbox',filter,unread]);return fail?{ok:false,error:'Connection unavailable'}:{ok:true,items:[{id:'1',kind:'mention',client:'Example restoration job',body:'@ol.sam.abcdef12 Please review the photo report.',actor:'Jo Manager',card_id:'exact-card',division:'Contents',created_at:'2026-09-29T18:00:00Z',muted}],pending_delivery:0};},personal_read:async(...a)=>{calls.push(['read',...a]);return {ok:true};},personal_mute:async(card,value)=>{muted=value;return {ok:true};}}};
  });
  await page.evaluate(()=>{pywebview.api.notification_job=async card=>({ok:true,client:'Example restoration job',cardId:card,division:'Contents'});});
  await page.addScriptTag({path:path.resolve('notifications_web_assets/personal.js')});await page.evaluate(()=>dispatchEvent(new Event('pywebviewready')));
  await page.getByRole('button',{name:'Open job',exact:true}).click();await page.waitForFunction(()=>posts.length>0);assert.equal(await page.evaluate(()=>posts[0].cardId),'exact-card');
  await page.getByRole('button',{name:'Mark unread',exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>calls.filter(c=>c[0]==='read'&&c[2]===true).length),1,'Opening marks personal notification read');
  assert.equal(await page.locator('#personal-unread').isChecked(),false,'Read items remain visible by default');
  assert.equal(await page.locator('.personal-notification').count(),1);
  await page.locator('#personal-unread').check();
  assert.equal(await page.locator('.personal-notification').count(),0);
  await page.locator('#personal-unread').uncheck();
  assert.equal(await page.locator('.personal-notification').count(),1,'Clearing unread filter restores saved message without reload');
  await page.getByRole('button',{name:'Mark unread',exact:true}).click();
  await page.locator('#personal-unread').check();
  await page.getByRole('button',{name:'Mark read',exact:true}).click();
  assert.equal(await page.locator('.personal-notification').count(),0);
  await page.locator('#personal-unread').uncheck();
  assert.equal(await page.locator('.personal-notification').count(),1,'Reading does not discard the loaded record');
  await page.getByRole('button',{name:'Mute job',exact:true}).click();await page.getByRole('button',{name:'Unmute job',exact:true}).waitFor();
  await page.locator('#personal-filter').selectOption('mentions');await page.waitForFunction(()=>calls.some(c=>c[0]==='inbox'&&c[1]==='mentions'));
  await page.screenshot({path:path.join(process.env.TEMP,'oneloss-personal-inbox.png')});
  await page.setViewportSize({width:390,height:740});assert(await page.locator('#personal-panel').evaluate(e=>e.scrollWidth<=innerWidth));
  await page.screenshot({path:path.join(process.env.TEMP,'oneloss-personal-inbox-narrow.png')});
  await page.evaluate(()=>fail=true);await page.locator('#personal-refresh').click();await page.getByText('Connection unavailable').waitFor();assert.equal(await page.locator('.personal-notification').count(),1);
  assert.deepEqual(errors,[]);console.log('PASS: membership success/failure, native inbox, exact job link, read/unread, mute, filters, error preservation and narrow layout');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
