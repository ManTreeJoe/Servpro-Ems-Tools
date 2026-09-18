const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.setContent('<html><body></body></html>');
  await page.addStyleTag({path:path.resolve('analytics_web_assets/app.css')});
  await page.evaluate(()=>{
   window.writes=0;window.saved=null;
   const card={id:'card1',name:'Test job <safe>',desc:'Initial inspection recorded'};
   const operation={id:'op1',card_id:'card1',name:card.name,destination_name:'JUNE 2026 BILLED',comment:'Audited on test date\nExplicit billed evidence',status:'preview'};
   window.pywebview={api:{
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
  await page.addScriptTag({path:path.resolve('analytics_web_assets/logs_audit.js')});
  await page.evaluate(()=>LogsAuditUI.open({start:'2026-09-14',end:'2026-09-20'}));
  assert.match(await page.locator('[data-history]').textContent(),/superseded/,'replaced audit remains in recovery history');
  assert.equal(await page.locator('[data-retry="old-review"]').count(),0,'replaced audit cannot be retried');
  await page.getByRole('button',{name:'Export weekly Excel copy'}).click();
  assert.deepEqual(await page.evaluate(()=>window.exportPeriod),['2026-09-14','2026-09-20']);
  await page.locator('[data-card]').click();
  assert.equal(await page.locator('[name=ems_estimator]').inputValue(),'Kim');
  assert.equal(await page.locator('[name=scope]').isVisible(),false);
  assert.equal(await page.getByLabel('Job Date (received)',{exact:true}).isVisible(),true);
  await page.getByText('Initial note timing evidence',{exact:true}).click();
  await page.locator('[name=inspection_completed_at]').fill('2026-09-17T10:00:00-07:00');
  await page.locator('[name=initial_note_sent_at]').fill('2026-09-17T11:15:00-07:00');
  assert.equal(await page.locator('[name=initial_note]').inputValue(),'No');
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
  await page.evaluate(()=>LogsAuditUI.open({start:'2026-09-14',end:'2026-09-20'}));
  await page.locator('[data-card]').click();
  await page.locator('[name=ems_estimator]').fill('Unsaved estimator');
  await page.locator('[data-close]').click();
  assert.equal(closeWarnings.length,1,'a changed audit draft warns before closing');
  assert.equal(await page.locator('#logs-audit').evaluate(el=>el.open),true);
  assert.equal(await page.locator('[name=ems_estimator]').inputValue(),'Unsaved estimator');
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
  await page.getByRole('tab',{name:'Estimating',exact:true}).click();
  assert.equal(await page.locator('[name=ems_billed]').isVisible(),true);
  await page.locator('[name=ems_start]').fill('2026-06-01');
  await page.locator('[name=ems_ready]').fill('2026-06-07');
  await page.locator('[name=ems_billed]').fill('2026-06-08');
  assert.equal(await page.locator('[data-ems-days]').innerText(),'7 days from start to billed');
  await page.locator('[name=ems_start]').fill('');
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
  await page.getByRole('button',{name:'Review saved drafts for this period'}).click();
  await page.locator('[data-batch-index="0"]').check();
  await page.locator('[data-batch-index="1"]').check();
  assert.equal(await page.evaluate(()=>writes),1,'batch preview does not publish');
  await page.locator('[data-confirm-batch]').click();
  await page.waitForFunction(()=>document.querySelector('[data-result="1"]').textContent==='Evidence changed');
  assert.equal(await page.evaluate(()=>writes),2);
  assert.equal(await page.locator('[data-batch-index="0"]').isDisabled(),true);
  await page.screenshot({path:path.join(require('node:os').tmpdir(),'linguar-logs-batch.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: draft, preview, explicit publication, escaping, narrow layout');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
