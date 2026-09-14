const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  const html=fs.readFileSync('run_doc_editor_web_assets/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace(/<link\b[^>]*>/g,'');
  await page.setContent(html);
  await page.evaluate(()=>document.documentElement.dataset.theme='light');
  for(const file of ['web_shared/theme.css','run_doc_editor_web_assets/app.css','run_doc_editor_web_assets/schedule_visits.css']) await page.addStyleTag({path:path.resolve(file)});
  for(const file of ['schedule_fields.js','visit_controls.js','app.js']) await page.addScriptTag({path:path.resolve('run_doc_editor_web_assets',file)});
  await page.evaluate(()=>{
   window.PanelState={set(){}};
   window.pywebview={api:{get_crew_roster:async()=>({ok:true,entries:[{name:'Sam',aliases:['S']},{name:'Alex',aliases:['A']}]})}};
   state.model={editable:true,date_iso:'2026-09-11',sections:{work:[{id:'test',text:'Test property | 100 Main St | Monitor | 12–3 PM | Sam | Call first',struck:false}],upcoming:[]},section_order:['work','upcoming']};
   document.querySelector('#run-board').classList.remove('hidden');
   document.querySelector('#day-title').textContent='Friday schedule — test data';
   renderWeekStrip();renderRows();
  });
  await page.locator('.visit-summary').click();
  assert.equal(await page.locator('#field-time').inputValue(),'12–3 PM');
  await page.locator('#field-task').fill('');
  await page.evaluate(()=>applyComposer());
  await page.locator('.visit-summary').click();
  assert.equal(await page.locator('#field-time').inputValue(),'12–3 PM');
  assert.equal(await page.locator('#field-crew').inputValue(),'Sam');
  await page.locator('#field-crew').fill('Sam, Outside vendor');
  await page.getByText('Select crew',{exact:true}).click();
  await page.getByLabel('Alex',{exact:true}).check();
  assert.equal(await page.locator('#field-crew').inputValue(),'Sam, Outside vendor, Alex');
  await page.getByLabel('Sam',{exact:true}).uncheck();
  assert.equal(await page.locator('#field-crew').inputValue(),'Outside vendor, Alex');
  await page.getByText('Choose arrival window',{exact:true}).click();
  await page.locator('#arrival-from').fill('12:00');await page.locator('#arrival-through').fill('15:00');
  await page.getByText('Use window',{exact:true}).click();
  assert.equal(await page.locator('#field-time').inputValue(),'12 PM–3 PM');
  await page.locator('#arrival-through').fill('11:00');
  await page.getByText('Use window',{exact:true}).click();
  assert.equal(await page.locator('#field-time').inputValue(),'12 PM–3 PM');
  assert.equal(await page.locator('#arrival-error').isVisible(),true);
  await page.screenshot({path:path.join(require('node:os').tmpdir(),'linguar-schedule-crew-picker.png')});
  await page.evaluate(()=>closeComposer());
  await page.screenshot({path:path.join(require('node:os').tmpdir(),'linguar-schedule-visits-test.png')});
  await page.setViewportSize({width:390,height:844});
  await page.locator('.visit-summary').click();
  assert.equal(await page.locator('#field-job').isVisible(),true);
  console.log('PASS: real schedule renderer, edit/reopen empty task retains arrival and crew, narrow viewport editor');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
