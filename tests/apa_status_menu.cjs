const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    await page.route(/^https?:/, route => route.abort());
    await page.addInitScript(() => {
      window.testSaves = [];
      window.pywebview = { api: {
        status_options: async () => ({ statuses: ['pending','uploaded','extended'], subs: ['AARON'], highlight: ['pending'] }),
        get_pinned_card_for_item: async () => ({}),
        get_item_franchise: async () => '', get_franchise_list: async () => [],
        list_sections: async () => ['Initial Uploads','Final Uploads'],
        save_doc: async (date, sections) => {
          window.testSaves.push({ date, sections });
          return { ok: true, doc: { date_iso: date, doc_exists: true, sections } };
        },
      } };
    });
    await page.goto(pathToFileURL(path.resolve('apa_web_assets/index.html')).href);
    await page.evaluate(() => {
      state.doc = { date_iso: '2026-09-18', doc_exists: true, sections: [
        { name: 'Initial Uploads', items: [{ text: 'Synthetic Customer - AAA-AARON-pending', highlighted: true }], count: 1 },
        { name: 'Final Uploads', items: [], count: 0 },
      ] };
      renderBoard();
    });
    const item = page.locator('[data-section="Initial Uploads"][data-index="0"]');
    await item.click({ button: 'right' });
    const parent = page.locator('#apa-ctx-menu .apa-ctx-sub').filter({ hasText: 'Status' });
    await parent.hover();
    assert.equal(await page.locator('.apa-ctx-submenu').count(), 1);
    // Reproduce WebView2 crossing between separate fixed-position surfaces:
    // relatedTarget is null before the submenu receives mouseenter.
    await parent.evaluate(el => el.dispatchEvent(new MouseEvent('mouseleave', { relatedTarget: null })));
    assert.equal(await page.locator('.apa-ctx-submenu').count(), 1,
      'Status flyout vanished before the pointer could reach an option');
    await page.locator('.apa-ctx-submenu').dispatchEvent('mouseenter');
    await page.waitForTimeout(350);
    assert.equal(await page.locator('.apa-ctx-submenu').count(), 1, 'entering the submenu cancels delayed closure');
    await page.locator('.apa-ctx-submenu button').filter({ hasText: /^\s*uploaded$/ }).click();
    await page.waitForFunction(() => window.testSaves.length === 1);
    const saved = await page.evaluate(() => window.testSaves[0]);
    assert.equal(saved.sections[0].items[0].text, 'Synthetic Customer - AAA-AARON-uploaded');
    assert.equal(saved.sections[0].items[0].highlighted, false);
    assert.equal(await page.locator('.apa-ctx-submenu').count(), 0);
    // The edit-dialog path must also preserve the selected status after save.
    await item.click();
    await page.locator('#apa-edit-status').selectOption('extended');
    await page.locator('#apa-pop-save').click();
    await page.waitForFunction(() => window.testSaves.length === 2);
    assert.equal(await page.evaluate(() => window.testSaves[1].sections[0].items[0].text),
      'Synthetic Customer - AAA-AARON-extended');
    console.log('PASS: production APA status flyout stays reachable and saves the selected status');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
