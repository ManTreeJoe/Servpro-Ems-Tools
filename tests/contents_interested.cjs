const { chromium } = require('playwright');
const path = require('node:path'), assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.setContent('<div id="status-msg"></div>');
    for (const file of ['web_shared/theme.css', 'web_shared/modal.css', 'pipeline_web_assets/app.css', 'pipeline_web_assets/job_workspace_tabs.css']) await page.addStyleTag({ path: path.resolve(file) });
    for (const file of ['web_shared/modal.js', 'pipeline_web_assets/job_workspace_tabs.js', 'pipeline_web_assets/job_conversation.js', 'pipeline_web_assets/app.js']) await page.addScriptTag({ path: path.resolve(file) });
    await page.evaluate(() => {
      window.saved = [];
      window.pywebview = { api: { save_crm_work_environment: async (...args) => {
        saved.push(args); return { ok: true, job_key: 'example', contents_card: { pending: true } };
      } } };
      openAuditModal({ ok: true, client: 'Example', card_id: 'ems-card', selected_division: 'EMS',
        audit: { ok: true, found: true }, crm: { canon_key: 'example', job_log: [], work_environments: [] },
        comments: [], checklists: [], documents: { files: [] } });
      window.originalTile = document.querySelector('[data-work-type-card="Contents"]');
    });
    await page.locator('[data-work-env="Contents"]').selectOption('interested');
    await page.waitForFunction(() => document.querySelector('[data-job-save-state]').textContent.includes('Linking Contents'));
    assert.deepEqual(await page.evaluate(() => saved[0].slice(0, 3)), ['Example', 'Contents', 'interested']);
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('pipeline:contents-card', { detail: {
      ok: true, job_key: 'example', card_id: 'contents-card', url: 'https://trello.com/c/contents' } })));
    assert.equal(await page.locator('[data-division-trello-open="Contents"]').count(), 1);
    assert.equal(await page.locator('[data-work-env="Contents"]').inputValue(), 'interested');
    assert.equal(await page.evaluate(() => originalTile === document.querySelector('[data-work-type-card="Contents"]')), true);
    assert.deepEqual(errors, []);
    console.log('PASS: Interested saves immediately and background success pins Contents without rebuilding the workspace.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
