const {chromium}=require('playwright');
const assert=require('node:assert/strict'), path=require('node:path'), os=require('node:os');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  await page.setContent('<main id="schedule"></main>');
  await page.addStyleTag({path:path.resolve('web_shared/theme.css')});
  await page.addStyleTag({path:path.resolve('run_doc_editor_web_assets/weekly_calendar.css')});
  await page.addScriptTag({path:path.resolve('run_doc_editor_web_assets/weekly_calendar.js')});
  await page.evaluate(()=>{
   window.events=[];
   window.records=[
    {id:'work-1',title:'Example residence',queue:'scheduled',date:'2026-10-02',time:'9 AM',activities:[{label:'Demo',people:['Sam']},{label:'Monitor',people:['Alex']}]},
    {id:'weekend',title:'Weekend visit',queue:'scheduled',date:'2026-10-04',activities:[]},
    {id:'pending',title:'Approval needed',queue:'pending',since:'2026-09-28',activities:[]},
    {id:'tbs',title:'Schedule inspection',queue:'tbs',since:'2026-09-29',activities:[]},
    {id:'escaped',title:'<img src=x onerror="window.bad=true">',queue:'tbs',activities:[]}
   ];
   window.calendar=OneLossWeeklyCalendar.mount(document.querySelector('#schedule'),{
    date:'2026-10-02',period:'week',today:()=> '2026-10-02',onEdit:id=>events.push(['edit',id]),
    onAdd:day=>events.push(['add',day]),onRangeChange:range=>events.push(['range',range]),onRetry:()=>events.push(['retry'])
   });
   calendar.update({records});
  });
  assert.equal(await page.locator('.wc-day').count(),7);
  assert.equal(await page.locator('.wc-week .wc-visit').count(),2);
  await page.locator('[data-edit="work-1"]').click();
  await page.locator('[data-add="2026-10-04"]').click();
  assert.deepEqual(await page.evaluate(()=>events.slice(0,2)),[['edit','work-1'],['add','2026-10-04']]);
  await page.getByRole('button',{name:'Legacy view',exact:true}).click();
  assert.equal(await page.locator('.wc-legacy [data-edit="work-1"]').count(),1);
  await page.evaluate(()=>{records[0].title='Updated in host';calendar.update({records});});
  assert.equal(await page.locator('.wc-legacy strong').textContent(),'Updated in host');
  await page.getByRole('button',{name:'Back to calendar'}).click();
  assert.equal(await page.locator('[data-edit="work-1"] strong').textContent(),'Updated in host');
  await page.getByRole('button',{name:'Next week'}).click();
  assert.equal(await page.locator('[data-day="2026-10-05"]').count(),1);
  assert.equal(await page.locator('.wc-week .wc-visit').count(),0);
  await page.getByRole('button',{name:'Pending (1)',exact:true}).click();
  assert.match(await page.locator('.wc-queue').textContent(),/Since 09\/28\/26/);
  await page.getByRole('button',{name:'To be scheduled (2)',exact:true}).click();
  assert.equal(await page.locator('.wc-queue img').count(),0);
  await page.getByRole('searchbox').fill('inspection');
  assert.equal(await page.locator('.wc-visit').count(),1);
  await page.getByRole('searchbox').fill('');
  await page.evaluate(()=>calendar.update({loading:true}));
  assert.equal(await page.getByRole('status').textContent(),'Loading schedule…');
  await page.evaluate(()=>calendar.update({loading:false,error:'Unavailable'}));
  await page.getByRole('button',{name:'Retry',exact:true}).click();
  assert.deepEqual(await page.evaluate(()=>events.at(-1)),['retry']);
  await page.evaluate(()=>calendar.update({error:''}));
  await page.locator('button[data-period="week"]').click();
  await page.getByRole('button',{name:'Today',exact:true}).click();
  assert.deepEqual(await page.evaluate(()=>OneLossWeeklyCalendar.week('2026-12-31')),['2026-12-28','2026-12-29','2026-12-30','2026-12-31','2027-01-01','2027-01-02','2027-01-03']);
  assert.equal(await page.evaluate(()=>{try{OneLossWeeklyCalendar.week('2026-02-30');return false;}catch{return true;}}),true);
  await page.screenshot({path:path.join(os.tmpdir(),'oneloss-weekly-calendar-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  await page.evaluate(()=>calendar.update({}));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  assert.equal(await page.evaluate(()=>document.querySelector('.wc-content').scrollLeft>0),true);
  await page.screenshot({path:path.join(os.tmpdir(),'oneloss-weekly-calendar-mobile.png')});
  await page.setViewportSize({width:1440,height:900});
  await page.evaluate(()=>{document.documentElement.dataset.theme='dark';calendar.update({});});
  await page.screenshot({path:path.join(os.tmpdir(),'oneloss-weekly-calendar-dark.png')});
  await page.evaluate(()=>calendar.destroy());
  assert.equal(await page.locator('#schedule').textContent(),'');
  console.log('PASS: weekly view, weekend add/edit callbacks, shared Legacy records, queues, search, loading/error/retry, date boundaries, escaping, narrow layout, cleanup');
 } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
