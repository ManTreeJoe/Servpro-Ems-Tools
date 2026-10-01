const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1360,height:950}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.setContent(fs.readFileSync('run_doc_editor_web_assets/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace(/<link\b[^>]*>/g,''));
  for(const file of ['web_shared/theme.css','web_shared/workspace_controls.css','web_shared/responsive.css',...['app.css','schedule_visits.css','schedule_workspace.css'].map(f=>'run_doc_editor_web_assets/'+f)]) await page.addStyleTag({path:path.resolve(file)});
  for(const file of ['schedule_fields.js','visit_controls.js','app.js']) await page.addScriptTag({path:path.resolve('run_doc_editor_web_assets',file)});
  await page.evaluate(()=>{
   document.documentElement.dataset.theme='light';
   window.fixture={ok:true,exists:true,editable:true,department:'IE',date_iso:'2026-09-18',date_label:'Friday, September 18, 2026',filename:'Friday Run.docx',version:'v1',modified:'2026-09-18T09:00:00',
    section_order:['work','monitor','pending_insurance'],section_labels:{work:'Work to be performed',monitor:'Monitor',pending_insurance:'Pending insurance approval'},sections:{
     work:[{id:'a',text:'Oak residence | 123 Oak St | Inspection | 9 AM | Sam | Call first',struck:false},
       {id:'b',text:'Pine residence | 42 Pine St | Pack out | 11 AM | Pablo | Contents',struck:false},
       {id:'c',text:'Elm residence | 3 Elm St | Equipment pickup | 2 PM | Sam |',struck:true}],
     monitor:[{id:'d',text:'Maple residence | 17 Maple St | Moisture check | 3 PM | Sam |',struck:false}],
     pending_insurance:[{id:'e',text:'Birch residence | 80 Birch St | Demo | Next week | | Pablo | Waiting on approval',struck:false}]}};
   window.saved=[];window.printed=[];
   window.PanelState={init:async()=>{},get:(k,v)=>v,set(){}};
   window.pywebview={api:{load_day:async()=>structuredClone(fixture),get_crew_roster:async()=>({ok:true,entries:[]}),
    save_day:async(offset,version,sections)=>{saved.push({offset,version,sections:structuredClone(sections)});return {...structuredClone(fixture),sections:structuredClone(sections),version:'v2'};},
    print_preview:async offset=>{printed.push(offset);return {ok:true};}}};
   dispatchEvent(new Event('pywebviewready'));
  });
  await page.locator('.run-row').first().waitFor();
  assert.ok(await page.locator('#run-board').evaluate(el=>el.getBoundingClientRect().top<280),'Desktop header must leave room for scheduled jobs');
  assert.equal(await page.locator('.run-row').count(),3);
  await page.locator('#schedule-crew').selectOption('Pablo');
  assert.equal(await page.locator('.run-row').count(),1);
  await page.locator('.visit-summary').click();
  assert.equal(await page.locator('#field-job').inputValue(),'Pine residence');
  await page.locator('#field-task').fill('Contents pack out');
  await page.mouse.click(1,1);
  assert.equal(await page.locator('#item-composer').isVisible(),true);
  await page.locator('#composer-apply').click();
  await page.locator('#save-btn').click();
  await page.waitForFunction(()=>saved.length===1);
  const save=await page.evaluate(()=>saved[0]);
  assert.equal(save.sections.work.length,3);
  assert.match(save.sections.work[1].text,/Contents pack out/);
  assert.match(save.sections.work[0].text,/Inspection/);
  assert.equal(save.sections.pending_insurance.length,1);
  await page.locator('#print-run').click();
  assert.deepEqual(await page.evaluate(()=>printed),[0]);
  await page.locator('[data-schedule-view="waiting"]').click();
  assert.equal(await page.locator('.run-row').count(),1);
  assert.match(await page.locator('.run-row').innerText(),/Not scheduled/);
  await page.locator('[data-schedule-view="all"]').click();
  await page.locator('#schedule-crew').selectOption('');
  await page.locator('#schedule-completed').check();
  assert.equal(await page.locator('.run-row').count(),5);
  await page.locator('#schedule-search').fill('Elm');
  assert.equal(await page.locator('.run-row').count(),1);
  await page.getByRole('button',{name:'Reopen work',exact:true}).click();
  assert.equal(await page.evaluate(()=>state.model.sections.work[2].struck),false);
  await page.locator('#undo-btn').click();
  assert.equal(await page.evaluate(()=>state.model.sections.work[2].struck),true);
  await page.locator('#schedule-search').fill('No matching address');
  assert.equal(await page.locator('.run-row').count(),0);
  await page.locator('#schedule-search').fill('');
  await page.locator('[data-schedule-view="daily"]').click();
  await page.locator('#schedule-completed').uncheck();
  for(const theme of ['light','dark']){
   await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);
   await page.screenshot({path:path.join(os.tmpdir(),`linguar-schedule-lops-${theme}.png`),animations:'disabled'});
   const colors=await page.locator('.run-row').first().evaluate(node=>({background:getComputedStyle(node).backgroundColor,surface:getComputedStyle(node).getPropertyValue('--surface').trim()}));
   if(theme==='dark') assert.notEqual(colors.background,'rgb(255, 255, 255)','Dark rows must not retain a white surface');
  }
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'No horizontal page overflow');
  await page.locator('.visit-summary').first().scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(os.tmpdir(),'linguar-schedule-lops-narrow.png')});
  await page.setViewportSize({width:1360,height:950});
  // A slow old-day response must not replace the newer selected date.
  await page.evaluate(()=>{
   state.dirty=false;window.loads=[];
   pywebview.api.load_day=()=>new Promise(resolve=>loads.push(resolve));
   walkDay(1);walkDay(1);
   loads[1]({...fixture,date_iso:'2026-09-20',date_label:'Sunday'});
  });
  await page.waitForFunction(()=>state.model.date_iso==='2026-09-20');
  await page.evaluate(()=>loads[0]({...fixture,date_iso:'2026-09-19'}));
  assert.equal(await page.locator('#schedule-date').inputValue(),'2026-09-20');
  await page.evaluate(()=>{pywebview.api.load_day=async()=>({ok:false,error:'Run folder unavailable'});return loadDay();});
  assert.match(await page.locator('#empty').innerText(),/Run folder unavailable/);
  assert.equal(await page.locator('#print-run').isDisabled(),true);
  assert.deepEqual(errors,[]);
  console.log('PASS: L OPS daily/waiting, crew/search/completed, correct filtered edits, full save/print, undo, safe dialog, responsive themes, stale day and error states.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
