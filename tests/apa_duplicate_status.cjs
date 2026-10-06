// Exercise the production menu against identical row text and refresh races.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    const page = await browser.newPage();
    await page.route(/^https?:/, r => r.abort());
    await page.addInitScript(() => {
      window.saves = [];
      window.pywebview = {api:{
        status_options: async () => ({statuses:['pending','uploaded'], subs:[], highlight:[]}),
        get_pinned_card_for_item: async () => ({}),
        save_doc: async (date, sections) => {
          saves.push(structuredClone(sections));
          return {ok:true, doc:{date_iso:date, doc_exists:true, sections}};
        },
      }};
    });
    await page.goto(pathToFileURL(path.resolve('apa_web_assets/index.html')).href);
    for (const scenario of ['duplicate', 'reorder', 'unique-refresh', 'duplicate-refresh', 'in-place-edit', 'date-change']) {
      await page.evaluate(async scenario => {
        saves.length = 0;
        const duplicate = ['duplicate','reorder','duplicate-refresh'].includes(scenario);
        const items = [{text:'Fixture - AAA-JUAN-pending'}];
        if (duplicate) items.push({...items[0]});
        state.doc = {date_iso:'2026-10-05', doc_exists:true,
          sections:[{name:'Audit Rejection', count:items.length, items}]};
        renderBoard();
        const target = document.querySelectorAll('.item')[duplicate ? 1 : 0];
        await openApaItemCtxMenu({preventDefault(){}, stopPropagation(){}, clientX:20, clientY:20}, target);
        if (scenario.endsWith('-refresh')) state.doc = structuredClone(state.doc);
        if (scenario === 'reorder') items.reverse();
        if (scenario === 'in-place-edit') items[0].text = 'Different job-JUAN-pending';
        if (scenario === 'date-change') state.doc.date_iso = '2026-10-06';
      }, scenario);
      await page.locator('#apa-ctx-menu .apa-ctx-sub').filter({hasText:'Status'}).hover();
      await page.locator('.apa-ctx-submenu button').filter({hasText:/^\s*uploaded$/}).click();
      const allowed = ['duplicate','reorder','unique-refresh'].includes(scenario);
      if (allowed) await page.waitForFunction(() => saves.length === 1, null, {timeout:3000});
      const saved = await page.evaluate(() => saves);
      assert.equal(saved.length, allowed ? 1 : 0, scenario);
      if (allowed) {
        const index = scenario === 'duplicate' ? 1 : 0;
        assert.equal(saved[0][0].items[index].text, 'Fixture - AAA-JUAN-uploaded', scenario);
        if (scenario !== 'unique-refresh')
          assert.equal(saved[0][0].items[1-index].text, 'Fixture - AAA-JUAN-pending', 'Other duplicate must stay unchanged');
      }
    }
    console.log('PASS: exact duplicate row edits; reorder safe; real/ambiguous changes blocked');
  } finally { await browser.close(); }
})().catch(e => {console.error(e); process.exitCode=1;});
