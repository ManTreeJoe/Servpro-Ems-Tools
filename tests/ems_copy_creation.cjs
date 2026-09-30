const {chromium}=require('playwright'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1000,height:750}});
 await page.setContent('<main></main>');
 for(const f of ['web_shared/theme.css','pipeline_web_assets/app.css'])await page.addStyleTag({path:path.resolve(f)});
 await page.addScriptTag({path:path.resolve('pipeline_web_assets/ems_copy.js')});
 await page.evaluate(()=>{
  document.documentElement.dataset.theme='dark';window.calls=[];window.existing=false;window.fail=true;window.finished=0;
  window.pywebview={api:{preview_ems_card_copy:async()=>({ok:true,name:'Example job',target_name:'Estimating',lists:[{id:'lane',name:'Needs estimate'}],existing:existing?{id:'b'.repeat(24)}:null}),create_ems_card_copy:async(...a)=>{calls.push(a);await new Promise(r=>setTimeout(r,100));return fail?{ok:false,error:'Copy not confirmed. Check again.'}:{ok:true};}}};
  openEmsCopyCreateModal('Example job','source',()=>finished++);
 });
 await page.locator('select:not(:disabled)').waitFor();assert(await page.locator('[data-create]').isDisabled());
 await page.locator('select').selectOption('lane');
 await page.screenshot({path:path.join(process.env.TEMP,'oneloss-copy-to-board.png')});
 await page.locator('[data-create]').click();await page.waitForTimeout(200);
 assert.equal(await page.locator('[data-create]').innerText(),'Check / finish copy');
 assert.equal((await page.evaluate(()=>calls)).length,1);
 await page.evaluate(()=>fail=false);await page.locator('[data-create]').click();await page.waitForTimeout(200);
 assert.equal(await page.evaluate(()=>finished),1);
 await page.evaluate(()=>{existing=true;openEmsCopyCreateModal('Example job','source',()=>finished++);});
 await page.locator('[data-open]:visible').waitFor();assert(await page.locator('[data-create]').isDisabled());
 console.log('PASS: section selection, explicit create, error recovery and existing-copy guard');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
