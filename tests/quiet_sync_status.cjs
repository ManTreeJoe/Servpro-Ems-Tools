const { chromium } = require('playwright');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage();
    await page.setContent('<div id="background-sync-state"><span></span></div>');
    await page.addScriptTag({path: path.resolve('pipeline_web_assets/app.js')});
    await page.evaluate(() => {
      refreshSavedBoardInBackground = async () => {};
      refreshOpenWorkspaceComments = async () => {};
      updateBackgroundSyncIndicator();
    });
    const badge = page.locator('#background-sync-state');
    await assert.equal(await badge.innerText(), 'Checking sync');
    await page.evaluate(() => onBackgroundSyncDone({detail: {
      ok: true, mode: 'direct', queue_reason: 'schema_missing', at: new Date().toISOString()
    }}));
    assert.equal(await badge.innerText(), 'Trello connected');
    assert.match(await badge.getAttribute('title'), /Shared background write queue is not enabled/);
    await page.evaluate(() => onBackgroundSyncDone({detail: {ok: false, error: 'Trello timed out'}}));
    assert.equal(await badge.innerText(), 'Sync needs attention');
    assert.match(await badge.getAttribute('title'), /Trello timed out/);
    await page.evaluate(() => onBackgroundSyncDone({detail: {ok: true, mode: 'shared'}}));
    assert.equal(await badge.innerText(), 'Hub current');
    console.log('PASS: direct mode, shared mode and genuine sync failures are distinguished.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
