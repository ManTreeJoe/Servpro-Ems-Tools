const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require('playwright');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.emulateMedia({reducedMotion:'reduce'});
 await page.setContent('<div id="status-msg"></div>');
 for(const f of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css'])await page.addStyleTag({path:path.resolve(f)});
 for(const f of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','pipeline_web_assets/app.js'])await page.addScriptTag({path:path.resolve(f)});
 await page.evaluate(()=>{
  window.opened=[];window.pywebview={api:{open_url:async url=>{opened.push(url);return true;}}};
  window.base={ok:true,client:'DocuSketch test',card_id:'card',selected_division:'EMS',audit:{found:true},crm:{},comments:[]};
  window.controller=openAuditModal(base);
 });
 assert.equal(await page.locator('[data-open-docusketch]').count(),0);
 await page.evaluate(()=>controller.applyRefresh({ok:true,card_id:'card',info_sections:[{name:'Links',fields:[{id:'link_docusketch',value:'https://app.docusketch.com/player/example'}]}]}));
 await page.locator('[data-open-docusketch]').click();
 assert.deepEqual(await page.evaluate(()=>opened),['https://app.docusketch.com/player/example']);
 await page.screenshot({path:path.join(process.env.TEMP,'oneloss-docusketch-toolbar.png')});
 await page.evaluate(()=>controller.applyRefresh({ok:true,card_id:'card',info_sections:[{name:'Links',fields:[{id:'link_docusketch',value:'javascript:alert(1)'}]}]}));
 assert.equal(await page.locator('[data-open-docusketch]').count(),0);
 console.log('PASS toolbar hidden without safe link, appears after refresh, opens exact saved URL');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
