const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path'),os=require('node:os');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1360,height:900}}),errors=[];
  page.on('pageerror',e=>{errors.push(e.message);console.error(e.message);});
  await page.addInitScript(()=>{
   const card={card_id:'a'.repeat(24),board_id:'wip',board_name:'WORK IN PROGRESS',title:'Oak home',list_id:'tbs',lane_name:'TBS MITIGATION',version:4,suggested_list:'work',lanes:[{id:'tbs',name:'TBS MITIGATION'},{id:'work',name:'WORK IN PROGRESS'},{id:'monitor',name:'MONITOR'}]};
   const entries=[{id:'v1',revision:1,title:'Oak home',group:'Work To Be Performed',activities:[{label:'Demo'}],cards:[card],confirmed:false,note:''},{id:'v2',revision:2,title:'Imported entry',group:'Monitor',activities:[{label:'Monitor'}],cards:[],note:'Link this entry to a job to enable board moves.'},{id:'v3',revision:3,title:'Two linked cards',group:'Work To Be Performed',activities:[{label:'Demo'}],cards:[card,{...card,card_id:'b'.repeat(24),board_name:'CONTENTS'}],note:'Choose the card to move; no card is selected automatically.'}];
   window.confirmCommands=[];window.confirmFail=true;window.reviewDays=[];
   window.pywebview={api:{
    schedule_load:async()=>({ok:true,context:'bound',department:'IE',records:[]}),
    schedule_realtime:async()=>({ok:false,error:'Test offline'}),
    schedule_confirmation_preview:async(day,context)=>{if(context!=='bound')throw Error('Wrong context');window.reviewDays.push(day);return {ok:true,review:{date:day,department:'IE',entries}};},
    schedule_confirm_day:async(c,context)=>{if(context!=='bound')throw Error('Wrong context');window.confirmCommands.push(c);return window.confirmFail?{ok:false,error:'Connection interrupted. Retry the same confirmation.'}:{ok:true,result:{confirmed:3,moved:1}};}
   }};
  });
  await page.goto('file:///'+path.resolve('run_doc_editor_web_assets/calendar_preview.html').replaceAll('\\','/')+'?live=1');
  await page.waitForFunction(()=>document.querySelector('.preview-note').textContent.startsWith('Live schedule'));
  const selected=page.locator('[data-day]').nth(1),day=await selected.getAttribute('data-day');await selected.click();
  await page.getByRole('button',{name:'Confirm day',exact:true}).click();
  const d=page.locator('.schedule-confirmation');await d.locator('.confirmation-row').nth(2).waitFor();
  assert.equal((await page.evaluate(()=>window.reviewDays))[0],day);
  assert.equal(await d.locator('[data-lane]').nth(0).inputValue(),'work');
  assert.equal(await d.locator('[data-lane]').nth(1).isDisabled(),true);
  assert.equal(await d.locator('[data-card]').nth(2).inputValue(),'','Never choose between cards silently');
  assert.equal((await page.evaluate(()=>window.confirmCommands)).length,0,'Review does not mutate');
  await d.locator('[data-lane]').nth(0).selectOption('monitor');
  await d.locator('[data-confirm]').click();await d.getByRole('alert').waitFor();
  assert.equal(await d.locator('[data-lane]').nth(0).inputValue(),'monitor','Failure keeps user selection');
  await page.evaluate(()=>window.confirmFail=false);await d.locator('[data-confirm]').click();
  await d.getByText(/3 visits confirmed/).waitFor();
  const cmds=await page.evaluate(()=>window.confirmCommands);assert.equal(cmds[0].operation_id,cmds[1].operation_id);
  assert.equal(cmds[1].entries[0].list_id,'monitor');assert.equal(cmds[1].entries[1].action,'keep');assert.equal(cmds[1].entries[2].action,'keep');
  await d.getByRole('button',{name:'Done',exact:true}).click();
  await page.getByRole('button',{name:'Confirm day',exact:true}).click();await d.locator('.confirmation-row').nth(2).waitFor();
  await page.screenshot({path:path.join(os.tmpdir(),'oneloss-confirm-review-desktop.png')});
  await page.setViewportSize({width:520,height:760});
  assert.ok(await d.evaluate(el=>el.scrollWidth<=el.clientWidth+2),'No horizontal clipping on narrow window');
  await page.screenshot({path:path.join(os.tmpdir(),'oneloss-confirm-review-narrow.png')});
  await page.keyboard.press('Escape');await d.waitFor({state:'hidden'});
  assert.deepEqual(errors,[]);console.log('Confirmation UI: selected day, complete review, corrections, ambiguity, retry, cancel and narrow layout passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
