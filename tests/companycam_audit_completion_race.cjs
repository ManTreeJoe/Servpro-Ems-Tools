// A fast worker must not finish before Jobs starts listening. No provider calls.
const { chromium } = require('playwright');
const path = require('node:path'), assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage();
    await page.route('http://localhost/**', route => route.fulfill({
      contentType: 'text/html', body: '<div id="status-msg"></div>'
    }));
    await page.goto('http://localhost/');
    await page.addScriptTag({path: path.resolve('pipeline_web_assets/app.js')});
    await page.evaluate(async () => {
      window.pywebview = {api: {
        companycam_plan_pull: async () => ({ok: true, project_id: 'fixture', missing: 1,
          groups: [{stage: 'Initial', date: '2026-09-22', tech: 'AT', count: 1,
            photo_ids: ['p1'], rooms: [], current_tags: ['Initial']}]}),
        companycam_pull_assigned_bg: async (...args) => {
          window.dispatchEvent(new CustomEvent('companycam:pull-done', {detail: {
            client: 'Audit fixture', operation_id:args[5], ok: true, pulled: 1, skipped: 0
          }}));
          return {ok: true, total: 1};
        }
      }};
      await openCompanyCamPullModal({client: 'Audit fixture', card_id: 'fake'}, {});
    });
    await page.locator('[data-start-pull]').click();
    const status = await page.locator('#status-msg').innerText();
    assert.match(status, /import complete.*1 pulled/);
    console.log('PASS: fast completion is retained, not overwritten by the start acknowledgement');
    await page.evaluate(() => {
      window.testWatcher = watchCompanyCamPull('Same customer', 'ems', 'ems-operation');
      window.dispatchEvent(new CustomEvent('companycam:pull-done', {detail:{
        client:'Same customer', operation_id:'contents-operation', ok:true, pulled:900
      }}));
    });
    assert.equal(await page.evaluate(() => window.testWatcher.finished), false);
    await page.evaluate(() => window.testWatcher.stop());
    console.log('PASS: a different card operation cannot complete this watcher');
    await page.evaluate(async () => {
      pywebview.api.companycam_import_status = async () => ({ok:true, found:true,
        state:'complete', operation_id:'saved', result:{ok:true, pulled:47, skipped:2}});
      pywebview.api.companycam_plan_pull = async () => {throw new Error('Reopening status must not relist photos');};
      await openCompanyCamPullModal({client:'Audit fixture', card_id:'fake'}, {});
    });
    assert.match(await page.locator('.cc-pull-body').innerText(), /Last import complete.*47 pulled.*2 skipped/);
    console.log('PASS: reopening shows the saved result without listing or importing again');
    await page.locator('[data-close]').click();
    await page.evaluate(async () => {
      pywebview.api.companycam_import_status = async () => ({ok:true, found:false});
      pywebview.api.companycam_plan_pull = async () => ({ok:false, error:'Photo list timed out'});
      await openCompanyCamPullModal({client:'Audit fixture', card_id:'fake'}, {});
    });
    assert.equal(await page.locator('[data-choose-job-folder]').count(), 0);
    assert.equal(await page.locator('[data-retry-cc-preview]').count(), 1);
    await page.locator('[data-close]').click();
    await page.evaluate(async () => {
      pywebview.api.companycam_plan_pull = async () => ({ok:false, recovery:'folder', error:'No folder'});
      await openCompanyCamPullModal({client:'Audit fixture', card_id:'fake'}, {});
    });
    assert.equal(await page.locator('[data-choose-job-folder]').count(), 1);
    console.log('PASS: folder recovery is offered for folder failures, not photo-list timeouts');
    await page.evaluate(() => {
      pywebview.api.companycam_import_status = async () => ({ok:true, found:true,
        state:'complete', result:{ok:true, pulled:5}});
      watchCompanyCamPull('Lost event fixture', 'card', 'lost-event');
    });
    await page.waitForFunction(() => document.querySelector('#status-msg').textContent.includes('5 pulled'), {timeout:10000});
    console.log('PASS: saved completion recovers even when no completion event arrives');
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exit(1);});
