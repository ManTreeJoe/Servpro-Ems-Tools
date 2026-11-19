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
    await page.setViewportSize({width:1000,height:800});
    fs.mkdirSync('test-results',{recursive:true});
    const shot = async name => {
      const current = await page.evaluate(() => steps.find(s => !s.done && !s.skipped));
      const text = await page.locator('#fr-overlay').innerText();
      assert(!text.includes('Finish this step'));
      if (current) {
        assert(text.includes(current.help), `Missing help for ${current.key}`);
        assert.equal(await page.locator('.setup-instruction').textContent(),current.help);
        const index = await page.evaluate(() => steps.findIndex(s => !s.done && !s.skipped));
        assert(text.includes(`Step ${index + 1} of 7`));
        assert.equal(await page.locator('.setup-dots span').count(),7);
      }
      await page.screenshot({path:`test-results/${name}.png`});
    };
    // Copy only literal instruction text from status source; never import Python.
    const source = fs.readFileSync('employee_setup.py','utf8');
    const prefixes = ['Use your work email', 'Enter the name coworkers', 'Choose an assignment',
      'Select Connect Trello', 'Connect your work account', 'Connect to the office network', 'Finish the required steps'];
    const helps = prefixes.map(prefix => {
      const literal = [...source.matchAll(/"[^"\n]*"/g)].map(m=>m[0]).find(value=>value.startsWith('"'+prefix));
      assert(literal, `Missing status instruction: ${prefix}`);
      return JSON.parse(literal);
    });
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    const html = fs.readFileSync('home_web_assets/index.html','utf8');
    const modal = html.slice(html.indexOf('<div class="fr-overlay'),html.indexOf('<!-- Department switch splash'));
    await page.setContent(`<style>${fs.readFileSync('web_shared/theme.css','utf8')}\n${fs.readFileSync('home_web_assets/app.css','utf8')}</style>${[...html.matchAll(/<style>([\s\S]*?)<\/style>/g)].map(m=>m[0]).join('')}${modal}`);
    await page.addScriptTag({content:fs.readFileSync('home_web_assets/setup_wizard.js','utf8')});
    await page.evaluate(helps => {
      window.actions=[]; window.dismissed=false;
      window.steps=[
        {key:'signin',title:'Sign in',done:false},
        {key:'profile_name',title:'Your display name',done:false},
        {key:'franchise',title:'Assigned franchise',done:false},
        {key:'trello',title:'Connect Trello',done:false},
        {key:'companycam',title:'CompanyCam (optional)',done:false,optional:true},
        {key:'folders',title:'Shared folders',done:false},
        {key:'live_data',title:'Check shared data',done:false},
      ].map((s,i)=>({...s,help:helps[i],detail:'Not verified'}));
      window.bridge={
        first_run:async()=>({show:steps.some(s=>!s.done&&!s.skipped),steps:structuredClone(steps),departments:['TEST'],folders:{},session_dismissed:dismissed}),
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
    }, helps);
    assert(!(await page.locator('#fr-overlay').innerText()).includes('Not verified'));
    await shot('01-signin');
    await page.locator('[name=email]').fill('employee@example.invalid');
    await page.locator('[name=password]').fill('synthetic-only');
    await page.locator('#fr-next').click();
    assert.equal(await page.locator('[name=email]').count(),0);
    await shot('02-display-name');
    await page.locator('[name=name]').fill('Test Employee');
    await page.locator('#fr-next').click();
    await shot('03-franchise');
    await page.locator('[name=key]').selectOption('TEST');
    await page.locator('#fr-next').click();
    assert(!(await page.locator('#fr-overlay').innerText()).includes('Not verified'));
    await page.locator('#fr-next').click();
    await page.locator('#fr-error').filter({hasText:'Authorization unavailable'}).waitFor();
    assert.equal(await page.locator('#fr-step h2').textContent(),'Connect Trello');
    assert((await page.locator('#fr-overlay').innerText()).includes('Not verified'));
    await shot('04-trello');
    await page.evaluate(()=>{steps.find(s=>s.key==='trello').done=true;});
    await page.locator('#fr-recheck').click();
    assert(!(await page.locator('#fr-overlay').innerText()).includes('Not verified'));
    await shot('05-companycam');
    await page.getByText('Skip optional connection',{exact:true}).click();
    await page.getByText('Choose shared job root',{exact:true}).click();
    assert.equal(await page.locator('[name=job_root]').inputValue(),'C:/Fictional/Shared');
    await page.locator('[name=runs_dir]').fill('C:/Fictional/Runs');
    await shot('06-folders');
    await page.setViewportSize({width:390,height:700});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    fs.mkdirSync('test-results',{recursive:true});
    await page.screenshot({path:'test-results/setup-wizard-mobile.png'});
    await page.setViewportSize({width:1000,height:800});
    await page.locator('#fr-next').click();
    await shot('07-live-data');
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
    assert.deepEqual(await page.locator('#fr-overlay button:visible').allTextContents(), ['Start working']);
    await shot('08-all-done');
    await page.locator('#fr-next').click();
    await page.evaluate(()=>{dismissed=false;bridge.first_run=async()=>{throw Error('offline');};return OneLossSetup.open(bridge);});
    await page.locator('#fr-error').filter({hasText:'Setup checks could not load'}).waitFor();
    assert.deepEqual(requests,[]);assert.deepEqual(errors,[]);
    console.log('PASS inline controls, completed-step omission, failed-step blocking, optional skip, folder picker, session dismissal/resume, final check, fail-open retry, mobile layout; zero browser requests/errors');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
