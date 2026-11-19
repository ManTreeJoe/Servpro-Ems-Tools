const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 900, height: 900}});
    await page.goto('file:///' + path.resolve('settings_web_assets/index.html').replaceAll('\\', '/'));
    await page.evaluate(() => {
      window.calls = [];
      window.pywebview = {api: {
        supabase_sign_in_microsoft: email => new Promise(resolve => {
          calls.push(['microsoft', email]); window.finishMicrosoft = resolve;
        }),
        supabase_cancel_microsoft: async () => {
          calls.push(['cancel']); finishMicrosoft({ok:false, error:'Microsoft sign-in cancelled.'});
        },
        supabase_sign_in_password: async () => { calls.push(['password']); return {ok:false}; },
      }};
      window.refreshSupabase = async () => calls.push(['refresh']);
      window.renderConnections = async () => calls.push(['connections']);
      bindSupabaseControls(); openSupabaseSignIn();
    });
    const button = page.locator('#sb-microsoft-signin');
    await button.click();
    assert.equal(await page.locator('#sb-email').inputValue(), '');
    assert.deepEqual((await page.evaluate(() => calls))[0], ['microsoft', undefined]);
    assert.equal(await button.isDisabled(), true);
    assert.equal(await page.locator('#sb-password-signin').isDisabled(), true);
    await page.locator('#sb-password').press('Enter');
    assert.equal((await page.evaluate(() => calls.filter(c => c[0] === 'password'))).length, 0);
    await page.locator('#sb-signin-close').click();
    await page.waitForFunction(() => !sbMicrosoftBusy);
    assert.equal(await button.isDisabled(), false);
    await page.evaluate(() => openSupabaseSignIn());
    await button.click();
    await page.evaluate(() => finishMicrosoft({ok:true, message:'Signed in'}));
    await page.waitForFunction(() => calls.some(c => c[0] === 'connections'));
    assert.equal(await page.locator('#sb-signin').isVisible(), false);
    assert.equal((await page.evaluate(() => calls.filter(c => c[0] === 'microsoft'))).length, 2);
    console.log('PASS: Microsoft button, validation, busy state, cancellation, retry and successful refresh.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
