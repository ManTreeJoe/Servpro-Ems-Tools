const { chromium } = require('playwright');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({headless:true, channel:'msedge'});
  try {
    const page = await browser.newPage();
    await page.setContent(`<div id="root"><button data-add-job-log>Add update</button><div class="modal-body"><div class="job-card-layout"><div class="job-card-main">
      <div class="division-conflict-banner">Verify card</div><section class="job-info-section">Info</section>
      <section class="job-log-section"><textarea id="draft">unsaved update</textarea></section>
      <section class="progress-section">Requirements</section><section class="checklist-section"><input id="check" type="checkbox"></section>
      <section class="signatures-section">Signatures</section><details class="job-attachments-section">Attachments</details>
      <details class="job-run-section">Run history</details></div><aside class="job-card-activity"><input data-comment-search value="search draft"></aside></div></div></div>`);
    await page.addScriptTag({path:path.resolve('pipeline_web_assets/job_workspace_tabs.js')});
    await page.addStyleTag({path:path.resolve('web_shared/theme.css')});
    await page.addStyleTag({path:path.resolve('pipeline_web_assets/app.css')});
    await page.addStyleTag({path:path.resolve('pipeline_web_assets/job_workspace_tabs.css')});
    await page.evaluate(() => {
      window.original = document.querySelector('#draft');
      window.checkEvents = 0;
      document.querySelector('#check').addEventListener('change',()=>window.checkEvents++);
      window.tabs = JobWorkspaceTabs.mount(document.querySelector('#root'),'test-job');
    });
    assert.equal(await page.locator('[role=tab]').count(),5);
    assert.equal(await page.locator('#job-panel-overview').isVisible(),true);
    await page.locator('[data-add-job-log]').click();
    assert.equal(await page.locator('#draft').isVisible(),true);
    assert.equal(await page.locator('[data-comment-search]').inputValue(),'search draft');
    await page.locator('#job-tab-requirements').click();
    await page.locator('#check').check();
    assert.equal(await page.evaluate(()=>window.checkEvents),1);
    await page.locator('#job-tab-log').click();
    assert.equal(await page.locator('#draft').inputValue(),'unsaved update');
    assert.equal(await page.evaluate(()=>document.querySelector('#draft')===window.original),true);
    await page.locator('#job-tab-log').focus();
    await page.keyboard.press('End');
    assert.equal(await page.locator('#job-tab-run').getAttribute('aria-selected'),'true');
    assert.equal(await page.locator('.division-conflict-banner').isVisible(),true);
    for (const width of [1280,390]) {
      await page.setViewportSize({width,height:800});
      assert.equal(await page.locator('#job-tab-overview').count(),1);
      assert.equal(await page.locator('#job-panel-run').isVisible(),true);
    }
    await page.screenshot({path:path.join(require('node:os').tmpdir(),'linguar-workspace-tabs-test.png')});
    console.log('PASS: tab routing, keyboard navigation, retained drafts/listeners, comment search, persistent warnings');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
