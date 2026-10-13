const {chromium}=require('playwright'),assert=require('assert/strict'),path=require('path');
const {execFileSync}=require('child_process');
(async()=>{
 const forms=JSON.parse(execFileSync('C:/Users/NathanBupte/AppData/Local/Programs/Python/Python312/python.exe',['-c',"import json,job_forms; print(json.dumps(job_forms.catalog({'customer_name':'Sample Customer','date_of_loss':'10/11/2026'})))"],{encoding:'utf8'}));
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1000,height:900}});
  await page.setContent('<body style="background:#17191b"></body>');
  for(const file of ['job_members.css','job_forms.css']) await page.addStyleTag({path:path.resolve('pipeline_web_assets',file)});
  await page.addScriptTag({path:path.resolve('pipeline_web_assets/job_forms.js')});
  assert.equal(await page.evaluate(()=>jobFormAction('ATP','present')),'');
  assert.equal(await page.evaluate(()=>jobFormAction('ATR','missing')),'');
  assert.match(await page.evaluate(()=>jobFormAction('Customer Info Form','missing')),/data-prepare-form="cif"/);
  await page.evaluate(forms=>{window.calls=[];window.pywebview={api:{job_forms_load:async()=>({ok:true,forms}),job_forms_export:async(...args)=>{calls.push(args);return {ok:true,cancelled:true};}}};openJobForms('Test','card');},forms);
  await page.getByLabel('Customer / insured name').fill('Edited Customer');
  await page.locator('[data-form]').selectOption('cer');
  await page.locator('[data-form]').selectOption('atp');
  await page.evaluate(()=>{pywebview.api.job_forms_preview=async()=>({ok:true,pages:['iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jK1kAAAAASUVORK5CYII=']});});
  await page.locator('[data-preview-button]').click();
  assert.equal(await page.locator('[data-preview] img').count(),1);
  await page.getByLabel('Customer / insured name').fill('Edited Customer');
  assert(await page.locator('[data-preview]').isHidden());
  assert.equal(await page.getByLabel('Customer / insured name').inputValue(),'Edited Customer');
  await page.locator('[data-save]').click();
  assert.match(await page.locator('[data-status]').innerText(),/cancelled/);
  assert.equal(await page.evaluate(()=>calls[0][1].InsuredName),'Edited Customer');
  await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-forms-ui.png')});
  await page.setViewportSize({width:390,height:800});
  assert(await page.evaluate(()=>document.querySelector('dialog').scrollWidth<=document.querySelector('dialog').clientWidth));
  await page.locator('[data-close]').click();
  await page.evaluate(()=>{pywebview.api.job_forms_load=async()=>({ok:false,error:'Unavailable'});openJobForms('Test','card');});
  await page.getByText('Unavailable',{exact:true}).waitFor();
  assert(await page.locator('[data-save]').isDisabled());
  console.log('PASS forms: edits, selection retention, export/cancel, responsive layout, load failure');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
