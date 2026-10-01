// Read-only visual audit: real page styles, synthetic non-customer content.
const {chromium}=require('playwright'),fs=require('node:fs'),path=require('node:path');
function lum(rgb){return rgb.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0)}
function ratio(a,b){let x=lum(a),y=lum(b);return +((Math.max(x,y)+.05)/(Math.min(x,y)+.05)).toFixed(2)}
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1280,height:800}});
 await page.route('https://audit.test/**',route=>{
  const file=path.resolve(new URL(route.request().url()).pathname.slice(1));
  if(!fs.existsSync(file)||!fs.statSync(file).isFile())return route.abort();
  let body=fs.readFileSync(file);if(file.endsWith('.html'))body=body.toString().replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi,'');
  return route.fulfill({body,contentType:file.endsWith('.css')?'text/css':'text/html'});
 });
 for(const panel of ['pipeline','apa','audit','snapshot','notifications']){
  await page.goto(`https://audit.test/${panel}_web_assets/index.html`);
  for(const theme of ['dark','light']){
   const colors=await page.evaluate(theme=>{
    document.documentElement.dataset.theme=theme;
    const el=document.createElement('span');document.body.append(el);const result={};
    for(const token of ['bg','surface-2','text','text-muted','text-dim','green']){el.style.color=`var(--${token})`;result[token]=getComputedStyle(el).color}el.remove();return result;
   },theme);
   console.log(JSON.stringify({panel,theme,colors,mutedOnCard:ratio(colors['text-muted'],colors['surface-2']),dimOnCard:ratio(colors['text-dim'],colors['surface-2'])}));
  }
 }
 await page.goto('https://audit.test/notifications_web_assets/index.html');
 await page.evaluate(()=>{
  document.documentElement.dataset.theme='dark';document.querySelector('#personal-panel').hidden=true;document.querySelector('#trello-panel').hidden=false;
  document.querySelector('#feed').innerHTML=['Estimating','Work in progress'].map(name=>`<section class="board-group"><div class="board-head"><span class="board-name">${name}</span><span class="board-count">20 unread · 20 total</span></div><ul class="notif-list">${Array.from({length:20},(_,i)=>`<li class="notif unread"><div>●</div><div><div class="notif-card">Example job ${i+1}</div><div class="notif-meta">Comment · Technician</div><div class="notif-snippet">Inspection completed. Please review.</div></div><div class="notif-date">today · 8:55a</div></li>`).join('')}</ul></section>`).join('');
  document.querySelector('#feed').scrollTop=100;
 });
 console.log('sticky',await page.evaluate(()=>{const f=document.querySelector('#feed'),h=f.querySelector('.board-head');return {feedTop:f.getBoundingClientRect().top,headingTop:h.getBoundingClientRect().top,padding:getComputedStyle(f).paddingTop}}));
 await page.screenshot({path:path.join(process.env.TEMP,'oneloss-notification-heading-audit.png')});
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
