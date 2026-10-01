const {chromium}=require('playwright'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1480,height:900}});
 page.on('pageerror',e=>console.log('JS error:',e.message));
 page.on('response',r=>{if(r.status()>=400)console.log('HTTP',r.status(),new URL(r.url()).pathname);});
 await page.goto(process.env.DEV_TEST_URL,{waitUntil:'networkidle'});
 const result=await page.evaluate(()=>({base:document.baseURI,sheets:[...document.querySelectorAll('link[rel=stylesheet]')].map(el=>({href:el.href,loaded:!!el.sheet})),sidebarWidth:document.querySelector('.sidebar')?.getBoundingClientRect().width}));
 console.log(JSON.stringify(result));
 await page.screenshot({path:require('os').tmpdir()+'/oneloss-shell-startup.png'});
 assert.ok(result.sheets.every(s=>s.loaded),'All shell stylesheets must load');
 assert.ok(result.sidebarWidth>150 && result.sidebarWidth<400,'Sidebar must remain compact, not full-window');
 console.log('PASS: full shell loads layout styles');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
