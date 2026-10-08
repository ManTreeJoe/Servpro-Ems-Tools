const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
// Real Snapshot markup/styles, without backend calls or live job data.
const server=http.createServer((req,res)=>{
  const name=new URL(req.url,'http://local').pathname;
  const file=path.resolve('.'+name);
  if(!file.startsWith(process.cwd()+path.sep)){res.statusCode=403;return res.end();}
  try {
    let data=fs.readFileSync(file,'utf8');
    if(name.endsWith('.html'))data=data.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'');
    res.setHeader('Content-Type',name.endsWith('.css')?'text/css':'text/html');res.end(data);
  }catch{res.statusCode=404;res.end();}
});
(async()=>{
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const origin='http://127.0.0.1:'+server.address().port;
    await page.goto(origin+'/snapshot_web_assets/index.html');
    await page.evaluate(()=>{
      document.querySelectorAll('main.wrap').forEach(el=>el.classList.add('hidden'));
      document.querySelector('#view-gen').classList.remove('hidden');
      document.querySelector('#f-insured').value='Sample restoration job';
    });
    const reference=await browser.newPage();
    await reference.goto(origin+'/pipeline_web_assets/index.html');
    for(const theme of ['dark','light']){
      for(const p of [page,reference])await p.evaluate(t=>document.documentElement.dataset.theme=t,theme);
      const palette=()=>{const s=getComputedStyle(document.documentElement);return Object.fromEntries(['--bg','--surface','--surface-2','--surface-3','--border','--text','--text-muted','--text-dim','--green','--green-hover','--on-accent'].map(k=>[k,s.getPropertyValue(k).trim()]));};
      assert.deepEqual(await page.evaluate(palette),await reference.evaluate(palette),theme+' palette must match job cards');
      const colors=await page.evaluate(()=>{
        const css=selector=>getComputedStyle(document.querySelector(selector));
        const probe=document.createElement('div');document.body.append(probe);
        const token=name=>{probe.style.backgroundColor='var('+name+')';return getComputedStyle(probe).backgroundColor;};
        const result={field:css('#f-insured').backgroundColor,expectedField:token('--surface-2'),panel:css('#snapshot-form-card').backgroundColor,expectedPanel:token('--surface'),button:css('.btn-primary').color,expectedButton:token('--on-accent'),scheme:getComputedStyle(document.documentElement).colorScheme};probe.remove();return result;
      });
      assert.equal(colors.field,colors.expectedField);
      assert.equal(colors.panel,colors.expectedPanel);
      assert.equal(colors.button,colors.expectedButton);
      assert.equal(colors.scheme,theme);
      await page.waitForTimeout(250); // Let shared control color transitions settle.
      await page.screenshot({path:require('node:os').tmpdir()+'/snapshot-theme-'+theme+'.png'});
    }
    console.log('PASS: real Snapshot form matches shared/job-card palette and primary button contrast in dark/light themes');
  }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
