const {chromium}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1100,height:750}});
 const html=fs.readFileSync('snapshot_web_assets/index.html','utf8');
 const banner=html.match(/<div id="snapshot-form-loading"[\s\S]*?<\/div>/)[0];
 await page.setContent((html.match(/<style>[\s\S]*?<\/style>/g)||[]).join('')+'<style>.hidden{display:none}body{padding:24px}</style><h2>Create snapshot</h2><button id="open">Open snapshot</button>'+banner+'<footer class="statusbar">Ready</footer>');
 await page.addStyleTag({path:path.resolve('web_shared/theme.css')});
 await page.evaluate(()=>document.documentElement.dataset.theme='dark');
 await page.addScriptTag({path:path.resolve('web_shared/loading_feedback.js')});
 await page.addScriptTag({path:path.resolve('web_shared/progress_bar.js')});
 await page.evaluate(()=>{
  document.querySelector('#open').onclick=()=>{
   document.querySelector('#snapshot-form-loading').classList.remove('hidden');
   LoadingFeedback.track('prefill_from_trello_card',new Promise(resolve=>window.finish=resolve),{force:true});
  };
 });
 await page.locator('#open').click();await page.waitForTimeout(350);
 assert.equal(await page.locator('#snapshot-form-loading').isVisible(),true);
 assert.equal(await page.locator('#oneloss-loading-feedback').isVisible(),false,'Snapshot already owns visible loading feedback');
 assert.equal(await page.locator('.olf-control').count(),0,'No second spinner on the control');
 await page.evaluate(()=>Progress.set(2,10));await page.waitForTimeout(100);
 assert.equal(await page.locator('.ems-prog').isVisible(),false,'Native banner also suppresses legacy footer bar');
 await page.evaluate(()=>Progress.hide());
 await page.evaluate(()=>document.querySelector('#snapshot-form-loading').classList.add('hidden'));
 await page.waitForTimeout(100);
 assert.equal(await page.locator('#oneloss-loading-feedback').isVisible(),true,'Fallback returns while the request still runs');
 await page.evaluate(()=>Progress.set(3,10));await page.waitForTimeout(100);
 assert.equal(await page.locator('#oneloss-loading-feedback').isVisible(),false,'Streamed progress takes priority');
 assert.equal(await page.locator('.ems-prog i').evaluate(n=>n.style.width),'30%');
 await page.evaluate(()=>{Progress.hide();finish();});await page.waitForTimeout(100);
 assert.equal(await page.locator('#oneloss-loading-feedback').isVisible(),false);
 for(const cls of ['ui-spinner','cmt-refresh-spinner','spinner','snapshot-skeleton','job-card-skeleton','skeleton-line','ems-skel','settings-loading','context-loading','field-note-loading','save-state saving','dept-splash-spin']){
  await page.evaluate(cls=>{const el=document.createElement('div');el.className=cls;el.style.cssText='width:40px;height:10px';document.body.append(el);window.native=el;LoadingFeedback.track('load',new Promise(resolve=>window.finish=resolve),{force:true});},cls);
  await page.waitForTimeout(300);
  assert.equal(await page.locator('#oneloss-loading-feedback').isVisible(),false,cls+' has existing feedback');
  await page.evaluate(()=>{native.remove();finish();});
 }
 // One owner across the shell and its visible, same-origin tool frame.
 const handle=await page.evaluateHandle(()=>{const f=document.createElement('iframe');document.body.append(f);return f;});
 const child=await handle.asElement().contentFrame();
 await child.setContent('<div class="spinner" style="width:20px;height:20px">Loading tool</div>');
 await child.addScriptTag({path:path.resolve('web_shared/loading_feedback.js')});
 await child.evaluate(()=>LoadingFeedback.refresh());
 await page.evaluate(()=>{LoadingFeedback.track('tool_navigation',new Promise(resolve=>window.finish=resolve),{force:true});});
 await page.waitForTimeout(350);
 assert.equal(await page.locator('#oneloss-loading-feedback').isVisible(),false,'Child tool owns the indicator, shell stays quiet');
 await page.evaluate(()=>document.querySelector('iframe').hidden=true);await page.waitForTimeout(100);
 assert.equal(await page.locator('#oneloss-loading-feedback').isVisible(),true,'Hidden tools cannot suppress visible fallback');
 await page.evaluate(()=>{finish();document.querySelector('iframe').remove();});
 await page.evaluate(()=>{document.querySelector('#snapshot-form-loading').classList.remove('hidden');});
 await page.screenshot({path:path.join(require('os').tmpdir(),'snapshot-single-loader.png')});
 console.log('PASS: snapshot, native spinners/skeletons, streamed progress, fallback restoration and cleanup');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
