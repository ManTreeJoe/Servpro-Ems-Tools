const {chromium}=require('playwright'),assert=require('node:assert/strict'),path=require('node:path');
const {pathToFileURL}=require('node:url');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage();await page.route(/^https?:/,r=>r.abort());
 await page.addInitScript(()=>{window.saves=[];window.pywebview={api:{get_pinned_card_for_item:async()=>({}),save_doc:async(date,sections)=>{saves.push(sections);return {ok:true,doc:{date_iso:date,doc_exists:true,sections}};}}};});
 await page.goto(pathToFileURL(path.resolve('apa_web_assets/index.html')).href);
 await page.evaluate(()=>{state.doc={date_iso:'2026-09-25',doc_exists:true,sections:[
  {name:'KIM',items:[{text:'X'}],count:1},{name:'PABLO',items:[{text:'A'},{text:'B'}],count:2}]};renderBoard();});
 async function drop(from,index,to,before){await page.evaluate(({from,index,to,before})=>{
  const el=document.querySelector(`.item[data-section="${from}"][data-index="${index}"]`);
  const body=document.querySelector(`.section-body[data-section="${to}"]`);
  const target=body.querySelector(`.item[data-index="${before}"]`);
  const dt=new DataTransfer();el.dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:dt}));
  body.dispatchEvent(new DragEvent('dragover',{bubbles:true,dataTransfer:dt,clientY:target.getBoundingClientRect().top+1}));
  const gap=body.querySelector('.card-drop-preview');
  if (!gap || gap.nextElementSibling !== target) throw new Error('Preview must mark exact insertion slot');
  body.dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:dt,clientY:gap.getBoundingClientRect().top+5}));
 },{from,index,to,before});}
 await drop('KIM',0,'PABLO',1);await page.waitForFunction(()=>saves.length===1);
 assert.deepEqual(await page.evaluate(()=>saves[0][1].items.map(i=>i.text)),['A','X','B']);
 await drop('PABLO',2,'PABLO',0);await page.waitForFunction(()=>saves.length===2);
 assert.deepEqual(await page.evaluate(()=>saves[1][1].items.map(i=>i.text)),['B','A','X']);
 assert.deepEqual(await page.locator('.section-body[data-section="PABLO"] .item-text').allTextContents(),['B','A','X']);
 await page.evaluate(()=>{
  const body=document.querySelector('.section-body[data-section="PABLO"]');
  const cards=body.querySelectorAll('.item');
  CardDropPreview.show(body,'.item',cards[2],cards[1].getBoundingClientRect().top+1);
 });
 await page.evaluate(()=>Promise.all(document.getAnimations().map(a=>a.finished.catch(()=>{}))));
 await page.screenshot({path:path.join(require('node:os').tmpdir(),'oneloss-apa-preview.png')});
 await page.evaluate(()=>document.dispatchEvent(new Event('dragend')));
 assert.equal(await page.locator('.card-drop-preview').count(),0,'Ending drag clears the gap');
 console.log('PASS: APA cross-lane second slot and same-lane reorder persist and render');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
