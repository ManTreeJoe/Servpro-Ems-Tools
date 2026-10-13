const {chromium}=require('playwright'),assert=require('assert/strict'),path=require('path'),fs=require('fs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1366,height:900}});
  await page.setContent('<html data-theme="dark"><body><main class="audit-modal"><div class="paperwork-list"></div></main></body></html>');
  const root=path.resolve('pipeline_web_assets');
  const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
  for(const match of html.matchAll(/<link[^>]+href="([^"]+\.css)(?:\?[^"]*)?"/g)) {
   await page.addStyleTag({path:path.resolve(root,match[1])});
  }
  await page.addScriptTag({path:path.join(root,'job_forms.js')});
  await page.evaluate(()=>{
   document.querySelector('.paperwork-list').innerHTML=['Auth to Perform','Customer Info Form','Customer Equip Resp','Cert of Satisfaction'].map(label=>`<div class="paperwork-row paperwork-missing"><span class="paperwork-mark">!</span><span><strong>${label}</strong><small>folder audit</small></span><b>Missing</b>${jobFormAction(label,'missing')}</div>`).join('');
  });
  for(const width of [1080,740,340]) {
   await page.locator('main').evaluate((el,width)=>{el.style.cssText=`position:static;width:${width}px;max-width:none;margin:10px;padding:10px;`;},width);
   const bounds=await page.locator('[data-prepare-form]').evaluateAll(buttons=>buttons.map(button=>{
    const rect=button.getBoundingClientRect(),parent=button.parentElement.getBoundingClientRect();
    const range=document.createRange();range.selectNodeContents(button);const text=range.getBoundingClientRect();
    return {button:rect.width,text:text.width,inside:text.left>=parent.left && text.right<=parent.right,overflow:button.scrollWidth>button.clientWidth};
   }));
   assert(bounds.every(b=>b.inside&&!b.overflow),`Clipped form action at ${width}px: ${JSON.stringify(bounds)}`);
   await page.screenshot({path:path.join(require('os').tmpdir(),`oneloss-form-layout-${width}.png`)});
  }
  console.log('PASS form action contained at Snapshot, Jobs and narrow widths');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
