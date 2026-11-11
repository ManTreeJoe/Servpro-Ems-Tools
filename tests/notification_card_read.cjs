const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const context = await browser.newContext({ serviceWorkers: 'block' });
    await context.route('**/*', route => route.abort());
    const page = await context.newPage();
    const html = fs.readFileSync('notifications_web_assets/index.html', 'utf8')
      .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '').replace(/<link\b[^>]*>/gi, '');
    await page.setContent(html);
    await page.evaluate(() => {
      const a = 'a'.repeat(24), b = 'b'.repeat(24);
      window.cardCalls = []; window.cleared = false;
      window.PanelState = { init: async () => {}, get: (_, value) => value, set: () => {} };
      window.pywebview = { api: {
        unread_count: async () => ({ ok: true, count: window.cleared ? 1 : 3 }),
        personal_inbox: async () => ({ ok: true, items: [] }),
        list_notifications: async () => ({ ok: true, groups: [{ board: 'Work', items: [
          { id: '1', card_id: a, card_name: 'First job', unread: !window.cleared, snippet: 'One' },
          { id: '2', card_id: a, card_name: 'First job', unread: !window.cleared, snippet: 'Two' },
          { id: '3', card_id: b, card_name: 'Other job', unread: true, snippet: 'Three' },
        ] }] }),
        mark_card_read: async id => { window.cardCalls.push(id); window.cleared = true; return { ok: true }; },
      } };
    });
    for (const name of ['type_filter.js', 'reader.js', 'unified.js'])
      await page.addScriptTag({ path: path.resolve('notifications_web_assets', name) });
    await page.evaluate(() => dispatchEvent(new Event('pywebviewready')));
    const dot = page.getByRole('button', { name: 'Mark all notifications for this card read: First job' });
    await dot.click();
    await page.getByText('Card notifications marked read.').waitFor();
    assert.deepEqual(await page.evaluate(() => window.cardCalls), ['a'.repeat(24)]);
    assert.equal(await dot.count(), 0);
    assert.equal(await page.getByRole('button', { name: 'Mark all notifications for this card read: Other job' }).count(), 1);
    console.log('PASS: card dot clears only its exact group and refreshes the display');
    await context.close();
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
