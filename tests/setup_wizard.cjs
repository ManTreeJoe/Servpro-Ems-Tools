// Synthetic markup only: no OneLoss process, credentials, providers or server.
const { chromium } = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    const context = await browser.newContext({serviceWorkers:'block'});
    const requests = [];
    await context.route('**/*', route => {requests.push(route.request().url()); return route.abort();});
    const page = await context.newPage();
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    const html = fs.readFileSync('home_web_assets/index.html','utf8');
    const modal = html.slice(html.indexOf('<div class="fr-overlay'),html.indexOf('<!-- Department switch splash'));
    await page.setContent(`<style>${fs.readFileSync('web_shared/theme.css','utf8')}\n${fs.readFileSync('home_web_assets/app.css','utf8')}</style>${[...html.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(m=>m[0]).join('')}${modal}`);
    await page.addScriptTag({content:fs.readFileSync('home_web_assets/setup_wizard.js','utf8')});
    await page.evaluate(() => {
      window.actions=[]; window.dismissed=false;
      window.steps=[
        {key:'signin',title:'Sign in',done:true},
        {key:'profile_name',title:'Your display name',done:false},
        {key:'franchise',title:'Assigned franchise',done:false},
        {key:'trello',title:'Connect Trello',done:false},
        {key:'companycam',title:'CompanyCam (optional)',done:false,optional:true},
        {key:'folders',title:'Shared folders',done:false},
        {key:'live_data',title:'Check shared data',done:false},
      ].map(s=>({...s,help:'Finish this step, then continue.',detail:'Not verified'}));
      window.bridge={
        first_run:async()=>({show:steps.some(s=>!s.done&&!s.skipped),steps,departments:['TEST'],folders:{},session_dismissed:dismissed}),
        dismiss_first_run:async()=>{dismissed=true;return {ok:true};},
        settings_employee_setup_action:async(name,values)=>{
          actions.push({name,values});
          if(name==='trello') return {ok:false,error:'Authorization unavailable. Ask your administrator.'};
          if(name==='skip_companycam') steps.find(s=>s.key==='companycam').skipped=true;
          else steps.find(s=>s.key===(name==='name'?'profile_name':name)).done=true;
          return {ok:true};
        },
        settings_pick_dir:async()=>({ok:true,path:'C:/Fictional/Shared'}),
      };
      return OneLossSetup.open(bridge);
    });
    assert.equal(await page.locator('[name=email]').count(),0);
    await page.locator('[name=name]').fill('Test Employee');
    await page.locator('#fr-next').click();
    await page.locator('[name=key]').selectOption('TEST');
    await page.locator('#fr-next').click();
    await page.locator('#fr-next').click();
    await page.locator('#fr-error').filter({hasText:'Authorization unavailable'}).waitFor();
    assert.equal(await page.locator('#fr-step h2').textContent(),'Connect Trello');
    await page.evaluate(()=>{steps.find(s=>s.key==='trello').done=true;});
    await page.locator('#fr-recheck').click();
    await page.getByText('Skip optional connection',{exact:true}).click();
    await page.getByText('Choose shared job root',{exact:true}).click();
    assert.equal(await page.locator('[name=job_root]').inputValue(),'C:/Fictional/Shared');
    await page.locator('[name=runs_dir]').fill('C:/Fictional/Runs');
    await page.setViewportSize({width:390,height:700});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    fs.mkdirSync('test-results',{recursive:true});
    await page.screenshot({path:'test-results/setup-wizard-mobile.png'});
    await page.locator('#fr-next').click();
    assert.equal(await page.locator('#fr-step h2').textContent(),'Check shared data');
    await page.locator('#fr-next').click();
    assert.equal(await page.locator('#fr-step h2').textContent(),'Check shared data');
    await page.locator('#fr-later').click();
    await page.evaluate(()=>OneLossSetup.open(bridge));
    assert(await page.locator('#fr-overlay').evaluate(el=>el.classList.contains('hidden')));
    await page.evaluate(()=>{dismissed=false; return OneLossSetup.open(bridge);});
    assert.equal(await page.locator('#fr-step h2').textContent(),'Check shared data');
    await page.evaluate(()=>{steps.find(s=>s.key==='live_data').done=true;});
    await page.locator('#fr-recheck').click();
    await page.getByText('Your workspace is ready',{exact:true}).waitFor();
    await page.locator('#fr-next').click();
    await page.evaluate(()=>{dismissed=false;bridge.first_run=async()=>{throw Error('offline');};return OneLossSetup.open(bridge);});
    await page.locator('#fr-error').filter({hasText:'Setup checks could not load'}).waitFor();
    assert.deepEqual(requests,[]);assert.deepEqual(errors,[]);
    console.log('PASS inline controls, completed-step omission, failed-step blocking, optional skip, folder picker, session dismissal/resume, final check, fail-open retry, mobile layout; zero browser requests/errors');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
