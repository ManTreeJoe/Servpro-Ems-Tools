const { chromium } = require('playwright');
const { execFileSync } = require('node:child_process');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel:'msedge',headless:true});
  try {
    const page = await browser.newPage();
    await page.setContent('<iframe id="content-frame"></iframe><iframe class="tool-workspace-frame"></iframe>');
    await page.evaluate(() => {
      for (const frame of document.querySelectorAll('iframe')) {
        frame.contentWindow.loading = true;
        frame.contentWindow.addEventListener('audit:done', event => {
          frame.contentWindow.loading = false;
          frame.contentWindow.rows = event.detail.rows;
        });
      }
    });
    const script = execFileSync('C:/Users/NathanBupte/AppData/Local/Programs/Python/Python312/python.exe', ['-c',
      "from audit_web import Api; a=Api.__new__(Api); a._window=type('Window',(),{'evaluate_js':lambda self,js:print(js)})(); a._last_rows=[{'client':'Fixture'}]; a._last_meta={}; a._emit_done(ok=True)"], {encoding:'utf8'});
    await page.evaluate(script);
    assert.deepEqual(await page.evaluate(() => Array.from(document.querySelectorAll('iframe'), f => ({loading:f.contentWindow.loading, count:f.contentWindow.rows?.length}))),
      [{loading:false,count:1},{loading:false,count:1}], 'Daily Run workspace must receive completion and stop loading');
    console.log('PASS Daily Run completion reaches both mounted frame types');
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exit(1);});
