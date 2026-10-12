const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.setContent('<html><body></body></html>');
  await page.addStyleTag({path:path.resolve('web_shared/theme.css')});
  await page.addStyleTag({path:path.resolve('analytics_web_assets/app.css')});
  await page.addStyleTag({path:path.resolve('analytics_web_assets/logs_review_workspace.css')});
  await page.evaluate(()=>{
   window.writes=0;window.saved=null;
   const card={id:'card1',name:'Test job <safe>',desc:'Initial inspection recorded'};
   const operation={id:'op1',card_id:'card1',name:card.name,destination_name:'JUNE 2026 BILLED',comment:'Audited on test date\nExplicit billed evidence',status:'preview'};
   window.pywebview={api:{
    open_popout:async(tool,context)=>{window.openedPopout={tool,context};return {ok:true};},
    logs_export_excel:async(start,end)=>{window.exportPeriod=[start,end];return {ok:true,count:1,path:'weekly-copy.xlsx'};},
    logs_ar_candidates:async()=>({ok:true,searched_count:1,candidates:[{card:{id:'ar1',name:'AR test'},reason:'Possible match'}]}),
    logs_ar_review:async(id,ar,confirmed)=>{window.arLinked=confirmed;return {ok:true,evidence:{card:{id:'ar1',name:'AR test',desc:'Claim ABC'},comments:[{date:'2026-07-01',author:'Tonia',text:'Billed on 7/1/26'}]},comparison:{conflicts:[{}],summary:'Conflicting billing evidence'}};},
    logs_queue:async()=>({ok:true,cards:[card],drafts:{},operations:[{...operation,id:'old-review',status:'superseded'}]}),
    logs_inspect:async()=>({ok:true,suggestions:{ems_estimator:{value:'Kim',conflict:false,sources:[{id:'description',title:'Card description',text:'EMS estimator: Kim'}]}},evidence:{card,revision:'rev1',comments:[{text:'Billed June 10',date:'2026-06-10',author:'Test'}],checklists:[]},lanes:[{id:'june',name:'JUNE 2026 BILLED'}]}),
    logs_save:async(id,rev,fields)=>{window.saved=fields;return {ok:true,draft:{fields}};},
    logs_preview:async()=>window.saved?.scope?({ok:true,operation}):({ok:false,error:'Choose review period and audited scope.'}),
    logs_publish:async(id,confirmed)=>{if(confirmed!==true)throw Error('Missing confirmation');window.writes++;return {ok:true,operation:{...operation,status:'done'}};}
   }};
  });
  await page.addScriptTag({path:path.resolve('analytics_web_assets/audit_field_controls.js')});
  await page.addScriptTag({path:path.resolve('analytics_web_assets/logs_review_workspace.js')});
  await page.addScriptTag({path:path.resolve('web_shared/popout_menu.js')});
  await page.addScriptTag({path:path.resolve('analytics_web_assets/logs_audit.js')});
  await page.evaluate(()=>LogsAuditUI.open({start:'2026-09-14',end:'2026-09-20'}));
  assert.match(await page.locator('[data-history]').textContent(),/superseded/,'replaced audit remains in recovery history');
  assert.equal(await page.locator('[data-retry="old-review"]').count(),0,'replaced audit cannot be retried');
  assert.equal(await page.locator('.logs-review-workspace').isVisible(),true,'opens directly into first job');
  assert.equal(await page.getByRole('button',{name:'Audit job',exact:true}).count(),0);
  await page.locator('.logs-more>summary').click();
  await page.getByRole('button',{name:'Export weekly Excel copy'}).click();
  assert.deepEqual(await page.evaluate(()=>window.exportPeriod),['2026-09-14','2026-09-20']);
  await page.locator('.logs-more>summary').click();
  assert.equal(await page.locator('.logs-review-queue').isVisible(),true);
  assert.equal(await page.locator('.logs-review-comments').isVisible(),true);
  assert.match(await page.locator('.logs-review-comments').innerText(),/Billed June 10/);
  await page.evaluate(()=>{window.jobMessages=[];window.postMessage=data=>{if(data?.type==='linguar-open-job')jobMessages.push(data);};});
  await page.locator('[name=ems_estimator]').fill('Draft survives overlay');
  assert.equal(await page.getByLabel('Coordinator who sent the initial note',{exact:true}).isVisible(),true);
  await page.locator('[data-open]').click();
  await page.waitForFunction(()=>jobMessages.length===1);
  assert.equal(await page.evaluate(()=>jobMessages[0].cardId),'card1');
  assert.equal(await page.locator('[name=ems_estimator]').inputValue(),'Draft survives overlay');
  await page.locator('[data-open]').click({button:'right'});
  assert.equal(await page.locator('#logs-audit #oneloss-popout-menu').isVisible(),true);
  await page.screenshot({path:path.join(require('node:os').tmpdir(),'logs-popout-menu.png')});
  await page.getByRole('menuitem',{name:'Open in new window'}).click();
  assert.deepEqual(await page.evaluate(()=>window.openedPopout),{tool:'pipeline',context:{cardId:'card1',client:'Test job <safe>'}});
  assert.equal(await page.locator('[name=ems_estimator]').inputValue(),'Draft survives overlay');
  await page.locator('[data-open]').click({button:'right'});
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#oneloss-popout-menu').count(),0);
  assert.equal(await page.locator('#logs-audit').isVisible(),true);
  await page.locator('[name=ems_estimator]').fill('Kim');
  assert.equal(await page.locator('[name=ems_estimator]').inputValue(),'Kim');
  assert.equal(await page.locator('[name=scope]').isVisible(),false);
  assert.equal(await page.getByLabel('Job Date (received)',{exact:true}).isVisible(),true);
  await page.getByText('Initial note timing evidence',{exact:true}).click();
  await page.getByRole('tab',{name:'Field',exact:true}).click();
  await page.getByLabel('inspection_at date',{exact:true}).fill('09/17/2026');
  await page.getByLabel('inspection_at time',{exact:true}).fill('08:00');
  await page.getByLabel('field_note_posted_at date',{exact:true}).fill('09/17/2026');
  await page.getByLabel('field_note_posted_at time',{exact:true}).fill('10:00');
  await page.getByRole('tab',{name:'Front & job',exact:true}).click();
  await page.getByLabel('initial_note_sent_at date',{exact:true}).fill('09/17/2026');
  await page.getByLabel('initial_note_sent_at time',{exact:true}).fill('11:15');
  assert.equal(await page.locator('[name=initial_note]').inputValue(),'No');
  assert.match(await page.locator('[name=initial_note]').locator('..').innerText(),/Field note → coordinator: 1 hour 15 minutes · limit 1 hour/);
  await page.getByLabel('initial_note_sent_at time',{exact:true}).fill('10:45');
  assert.equal(await page.locator('[name=initial_note]').inputValue(),'Yes','coordinator is on time despite earlier inspection');
  await page.getByLabel('initial_note_sent_at date',{exact:true}).scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(require('node:os').tmpdir(),'logs-guided-fields.png')});
  await page.locator('.audit-source summary').click();
  assert.match(await page.locator('.audit-source pre').innerText(),/EMS estimator: Kim/);
  await page.locator('[name=ems_estimator]').fill('Test estimator');
  await page.locator('[data-save]').click();
  await page.waitForFunction(()=>window.saved);
  assert.equal(await page.evaluate(()=>writes),0);
  assert.equal(await page.locator('[name=period_start]').inputValue(),'2026-09-14');
  const closeWarnings=[];
  page.on('dialog',async dialog=>{closeWarnings.push(dialog.message());await dialog.dismiss();});
  await page.locator('[data-close]').click();
  assert.deepEqual(closeWarnings,[],'a saved audit draft closes without an unsaved warning');
  assert.equal(await page.locator('#logs-audit').evaluate(el=>el.open),false);
  assert.equal(await page.locator('#logs-audit').isVisible(),false);
  await page.evaluate(()=>LogsAuditUI.open({start:'2026-09-14',end:'2026-09-20'}));
  assert.equal(await page.locator('.logs-review-workspace').isVisible(),true);
  await page.locator('[name=ems_estimator]').fill('Unsaved estimator');
  await page.locator('[data-close]').click();
  assert.equal(closeWarnings.length,1,'a changed audit draft warns before closing');
  assert.equal(await page.locator('#logs-audit').evaluate(el=>el.open),true);
  assert.equal(await page.locator('[name=ems_estimator]').inputValue(),'Unsaved estimator');
  await page.locator('.logs-more>summary').click();
  await page.locator('[data-refresh]').click();
  assert.equal(await page.locator('[name=ems_estimator]').inputValue(),'Unsaved estimator','cancelled refresh preserves draft');
  await page.locator('.logs-more>summary').click();
  await page.locator('[data-save]').click();
  await page.waitForFunction(()=>window.saved.ems_estimator==='Unsaved estimator');
  await page.locator('#logs-audit').evaluate(el=>el.scrollTop=0);
  await page.screenshot({path:path.join(require('node:os').tmpdir(),'linguar-logs-form.png'),fullPage:true});
  for(const theme of ['light','dark']){
   await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
   const contrast=await page.evaluate(()=>{
    const lum=rgb=>{const c=rgb.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});return .2126*c[0]+.7152*c[1]+.0722*c[2];};
    const bg=lum(getComputedStyle(document.querySelector('#logs-audit')).backgroundColor);
    return Array.from(document.querySelectorAll('#logs-audit label,#logs-audit .audit-provenance,#logs-audit summary')).filter(e=>e.checkVisibility()).map(e=>{const fg=lum(getComputedStyle(e).color);return (Math.max(bg,fg)+.05)/(Math.min(bg,fg)+.05);});
   });
   assert.ok(contrast.every(r=>r>=4.5),theme+' text contrast meets 4.5:1');
  }
  await page.screenshot({path:path.join(require('node:os').tmpdir(),'linguar-logs-dark.png'),fullPage:true});
  assert.deepEqual(await page.getByRole('tab').allTextContents(),['Front & job','Field','Estimating','Billing & finish']);
  await page.getByRole('tab',{name:'Field',exact:true}).click();
  await page.getByLabel('EMS work started',{exact:true}).fill('06/01/2026');
  await page.getByLabel('EMS work completed',{exact:true}).fill('06/06/2026');
  assert.equal(await page.locator('[name=ems_completed]').inputValue(),'2026-06-06');
  await page.getByLabel('EMS work completed',{exact:true}).fill('02/30/2026');
  await page.locator('[data-save]').click();
  assert.match(await page.locator('[data-status]').innerText(),/Check the highlighted date/);
  await page.getByLabel('EMS work completed',{exact:true}).fill('06/06/2026');
  await page.screenshot({path:path.join(require('node:os').tmpdir(),'logs-field-dates.png')});
  await page.getByRole('tab',{name:'Estimating',exact:true}).click();
  await page.getByLabel('Ready for billing',{exact:true}).first().fill('06/07/2026');
  await page.getByRole('tab',{name:'Billing & finish',exact:true}).click();
  await page.getByLabel('EMS billing completed',{exact:true}).fill('06/08/2026');
  assert.equal(await page.locator('[data-ems-days]').innerText(),'7 days from start to billed');
  await page.getByRole('tab',{name:'Field',exact:true}).click();
  await page.getByLabel('EMS work started',{exact:true}).fill('');
  assert.match(await page.locator('[data-ems-days]').innerText(),/unknown/);
  assert.equal(await page.locator('[name=job_date]').isVisible(),false);
  await page.getByRole('tab',{name:'Billing & finish',exact:true}).click();
  assert.equal(await page.getByLabel('Division for filing',{exact:true}).isVisible(),true,'unrecognized source division has a finish-only routing choice');
  await page.locator('[data-preview]').click();
  assert.match(await page.locator('[data-status]').innerText(),/Choose.*division.*filing/i);
  assert.equal(await page.evaluate(()=>writes),0,'missing routing never publishes');
  await page.getByLabel('Division for filing',{exact:true}).selectOption('EMS + Contents');
  await page.locator('[data-find-ar]').click();
  await page.getByRole('button',{name:'AR test · Possible match'}).click();
  assert.equal(await page.evaluate(()=>arLinked),false,'inspection does not confirm link');
  await page.getByRole('button',{name:'Confirm this AR card (same job, division and unit)'}).click();
  await page.waitForFunction(()=>window.arLinked===true);
  assert.equal(await page.locator('[name=decision]').inputValue(),'questions');
  await page.locator('#logs-audit').evaluate(el=>el.scrollTop=0);
  await page.screenshot({path:path.join(require('node:os').tmpdir(),'linguar-logs-ar.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.querySelector('#logs-audit').scrollWidth<=document.querySelector('#logs-audit').clientWidth),true,'no dialog horizontal overflow');
  await page.locator('[data-preview]').click();
  await page.locator('[data-publish]').waitFor();
  assert.equal(await page.evaluate(()=>window.saved.scope),'EMS + Contents','explicit routing reaches server validation');
  assert.equal(await page.evaluate(()=>writes),0);
  assert.match(await page.locator('#logs-audit pre').innerText(),/Explicit billed evidence/);
  await page.locator('[data-publish]').click();
  await page.waitForFunction(()=>window.writes===1);
  await page.waitForFunction(()=>document.querySelector('[data-publish]').disabled);
  await page.evaluate(()=>{
   window.pywebview.api.logs_queue=async()=>({ok:true,cards:[{id:'batch1',name:'Batch one'},{id:'batch2',name:'Batch two'}],drafts:{batch1:{fields:{period_start:'2026-09-14',period_end:'2026-09-20'}},batch2:{fields:{period_start:'2026-09-14',period_end:'2026-09-20'}}},operations:[]});
   window.pywebview.api.logs_preview=async id=>({ok:true,operation:{id,card_id:id,name:id,comment:'Review '+id,destination_name:'TO BE PRESERVED',decision:'hold',status:'preview'}});
   window.pywebview.api.logs_publish=async(id,confirmed)=>{if(!confirmed)throw Error('No approval');if(id==='batch2')return {ok:false,error:'Evidence changed'};window.writes++;return {ok:true,operation:{id,status:'done'}};};
  });
  await page.locator('[data-queue]').click();
  await page.locator('.logs-more>summary').click();
  await page.getByRole('button',{name:'Review saved drafts for this period'}).click();
  await page.locator('[data-batch-index="0"]').check();
  await page.locator('[data-batch-index="1"]').check();
  assert.equal(await page.evaluate(()=>writes),1,'batch preview does not publish');
  await page.locator('[data-confirm-batch]').click();
  await page.waitForFunction(()=>document.querySelector('[data-result="1"]').textContent==='Evidence changed');
  assert.equal(await page.evaluate(()=>writes),2);
  assert.equal(await page.locator('[data-batch-index="0"]').isDisabled(),true);
  await page.screenshot({path:path.join(require('node:os').tmpdir(),'linguar-logs-batch.png'),fullPage:true});
  await page.evaluate(()=>{window.pywebview.api.logs_queue=async()=>({ok:true,cards:[],drafts:{},operations:[]});});
  await page.locator('[data-queue]').click();
  assert.match(await page.locator('[data-body]').innerText(),/No jobs waiting for audit/);
  await page.evaluate(()=>{
   window.pywebview.api.logs_queue=async()=>({ok:true,cards:[{id:'broken',name:'Failed evidence job'}],drafts:{},operations:[]});
   window.pywebview.api.logs_inspect=async()=>({ok:false,error:'Evidence unavailable'});
  });
  await page.locator('.logs-more>summary').click();
  await page.locator('[data-refresh]').click();
  assert.match(await page.locator('[data-status]').innerText(),/Evidence unavailable/);
  assert.equal(await page.locator('[data-load-recovery] [data-card="broken"]').isVisible(),true);
  assert.deepEqual(errors,[]);
  console.log('PASS: draft, preview, explicit publication, escaping, narrow layout');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
