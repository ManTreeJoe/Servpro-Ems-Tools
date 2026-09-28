const assert = require('node:assert/strict');
const path = require('node:path');
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.setContent('<div id="status-msg"></div>');
    for (const file of ['web_shared/theme.css','pipeline_web_assets/app.css','pipeline_web_assets/job_workspace_tabs.css']) await page.addStyleTag({path:path.resolve(file)});
    for (const file of ['web_shared/modal.js','pipeline_web_assets/job_workspace_tabs.js','pipeline_web_assets/job_conversation.js','web_shared/vendor/markdown-it/markdown-it.min.js','pipeline_web_assets/comment_markdown.js','pipeline_web_assets/app.js']) await page.addScriptTag({path:path.resolve(file)});
    await page.evaluate(() => {
      document.documentElement.dataset.theme = 'dark';
      window.original = '**Drying update**\n\n- *Kitchen* complete\n- ~~Old note~~\n\n> Adjuster response\n\n`Readings` and [Report](https://example.com/report)';
      window.posted = []; window.opened = [];
      window.pywebview = {api:{open_url: async url => opened.push(url), post_job_comment:async (...args) => {posted.push(args); return {ok:true,comment:{id:'new',card_id:'ems-card',actor:'Me',text:args[2]}};}}};
      openAuditModal({ok:true,client:'Markdown test',card_id:'ems-card',selected_division:'EMS',audit:{found:true},crm:{},comments:[{id:'one',card_id:'ems-card',source:'trello',actor:'Coordinator',text:original,can_manage:true}]});
    });
    const body = page.locator('.comment-markdown').first();
    assert.equal(await body.locator('strong').innerText(), 'Drying update');
    assert.equal(await body.locator('li').count(), 2);
    assert.equal(await body.locator('em').innerText(), 'Kitchen');
    assert.equal(await body.locator('s').innerText(), 'Old note');
    await body.locator('a').click();
    assert.deepEqual(await page.evaluate(() => opened), ['https://example.com/report']);
    const original = await page.evaluate(() => original);
    const prompt = page.waitForEvent('dialog').then(async dialog => {
      assert.equal(dialog.defaultValue(), original);
      await dialog.dismiss();
    });
    await page.locator('[data-comment-edit]').click();
    await prompt;
    const unsafe = await page.evaluate(() => {
      const host = document.createElement('div');
      host.innerHTML = CommentMarkdown.render('<img src=x onerror=alert(1)>\n\n[x](javascript:alert%281%29)\n\n![tracking](https://example.com/pixel)\n\n[x](file:///C:/private)');
      return {images:host.querySelectorAll('img,script,iframe').length, links:[...host.querySelectorAll('a')].map(a=>a.getAttribute('href')), text:host.textContent};
    });
    assert.equal(unsafe.images, 0); assert.deepEqual(unsafe.links, ['https://example.com/pixel']);
    assert.ok(unsafe.text.includes('<img'));
    const input = page.locator('[data-comment-input]');
    await input.fill('Kitchen complete');
    await input.evaluate(el => {el.setSelectionRange(0,7); window.formatEdits=0; el.addEventListener('input',()=>window.formatEdits++);});
    await page.locator('[data-comment-format="bold"]').click();
    assert.equal(await input.inputValue(), '**Kitchen** complete');
    await page.locator('[data-comment-format="bold"]').click();
    assert.equal(await input.inputValue(), 'Kitchen complete');
    await input.press('Control+i');
    assert.equal(await input.inputValue(), '*Kitchen* complete');
    assert.equal(await page.evaluate(()=>formatEdits), 3);
    await input.fill('Kitchen\nHall');
    await input.selectText();
    await page.locator('[data-comment-format="bullet"]').click();
    assert.equal(await input.inputValue(), '- Kitchen\n- Hall');
    await input.fill('Report'); await input.selectText();
    await page.locator('[data-comment-format="link"]').click();
    assert.equal(await input.inputValue(), '[Report](https://)');
    assert.equal(await input.evaluate(el=>el.value.slice(el.selectionStart,el.selectionEnd)), 'https://');
    assert.equal(await page.locator('.comment-format-tools').count(), 1);
    await page.locator('[data-comment-input]').fill('**New update**');
    await page.locator('[data-post-comment]').click();
    await page.waitForFunction(() => posted.length === 1);
    assert.equal(await page.evaluate(() => posted[0][2]), '**New update**');
    await page.waitForFunction(() => document.querySelector('[data-comment-input]').value === '');
    await page.screenshot({path:path.join(require('os').tmpdir(),'oneloss-comment-markdown.png')});
    assert.equal(await body.evaluate(el=>el.scrollWidth <= el.clientWidth + 1), true);
    assert.deepEqual(errors, []);
    console.log('PASS: Markdown rendering, original edit/post text, safe links, no embedded HTML/images, layout.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exit(1);});
