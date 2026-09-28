const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    const page = await browser.newPage();
    await page.route(/^https?:/, route => route.abort());
    await page.addInitScript(() => {
      window.pinLookups = [];
      window.pywebview = {api:{get_pinned_card_for_item:async text => {
        window.pinLookups.push(text); return {};
      }}};
    });
    await page.goto(pathToFileURL(path.resolve('apa_web_assets/index.html')).href);
    const raw = 'RICHARD DIXON - State Farm [Final #4243885] [750J2L926]-AARON';
    await page.evaluate(raw => {
      state.doc = {doc_exists:true, sections:[{name:'KIM',count:1,items:[{text:raw}]}]};
      renderBoard();
    }, raw);
    assert.equal(await page.locator('.item-text').innerText(), 'RICHARD DIXON - State Farm-AARON');
    assert.deepEqual(await page.evaluate(() => pinLookups), [raw]);
    assert.equal(await page.locator('.note-btn').getAttribute('data-note-client'), raw);
    assert.equal(await page.evaluate(() => state.doc.sections[0].items[0].text), raw);
    const cases = [
      ['Sample - AAA [Initial #101] - Contents [000123:CON]-AARON', 'Sample - AAA - Contents-AARON'],
      ['Unit 907 - AAA [2026]-AARON', 'Unit 907 - AAA [2026]-AARON'],
      ['Sample - AAA [Final #102] [000123]', 'Sample - AAA'],
    ];
    for (const [text, expected] of cases) {
      const visible = await page.evaluate(text => {
        const div=document.createElement('div'); div.innerHTML=renderItem({text}, 'KIM', 0);
        return div.querySelector('.item-text').textContent;
      }, text);
      assert.equal(visible, expected);
    }
    console.log('PASS: clean APA titles, original pin/note identity retained, unrelated numbers preserved');
  } finally {await browser.close();}
})().catch(e => {console.error(e); process.exitCode=1;});
