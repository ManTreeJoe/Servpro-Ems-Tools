const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage();
  await page.setContent('<iframe style="width:1100px;height:800px"></iframe>');
  await page.evaluate(()=>{window.messages=[];addEventListener('message',e=>messages.push(e.data));});
  const frame=page.frames()[1];
  await frame.setContent(fs.readFileSync('run_doc_editor_web_assets/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace(/<link\b[^>]*>/g,''));
  for(const file of ['web_shared/ctx_menu.js','run_doc_editor_web_assets/schedule_fields.js','run_doc_editor_web_assets/app.js']) await frame.addScriptTag({path:path.resolve(file)});
  await frame.evaluate(()=>{
   state.model={sections:{work:[{text:'Robertino Fieraru: 21490 Pine Ln (Demo)',card_id:'linked-card',division:'EMS'}]},section_order:['work'],section_labels:{work:'Work'},editable:true};
   state.dirty=true;renderRows();
  });
  await frame.getByRole('button',{name:'Open job ↗',exact:true}).click();
  await page.waitForFunction(()=>messages.some(x=>x.type==='linguar-open-job'));
  assert.equal(await frame.evaluate(()=>state.dirty),true);
  await page.evaluate(()=>{messages=[];});
  await frame.locator('.run-row').click({button:'right'});
  await frame.getByRole('button',{name:'Open job',exact:true}).click();
  await page.waitForFunction(()=>messages.some(x=>x.type==='linguar-open-job'));
  assert.deepEqual(await page.evaluate(()=>messages.find(x=>x.type==='linguar-open-job')),{type:'linguar-open-job',focus:'Robertino Fieraru',cardId:'linked-card',division:'EMS'});
  assert.equal(await frame.evaluate(()=>state.dirty),true);
  await frame.evaluate(()=>{state.model.sections.work=[{text:'Other Customer | 1 Main St | Demo'}];renderRows();});
  await frame.locator('.visit-summary').dispatchEvent('keydown',{key:'F10',shiftKey:true,bubbles:true});
  await frame.getByRole('button',{name:'Open job',exact:true}).click();
  await page.waitForFunction(()=>messages.filter(x=>x.type==='linguar-open-job').length===2);
  assert.equal(await page.evaluate(()=>messages.filter(x=>x.type==='linguar-open-job')[1].focus),'Other Customer');
  console.log('PASS right-click and keyboard Open job; exact linked card, legacy names and dirty schedule preserved');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
