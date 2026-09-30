const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage();
  await page.route('https://inbox.test/**',route=>{
   const file=path.resolve(new URL(route.request().url()).pathname.slice(1));
   if(!fs.existsSync(file))return route.abort();
   let body=fs.readFileSync(file);
   if(file.endsWith('index.html'))body=body.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'');
   return route.fulfill({body,contentType:file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.goto('https://inbox.test/notifications_web_assets/index.html');
  for(const width of [1280,420]) {
   await page.setViewportSize({width,height:700});
   for(const name of ['personal','trello']) {
    const feed=name==='personal'?'personal-feed':'feed';
    await page.evaluate(({name,feed})=>{
     document.querySelector('#personal-panel').hidden=name!=='personal';
     document.querySelector('#trello-panel').hidden=name!=='trello';
     document.getElementById(feed).innerHTML=Array.from({length:80},(_,i)=>`<article class="notif"><div>Notification ${i+1}</div><p>A job update to read.</p></article>`).join('');
    },{name,feed});
    const box=await page.locator('#'+feed).boundingBox();
    await page.mouse.move(box.x+50,Math.min(box.y+100,600));
    await page.mouse.wheel(0,650);
    await page.waitForTimeout(200);
    const state=await page.locator('#'+feed).evaluate(e=>({scroll:e.scrollTop,bottom:e.getBoundingClientRect().bottom,height:innerHeight}));
    assert(state.scroll>0,`${name} inbox must scroll with the mouse wheel at ${width}px: ${JSON.stringify(state)}`);
    assert(state.bottom<=state.height+1,'Feed must stay within window');
    await page.locator('#'+feed).evaluate(e=>e.scrollTop=e.scrollHeight);
    assert(await page.locator('#'+feed+' article').last().evaluate(e=>e.getBoundingClientRect().bottom<=innerHeight),'Last notification reachable');
   }
  }
  console.log('PASS: both inboxes scroll to the last notification at desktop and narrow widths');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
