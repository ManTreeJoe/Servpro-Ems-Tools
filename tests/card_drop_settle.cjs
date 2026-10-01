const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage();await page.setContent('<div id="card" data-card-id="job" style="position:absolute;left:400px;top:250px;width:200px;height:80px;background:#ddd">Job card</div>');
 await page.addScriptTag({path:path.resolve('web_shared/card_drop_preview.js')});
 await page.evaluate(()=>CardDropPreview.land(document.querySelector('#card'),{left:100,top:100,width:200,height:80}));
 assert.equal(await page.locator('.card-drop-flyer').count(),1);
 assert.equal(await page.locator('[data-card-id]').count(),1);
 await page.evaluate(()=>document.dispatchEvent(new Event('dragend')));
 assert.equal(await page.locator('.card-drop-flyer').count(),1,'dragend must not cancel settling');
 await page.waitForFunction(()=>!document.querySelector('.card-drop-flyer'));
 assert.equal(await page.locator('#card').evaluate(el=>el.style.visibility),'');
 await page.emulateMedia({reducedMotion:'reduce'});
 await page.evaluate(()=>CardDropPreview.land(document.querySelector('#card'),{left:0,top:0,width:200,height:80}));
 assert.equal(await page.locator('.card-drop-flyer').count(),0);
 console.log('PASS: cursor-to-slot animation, cleanup, dragend and reduced motion');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
