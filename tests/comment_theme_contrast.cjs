const {chromium}=require('playwright'),path=require('node:path'),assert=require('node:assert/strict');
function lum(rgb){const c=rgb.match(/[\d.]+/g).slice(0,3).map(v=>{v=Number(v)/255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4});return .2126*c[0]+.7152*c[1]+.0722*c[2]}
function ratio(a,b){const x=lum(a),y=lum(b);return(Math.max(x,y)+.05)/(Math.min(x,y)+.05)}
(async()=>{const b=await chromium.launch({channel:'msedge',headless:true});try{const p=await b.newPage();await p.setContent('<div class="job-card-activity" style="width:380px"><div class="activity-head"><h3>Comments and activity</h3></div><div class="comment-division-controls"><button aria-pressed="true">EMS</button><button>Contents</button></div></div>');
for(const file of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css'])await p.addStyleTag({path:path.resolve(file)});
await p.evaluate(()=>document.documentElement.dataset.theme='dark');
const pairs=await p.evaluate(()=>{const r=getComputedStyle(document.documentElement);const color=v=>{const el=document.createElement('i');el.style.color=r.getPropertyValue(v);document.body.append(el);const c=getComputedStyle(el).color;el.remove();return c};return ['--bg','--surface','--surface-2','--surface-3'].flatMap(bg=>['--text','--text-muted','--text-dim'].map(fg=>[fg,bg,color(fg),color(bg)]))});
for(const [fg,bg,a,c]of pairs)assert.ok(ratio(a,c)>=4.5,`${fg} on ${bg}: ${ratio(a,c)}`);
for(const button of await p.locator('.comment-division-controls button').all()){const colors=await button.evaluate(el=>{const s=getComputedStyle(el);return[s.color,s.backgroundColor,s.borderColor]});assert.ok(ratio(colors[0],colors[1])>=4.5);assert.ok(ratio(colors[2],'rgb(32,35,40)')>=3);}
assert.equal(await p.evaluate(()=>document.querySelector('.comment-division-controls button').getBoundingClientRect().top-document.querySelector('.activity-head').getBoundingClientRect().bottom),14);
console.log('PASS: dark base text pairs >=4.5:1, control boundaries >=3:1, 14px header spacing');
}finally{await b.close()}})().catch(e=>{console.error(e);process.exitCode=1});
