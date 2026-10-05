const {chromium}=require('playwright');
const assert=require('node:assert/strict'),path=require('node:path'),os=require('node:os');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1400,height:950}});
  await page.addInitScript(()=>{
   window.WebSocket=class {
    constructor(){window.testSocket=this;this.readyState=1;setTimeout(()=>this.onopen?.(),0);}
    send(raw){const m=JSON.parse(raw);if(m.event==='phx_join')setTimeout(()=>this.onmessage?.({data:JSON.stringify({event:'system',payload:{extension:'postgres_changes',status:'ok'}})}),0);}
    close(){this.readyState=3;}
    change(){this.onmessage?.({data:JSON.stringify({event:'postgres_changes'})});}
   };
   window.savedCommands=[];window.rows=[];window.failSave=false;
   window.pywebview={api:{
    schedule_load:async()=>({ok:true,context:'ctx',department:'IE',records:window.rows}),
    schedule_realtime:async()=>({ok:true,url:'https://example.supabase.co',key:'public',token:'user-token',department:'IE'}),
    schedule_search:async()=>({ok:true,jobs:[window.searchJob||{id:'job1',job_id:'job1',title:'Test real job',address:'123 Test Street',insurance:'AAA',activities:[]}]}),
    schedule_pick_document:async()=>({ok:true,preview:{import_key:'batch',bulk_entries:[{entry_title:'Second job',visit:{job_id:null,notes:'Second job: Demo needed',group:'TBS Mitigation',date:null}}],skipped:[{}],source_filename:'Monday Run.docx',section_labels:{tbs_mitigation:'TBS Mitigation',monitor:'Monitor'},visits:[
      {draft_id:'50000000-0000-4000-8000-000000000001',raw_text:'Second job: Demo needed',section:'tbs_mitigation',queue:'tbs',group:'TBS Mitigation',proposed_date:null,skip_reason:''},
      {draft_id:'skip',raw_text:'Crossed-out work',section:'monitor',skip_reason:'Crossed out in document'}],tables:[],blockers:[]}}),
    schedule_import_all:async()=>{window.rows.push({id:'50000000-0000-4000-8000-000000000001',job_id:null,title:'Second job',entry_title:'Second job',source_key:'batch:1',queue:'tbs',group:'TBS Mitigation',date:null,notes:'Second job: Demo needed',activities:[{label:'Demo',people:[]}],revision:1,needs_link:true});return {ok:true,result:{added:1,needs_link:1,already_imported:0}};},
    schedule_save:async(command)=>{
     window.savedCommands.push(command);
     if(window.failSave)return {ok:false,error:'Connection interrupted. Retry safely.'};
     window.rows=[{...command.visit,time:command.visit.arrival,revision:1,title:'Test real job',address:'123 Test Street'}];
     return {ok:true,saved:{revision:1}};
    }
   }};
  });
  await page.goto('file:///'+path.resolve('run_doc_editor_web_assets/calendar_preview.html').replaceAll('\\','/')+'?live=1');
  await page.getByText('Live drafts · IE', {exact:false}).waitFor();
  assert.equal(await page.locator('.wc-day').count(),3);
  assert.equal(await page.locator('[data-edit]').count(),0);
  await page.locator('#add-job-search').fill('Test');
  await page.locator('[data-found-job]').click();
  assert.equal(await page.locator('#address').inputValue(),'123 Test Street');
  assert.equal(await page.locator('#address').getAttribute('readonly'),'');
  await page.locator('#activity-picker summary').click();
  await page.locator('[data-activity="Demo"]').click();
  await page.locator('#activity-picker summary').click();
  await page.locator('[data-assignment]').fill('Sam');
  await page.evaluate(()=>window.failSave=true);
  await page.getByRole('button',{name:'Save draft',exact:true}).click();
  await page.getByText('Connection interrupted. Retry safely.').waitFor();
  assert.equal(await page.locator('#editor').isVisible(),true);
  await page.evaluate(()=>window.failSave=false);
  await page.getByRole('button',{name:'Save draft',exact:true}).click();
  await page.locator('#editor').waitFor({state:'hidden'});
  await page.locator('.wc-day [data-edit]').waitFor();
  const commands=await page.evaluate(()=>window.savedCommands);
  assert.equal(commands[0].operation_id,commands[1].operation_id);
  assert.equal(commands[0].visit.job_id,'job1');
  assert.equal(commands[0].visit.title,undefined);
  assert.deepEqual(commands[0].visit.activities,[{label:'Demo',people:['Sam']}]);
  const dragCard=await page.locator('.wc-day [data-edit]').boundingBox();
  const dropDay=page.locator('.wc-day').nth(1);
  const dropBox=await dropDay.boundingBox();
  const targetDate=await dropDay.getAttribute('data-drop-date');
  await page.mouse.move(dragCard.x+30,dragCard.y+20);
  await page.mouse.down();
  await page.mouse.move(dropBox.x+50,dropBox.y+100,{steps:12});
  await page.mouse.up();
  await page.waitForTimeout(400);
  assert.equal(await page.locator('#editor').isVisible(),false,'Dropping must not open the editor');
  await page.waitForFunction(day=>window.savedCommands.at(-1).visit.date===day,targetDate);
  await page.waitForTimeout(300);
  await page.locator('.wc-day [data-edit]').click();
  await page.locator('#notes').fill('My unsaved work');
  await page.evaluate(()=>{window.rows[0].revision=2;window.rows[0].time='1 PM';window.testSocket.change();});
  await page.getByText('This visit changed on another computer.',{exact:false}).waitFor();
  assert.equal(await page.locator('#notes').inputValue(),'My unsaved work');
  await page.locator('#cancel').click();
  await page.locator('.wc-day [data-edit]').click();
  assert.equal(await page.locator('#time').inputValue(),'1 PM');
  await page.locator('#cancel').click();
  await page.screenshot({path:path.join(os.tmpdir(),'schedule-live-drafts.png')});
  async function dragTo(source,target){
   const a=await source.boundingBox(),b=await target.boundingBox();
   await page.mouse.move(a.x+25,a.y+15);await page.mouse.down();
   await page.mouse.move(b.x+40,b.y+45,{steps:12});await page.mouse.up();
   await page.waitForTimeout(400);
   assert.equal(await page.locator('#editor').isVisible(),false);
  }
  await page.evaluate(()=>window.failSave=true);
  await dragTo(page.locator('.wc-day [data-edit]'),page.locator('.wc-day').nth(2));
  await page.getByText('Move not saved.',{exact:false}).waitFor();
  assert.equal(await page.evaluate(()=>window.rows[0].date),targetDate);
  await page.evaluate(()=>window.failSave=false);
  await page.getByRole('button',{name:'Legacy view',exact:true}).click();
  const legacyCard=page.locator('.wc-legacy-card');
  await legacyCard.scrollIntoViewIfNeeded();
  const monitor=page.locator('.run-paper [data-drop-group="Monitor"]');
  await monitor.scrollIntoViewIfNeeded();
  await dragTo(legacyCard,monitor);
  await page.waitForFunction(()=>window.rows[0].group==='Monitor');
  await page.screenshot({path:path.join(os.tmpdir(),'schedule-live-drag-legacy.png')});
  await page.getByRole('button',{name:'Back to calendar',exact:true}).click();
  await page.getByRole('button',{name:'Import document',exact:true}).click();
  await page.getByRole('button',{name:'Choose document',exact:true}).click();
  await page.getByText('Second job: Demo needed',{exact:true}).waitFor();
  assert.match(await page.locator('[data-message]').innerText(),/1 crossed-out/);
  await page.screenshot({path:path.join(os.tmpdir(),'schedule-document-import.png')});
  await page.evaluate(()=>window.searchJob={id:'job2',job_id:'job2',title:'Second job',activities:[]});
  await page.getByRole('button',{name:'Import all',exact:true}).click();
  await page.getByText('Imported 1 entries',{exact:false}).waitFor();
  await page.locator('#document-import [data-close]').click();
  await page.locator('[data-edit="50000000-0000-4000-8000-000000000001"]').click();
  assert.equal(await page.locator('#queue').inputValue(),'tbs');
  assert.equal(await page.locator('#run-group').inputValue(),'TBS Mitigation');
  assert.match(await page.locator('#notes').inputValue(),/Second job: Demo needed/);
  await page.locator('#schedule-link-search').fill('Second');
  await page.locator('#schedule-link-results button').click();
  await page.getByRole('button',{name:'Save draft',exact:true}).click();
  await page.locator('#editor').waitFor({state:'hidden'});
  const imported=await page.evaluate(()=>window.savedCommands.at(-1));
  assert.equal(imported.visit.date,null);
  assert.equal(imported.visit.id,'50000000-0000-4000-8000-000000000001');
  assert.equal(imported.visit.job_id,'job2');
  assert.equal(imported.source_key,'batch:1');
  console.log('Live schedule UI: real-job selection, readonly facts, save failure/retry and rendering passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
