const {chromium}=require('playwright');
const path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const failures=[];
 try{
  for(const kind of ['shared intake popup','job card','job info editor','APA editor','Snapshot popup']){
   const page=await browser.newPage({viewport:{width:1440,height:1000}});
   const errors=[];page.on('pageerror',e=>errors.push(e.message));
   try{
    await page.setContent('<div id="status-msg"></div>');
    for(const file of ['web_shared/theme.css','web_shared/modal.css','audit_web_assets/app.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css',...(kind==='APA editor'?['apa_web_assets/app.css']:[])])await page.addStyleTag({path:path.resolve(file)});
    const scripts=kind==='APA editor'?['apa_web_assets/app.js']:kind==='Snapshot popup'?['snapshot_web_assets/app.js']:['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js'];
    for(const file of scripts)await page.addScriptTag({path:path.resolve(file)});
    await page.evaluate(async kind=>{
     window.pywebview={api:{job_settings_schema:async()=>({ok:true,fields:[{id:'phone',label:'Phone',core:true}]}),job_settings_load:async()=>({ok:true,values:{phone:'555'}}),status_options:async()=>({statuses:[],highlight:[]}),get_franchise_list:async()=>[],get_item_franchise:async()=>''}};
     if(kind==='shared intake popup')openModal({title:'New Loss fixture',body:'<label>Customer <input id="popup-field" value="Saved customer"></label><button class="modal-close">Cancel</button>'});
     else if(kind==='job card')openAuditModal({ok:true,client:'Test customer',card_id:'test-card',selected_division:'EMS',audit:{found:true},crm:{},comments:[],division_trello_cards:[]});
     else if(kind==='job info editor')await openJobInfoEditor({client:'Test customer',card_id:'test-card'},{},()=>{});
     else if(kind==='APA editor')await showItemPopover({title:'Edit APA',section:'Initial Uploads',text:'Saved customer',onSave:async()=>{}});
     else mkSnapModal({title:'Snapshot',body:'<input id="popup-field" value="Saved customer"><button class="modal-close">Close</button>'});
    },kind);
    const selector=kind==='shared intake popup'||kind==='Snapshot popup'?'#popup-field':kind==='job card'?'[data-comment-input]':kind==='APA editor'?'#apa-edit-text':'[data-job-info-input]';
    const field=page.locator(selector);
    await field.click();
    const box=await field.boundingBox();
    await page.mouse.move(box.x+10,box.y+10);await page.mouse.down();await page.mouse.move(3,3);await page.mouse.up();
    assert.equal(await field.count(),1,`${kind}: releasing outside a field dismissed the popup`);
    await field.click();
    await page.mouse.click(3,3);
    assert.equal(await field.count(),1,`${kind}: clicking outside dismissed the popup`);
    assert.deepEqual(errors,[]);
    const close=kind==='shared intake popup'?page.locator('.modal-close-icon'):kind==='APA editor'?page.locator('#apa-pop-close'):kind==='Snapshot popup'?page.locator('.modal-close'):page.locator('[data-close]');
    await close.click();
    assert.equal(await field.count(),0,`${kind}: explicit close stopped working`);
    console.log(`PASS: ${kind} ignores outside clicks/releases; explicit Close works.`);
   }catch(e){failures.push(e.message);console.error(`FAIL: ${e.message}`);}
   finally{await page.close();}
  }
  assert.deepEqual(failures,[]);
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
