const { chromium } = require('playwright');
const path = require('node:path'), assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage();
    await page.route('http://localhost/**', route => route.fulfill({
      contentType: 'text/html', body: '<div id="status-msg"></div>'
    }));
    await page.goto('http://localhost/');
    await page.addScriptTag({ path: path.resolve('pipeline_web_assets/app.js') });
    await page.addStyleTag({ path: path.resolve('pipeline_web_assets/app.css') });
    await page.evaluate(() => {
      window.pywebview = { api: { companycam_plan_pull: (...args) => {
        window.request = args[4];
        return new Promise(resolve => { window.finishPlan = resolve; });
      } } };
      openCompanyCamPullModal({ client: 'Example', card_id: 'card' }, {});
    });
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('companycam:plan-progress', { detail: {
      request_id: 'another-window', phase: 'photos', total: 99, shoots: []
    } })));
    assert.equal(await page.locator('.cc-pull-body').innerText().then(t => t.includes('99')), false);
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('companycam:plan-progress', { detail: {
      request_id: request, phase: 'photos', total: 20,
      shoots: [{ date: '2026-09-22', tech: 'AT', count: 20 }]
    } })));
    assert.match(await page.locator('.cc-pull-body').innerText(), /20 photos · AT/);
    assert.equal(await page.locator('[data-start-pull]').count(), 0);
    await page.evaluate(() => finishPlan({ ok: true, total: 20, missing: 0 }));
    await page.waitForFunction(() => document.querySelector('.cc-pull-body').textContent.includes('already filed'));
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('companycam:plan-progress', { detail: {
      request_id: request, phase: 'photos', total: 99, shoots: []
    } })));
    assert.match(await page.locator('.cc-pull-body').innerText(), /All 20 photos are already filed/);
    await page.locator('[data-close]').click();
    await page.evaluate(async () => {
      pywebview.api.companycam_plan_pull = async () => ({
        ok: true, project_id: 'exact-preview-project', missing: 1, groups: [{
          stage: '', date: '2026-09-22', tech: 'AT', count: 1,
          photo_ids: ['p1'], rooms: [], current_tags: ['Initial']
        }]
      });
      pywebview.api.companycam_pull_assigned_bg = async (...args) => {
        window.importArgs = args;
        return {ok: false, error: 'Test: no real download'};
      };
      await openCompanyCamPullModal({client: 'Silvia Fenney', card_id: 'card'}, {});
    });
    assert.deepEqual(await page.locator('[data-cc-stage] option').evaluateAll(nodes => nodes.map(n => n.value).filter(Boolean)),
      ['Initial','Demo','Monitor','Abatement Prep','Mold Prep','Reinspection','Contents','Scope','Post','Cleaning']);
    await page.locator('[data-cc-stage]').selectOption('Cleaning');
    await page.locator('[data-start-pull]').click();
    assert.equal(await page.evaluate(() => importArgs[4]), 'exact-preview-project');
    await page.locator('[data-close]').click();
    await page.evaluate(async () => {
      pywebview.api.companycam_plan_pull = async (...args) => {
        if (args[5]) {
          window.reviewArgs = args;
          window.reviewAttempts = (window.reviewAttempts || 0) + 1;
          if (window.reviewAttempts === 1) return {ok:false,error:'Selected photo tags could not be verified (TimeoutError). No photos imported; retry the review.'};
          return {ok:true, project_id:args[6], missing:1, groups:[{
            stage:'Initial', date:'2026-09-22', tech:'AT', count:1,
            photo_ids:args[5], rooms:[], current_tags:['Initial']
          }]};
        }
        return {ok:true, project_id:'exact-visit-project', preview_id:'exact-preview-token', missing:2, tags_pending:true,
          groups:[{date:'2026-09-22',tech:'AT',count:1,photo_ids:['chosen']},
                  {date:'2026-09-21',tech:'BT',count:1,photo_ids:['not-chosen']}]};
      };
      await openCompanyCamPullModal({client:'Visit fixture',card_id:'card'},{});
    });
    assert.equal(await page.locator('[data-start-pull]').count(),0);
    assert.equal(await page.locator('[data-review-visits]').isDisabled(),true);
    await page.screenshot({path:path.join(require('node:os').tmpdir(), 'oneloss-cc-visits.png')});
    await page.locator('[data-cc-visit="0"]').check();
    await page.locator('[data-review-visits]').click();
    await page.waitForFunction(()=>document.querySelector('[data-review-status]').textContent.includes('TimeoutError'));
    assert.equal(await page.locator('[data-cc-visit="0"]').isChecked(),true);
    assert.equal(await page.locator('[data-review-visits]').isDisabled(),false);
    await page.locator('[data-review-visits]').click();
    await page.waitForSelector('[data-start-pull]');
    assert.deepEqual(await page.evaluate(() => reviewArgs[5]), ['chosen']);
    assert.equal(await page.evaluate(() => reviewArgs[6]), 'exact-visit-project');
    assert.equal(await page.evaluate(() => reviewArgs[8]), 'exact-preview-token');
    assert.equal(await page.locator('[data-start-pull]').isDisabled(),false);
    await page.locator('[data-close]').click();
    await page.evaluate(async () => {
      await openCompanyCamPullModal({client:'Run suggestion fixture',card_id:'card'}, {}, {
        ok:true, project_id:'project', missing:1, groups:[{
          stage:'', suggested_stage:'Post', suggested_from:'run doc', date:'09-24-2026',
          tech:'AT', count:1, photo_ids:['fixture'], current_tags:[]
        }]
      });
    });
    assert.equal(await page.locator('[data-cc-stage]').inputValue(), 'Post');
    await page.locator('[data-cc-stage]').selectOption('Demo');
    assert.equal(await page.locator('[data-cc-stage]').inputValue(), 'Demo');
    console.log('PASS: Daily Run suggestion is preselected and remains editable.');
    console.log('PASS: early technician preview, request isolation, no premature import, final state retained.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
