const { chromium } = require('playwright');
const path = require('node:path'), assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage();
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.setContent('<div id="status-msg"></div>');
    await page.addScriptTag({ path: path.resolve('pipeline_web_assets/app.js') });
    await page.evaluate(() => {
      window.calls = []; window.linked = 0;
      window.pywebview = { api: { link_ems_card_copy: async (...args) => {
        calls.push(args);
        return calls.length === 1 ? { ok: false, error: 'Use the main Estimating board.' } : { ok: true };
      } } };
      openEmsCopyLinkModal('Example Job', 'original-card', async () => { linked++; });
    });
    await page.locator('[data-copy-link]').fill('https://trello.com/c/copied01');
    await page.locator('[type=submit]').click();
    await page.waitForFunction(() => document.querySelector('[data-message]').textContent.includes('main Estimating'));
    assert.equal(await page.locator('[type=submit]').isEnabled(), true);
    await page.locator('[type=submit]').click();
    await page.waitForFunction(() => window.linked === 1);
    assert.equal(await page.locator('[data-copy-link]').count(), 0);
    assert.deepEqual(await page.evaluate(() => calls[1]), ['Example Job', 'original-card', 'https://trello.com/c/copied01']);
    assert.deepEqual(errors, []);
    console.log('PASS: EMS copy dialog submits the exact pair, displays errors, and closes after linking.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
