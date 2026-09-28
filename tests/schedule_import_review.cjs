const {chromium} = require('playwright');
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:900}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    const html = fs.readFileSync('run_doc_editor_web_assets/index.html','utf8')
      .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'').replace(/<link\b[^>]*>/g,'');
    await page.setContent(html);
    await page.evaluate(()=>document.documentElement.dataset.theme='dark');
    for (const file of ['web_shared/theme.css','run_doc_editor_web_assets/app.css','run_doc_editor_web_assets/schedule_visits.css','run_doc_editor_web_assets/schedule_workspace.css'])
      await page.addStyleTag({path:path.resolve(file)});
    for (const file of ['schedule_fields.js','visit_controls.js','app.js'])
      await page.addScriptTag({path:path.resolve('run_doc_editor_web_assets',file)});
    await page.evaluate(() => {
      window.PanelState = {set(){}};
      state.model = {ok:true, editable:true, exists:true, date_iso:'2026-09-18', department:'IE', version:'v1',
        sections:{monitor:[{text:'Example job: monitor equipment',struck:false}],on_hold:[]}, section_order:['monitor','on_hold']};
      document.querySelector('#run-board').classList.remove('hidden'); renderRows();
    });
    const rowHeight = await page.locator('.run-row').evaluate(row => row.getBoundingClientRect().height);
    assert.ok(rowHeight < 140, `A one-line Run without an arrival time is ${rowHeight}px tall`);
    await page.addStyleTag({path:path.resolve('run_doc_editor_web_assets/import_review.css')});
    await page.addScriptTag({path:path.resolve('run_doc_editor_web_assets/import_review.js')});
    await page.evaluate(() => {
      PanelState.init = async () => {}; PanelState.get = (key, fallback) => fallback;
      window.previewResult = {ok:true, preview_only:true, can_apply:false, workspace:'IE',run_date:'2026-09-18',source_version:'v1',
        source_filename:'Friday Run.docx',section_labels:{monitor:'Monitor',on_hold:'On Hold'},
        paragraphs:[{raw_text:'SERVPRO DAILY RUN'},{raw_text:''},{raw_text:'Monitor'}], tables:[],blockers:[],
        visits:[{section:'monitor',raw_text:'Example job: monitor equipment',source_paragraph:3,proposed_date:'2026-09-18'},
          {section:'on_hold',raw_text:'Example waiting job: insurance approval',source_paragraph:6,proposed_date:null,struck:true},
          {section:'on_hold',raw_text:'<img src=x onerror="window.unsafe=true">',source_paragraph:7,proposed_date:null}]};
      window.previewCalls=[];
      window.pywebview={api:{load_day:async()=>structuredClone(state.model),preview_schedule_import:async(...args)=>{
        previewCalls.push(args);return structuredClone(previewResult);
      },save_day:async()=>{throw new Error('Preview must never save');}}};
      window.dispatchEvent(new Event('pywebviewready'));
    });
    const opener = page.locator('#review-schedule-import');
    await opener.click();
    const modal = page.locator('.schedule-import-review');
    await page.locator('[data-import-row]').first().waitFor();
    assert.equal(await page.locator('[data-import-row]').count(),3);
    assert.deepEqual(await page.evaluate(()=>previewCalls[0]),[0,'2026-09-18','IE']);
    assert.equal(await page.evaluate(()=>window.unsafe),undefined);
    assert.equal(await modal.locator('img').count(),0);
    await page.locator('[data-import-filter]').selectOption('waiting');
    assert.equal(await page.locator('[data-import-row]').count(),2);
    assert.equal(await page.locator('.import-review-date').first().innerText(),'Not scheduled');
    await page.locator('[data-import-search]').fill('insurance');
    assert.equal(await page.locator('[data-import-row]').count(),1);
    assert.match(await page.locator('[data-import-row]').innerText(),/Crossed out in Run/);
    await page.locator('[data-import-search]').fill('not present');
    assert.equal(await page.locator('.import-review-no-results').isVisible(),true);
    await page.locator('[data-import-search]').fill('');
    await page.locator('[data-import-filter]').selectOption('all');
    await page.screenshot({path:path.join(require('node:os').tmpdir(),'linguar-schedule-import-dark.png')});
    await page.evaluate(()=>document.documentElement.dataset.theme='light');
    await page.screenshot({path:path.join(require('node:os').tmpdir(),'linguar-schedule-import-light.png')});
    await page.setViewportSize({width:390,height:844});
    assert.ok(await modal.evaluate(node=>node.scrollWidth<=node.clientWidth));
    assert.ok(await page.locator('.import-review-body').evaluate(node=>node.scrollWidth<=node.clientWidth));
    await page.screenshot({path:path.join(require('node:os').tmpdir(),'linguar-schedule-import-narrow.png')});
    await page.mouse.click(1,1);
    assert.equal(await modal.isVisible(),true,'Backdrop click must not close the preview');
    await page.keyboard.press('Escape');
    assert.equal(await modal.isVisible(),false);
    assert.equal(await opener.evaluate(node=>node===document.activeElement),true);
    await page.setViewportSize({width:1280,height:900});
    await page.evaluate(()=>{state.dirty=true; previewResult.source_version='v2';});
    await opener.click(); await page.locator('[data-import-row]').first().waitFor();
    assert.match(await page.locator('[data-import-warning]').innerText(),/unsaved/);
    assert.match(await page.locator('[data-import-warning]').innerText(),/Word file changed/);
    assert.equal(await page.evaluate(()=>state.model.version),'v1');
    assert.equal(await page.evaluate(()=>state.dirty),true);
    await page.locator('[data-import-close]').click();
    await page.evaluate(()=>{previewResult={ok:false,error:'Shared folder unavailable'};});
    await opener.click(); await page.locator('[data-import-retry]').waitFor();
    assert.match(await page.locator('[data-import-message]').innerText(),/Shared folder unavailable/);
    await page.evaluate(()=>{previewResult={ok:true,workspace:'IE',run_date:'2026-09-18',visits:[],paragraphs:[]};});
    await page.locator('[data-import-retry]').click();
    await page.locator('.import-review-no-results').waitFor();
    await page.locator('[data-import-close]').click();
    await page.evaluate(()=>{pywebview.api.preview_schedule_import=()=>new Promise(resolve=>window.finishPreview=resolve);});
    await opener.click();
    await page.waitForFunction(()=>typeof window.finishPreview==='function');
    await page.locator('[data-import-close]').click();
    await page.evaluate(()=>finishPreview({...previewResult,visits:[{section:'on_hold',raw_text:'Late reply'}]}));
    assert.equal(await modal.isVisible(),false);
    await page.evaluate(()=>{window.finishPreview=null;});
    await opener.click();
    await page.waitForFunction(()=>typeof window.finishPreview==='function');
    await page.evaluate(()=>{state.model.department='OC';finishPreview(previewResult);});
    await page.locator('[data-import-retry]').waitFor();
    assert.match(await page.locator('[data-import-message]').innerText(),/workspace changed/);
    assert.equal(await page.locator('[data-import-content]').isVisible(),false);
    await page.locator('[data-import-close]').click();
    await page.clock.install();
    await opener.click();
    await page.clock.fastForward(30_001);
    assert.match(await page.locator('[data-import-message]').innerText(),/did not finish loading/);
    assert.equal(await page.locator('[data-import-retry]').isVisible(),true);
    assert.deepEqual(errors,[]);
    console.log('PASS: compact rows, actual Schedule bridge, read-only review, filters, escaping, themes/narrow layout, draft retention, errors/retry, close/focus and late/workspace-switch protection.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode=1;});
