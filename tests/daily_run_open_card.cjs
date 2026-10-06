const {chromium}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage();await page.setContent('<iframe style="width:1100px;height:800px"></iframe>');
 await page.evaluate(()=>{window.messages=[];addEventListener('message',e=>messages.push(e.data));});
 const frame=page.frames()[1];
 await frame.setContent(fs.readFileSync('audit_web_assets/index.html','utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace(/<link\b[^>]*>/g,''));
 for(const file of ['web_shared/audit_detail.js','audit_web_assets/app.js'])await frame.addScriptTag({path:path.resolve(file)});
 await frame.evaluate(()=>{
  window.pywebview={api:{}};
  const row={client:'Example customer',trello_card_id:'exact-card',division:'EMS',found:true,form_issues:[],photo_issues:[],techs:[]};
  state.rows=[row];state.selected_client=rowKey(row);state.mode='daily';renderDetail();
  window.before=document.querySelector('#detail-view');
 });
 await frame.getByRole('button',{name:'Open job card ↗'}).click();
 await page.waitForFunction(()=>messages.some(m=>m.type==='linguar-open-job'));
 assert.deepEqual(await page.evaluate(()=>messages.find(m=>m.type==='linguar-open-job')),{type:'linguar-open-job',focus:'Example customer',cardId:'exact-card',division:'EMS'});
 assert(await frame.evaluate(()=>before===document.querySelector('#detail-view') && state.selected_client===rowKey(state.rows[0])));
 console.log('PASS: Daily Run detail button routes exact card and retains selected detail.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
