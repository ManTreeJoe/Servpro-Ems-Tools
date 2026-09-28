const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage();
 await page.setContent('<div class="board" style="width:300px;height:150px;overflow:auto"><div style="width:1000px;height:140px"><div class="kcard" draggable="false" style="width:600px;height:50px">Job card</div></div></div>');
 await page.addScriptTag({path:path.resolve('web_shared/h_scroll.js')});
 await page.evaluate(()=>document.querySelector('.board').scrollLeft=100);
 await page.mouse.move(150,30);await page.mouse.down();await page.mouse.move(100,30);
 assert.equal(await page.locator('.board').evaluate(el=>el.classList.contains('hdrag-active')),false,'Grabbing a Jobs card must not start board panning');
 await page.mouse.up();
 assert.equal(await page.locator('.board').evaluate(el=>el.scrollLeft),100);
 await page.mouse.move(150,110);await page.mouse.down();await page.mouse.move(100,110);await page.mouse.up();
 assert.equal(await page.locator('.board').evaluate(el=>el.scrollLeft),150,'Dragging bare background still pans');
 console.log('PASS: card drag and board panning stay separate');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
