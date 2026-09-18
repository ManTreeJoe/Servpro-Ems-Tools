const {chromium}=require('playwright');
const fs=require('fs'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage();
  for(const [asset,name,arg] of [['apa_web_assets','printAPA','selected.docx'],['run_doc_editor_web_assets','printRun',-7]]){
   const source=fs.readFileSync(`${asset}/app.js`,'utf8');
   const start=source.indexOf(`async function ${name}()`),end=source.indexOf('\n}',start)+2;
   assert.ok(start>=0&&end>start);
   const original=fs.readFileSync(`${asset}/index.html`,'utf8');
   const html=original.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace(/<link\b[^>]*>/g,'');
   await page.setContent(html);
   for(const match of original.matchAll(/<link[^>]*href="([^"]+\.css)(?:\?[^"]*)?"[^>]*>/g)) await page.addStyleTag({path:require('path').resolve(asset,match[1])});
   await page.evaluate(()=>{
    window.$=s=>document.querySelector(s);
    window.state={doc:{doc_path:'selected.docx'},dayOffset:-7,dirty:true,model:{exists:true}};
    window.calls=[];window.confirm=()=>false;
    window.saveDoc=async()=>true;
    window.setStatus=window.showNotice=message=>{window.notice=message;};
    window.pywebview={api:{print_preview:async arg=>{calls.push(arg);return {ok:true};}}};
   });
   await page.addScriptTag({content:source.slice(start,end)});
   await page.evaluate(name=>window[name](),name);
   assert.deepEqual(await page.evaluate(()=>calls),name==='printAPA'?[arg]:[],'APA prints directly; schedule retains its existing guard');
   await page.evaluate(()=>calls=[]);
   await page.evaluate(()=>window.confirm=()=>true);
   await page.evaluate(name=>window[name](),name);
   assert.deepEqual(await page.evaluate(()=>calls),[arg]);
   await page.evaluate(()=>{pywebview.api.print_preview=async()=>({ok:false,error:'Word unavailable'});});
   await page.evaluate(name=>window[name](),name);
   assert.equal(await page.evaluate(()=>notice),'Word unavailable');
   assert.equal(await page.locator(name==='printAPA'?'#print-btn':'#print-run').isDisabled(),false);
   if(name==='printAPA'){
    await page.evaluate(()=>{calls=[];saveDoc=async()=>false;});
    await page.evaluate(()=>printAPA());
    assert.deepEqual(await page.evaluate(()=>calls),[],'failed save must not print');
    assert.equal(await page.locator('#print-btn').isDisabled(),false);
   }
   await page.screenshot({path:require('path').join(require('os').tmpdir(),`${name}-toolbar.png`)});
  }
  console.log('Print controls passed: selected document/day, cancellation, errors and button recovery.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
