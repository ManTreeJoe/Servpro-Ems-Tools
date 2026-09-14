// Real zoom functions and PanelState; mock only the desktop persistence bridge.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({channel:'msedge',headless:true});
  try {
    const page = await browser.newPage();
    const root = path.resolve(__dirname,'..');
    const source = fs.readFileSync(path.join(root,'pipeline_web_assets/app.js'),'utf8');
    const functions = source.slice(source.indexOf('function setBoardZoom('),source.indexOf('async function refreshSavedBoardInBackground('));
    assert.ok(functions.includes('function onBoardZoomShortcut('));
    await page.setContent('<button id="board-zoom-out">−</button><button id="board-zoom-reset">100%</button><button id="board-zoom-in">+</button><main id="board-view"></main>');
    await page.evaluate(() => {
      window.saved = {};
      window.pywebview = {api:{get_ui_state:async()=>({...window.saved}),set_ui_state:(_panel,patch)=>Object.assign(window.saved,patch)}};
      window.$ = s=>document.querySelector(s);
      window.state = {boardZoom:1,view:'board'};
    });
    await page.addScriptTag({path:path.join(root,'web_shared/panel_state.js')});
    await page.addScriptTag({content:functions});
    await page.evaluate(async()=>{await PanelState.init('pipeline');applyBoardZoom();});
    // Exercise exactly the click bindings shipped by the app.
    const bindings = source.split('\n').filter(line=>/^\s*\$\("#board-zoom-(out|in|reset)"\)\.addEventListener/.test(line)).join('\n');
    assert.equal(bindings.split('\n').length,3);
    await page.addScriptTag({content:bindings+'\ndocument.addEventListener("keydown", onBoardZoomShortcut);'});
    for(let i=0;i<5;i++) await page.click('#board-zoom-out');
    assert.equal(await page.textContent('#board-zoom-reset'),'50%');
    assert.equal(await page.isDisabled('#board-zoom-out'),true);
    await page.keyboard.press('Control+-');
    assert.equal(await page.textContent('#board-zoom-reset'),'50%');
    await page.waitForFunction(()=>saved.boardZoom===.5);
    await page.evaluate(async()=>{state.boardZoom=1;await PanelState.init('pipeline');state.boardZoom=Number(PanelState.get('boardZoom',1))||1;applyBoardZoom();});
    assert.equal(await page.textContent('#board-zoom-reset'),'50%','saved setting restored');
    await page.keyboard.press('Control+=');
    assert.equal(await page.textContent('#board-zoom-reset'),'60%');
    await page.keyboard.press('Control+0');
    assert.equal(await page.textContent('#board-zoom-reset'),'100%');
    for(let i=0;i<4;i++) await page.click('#board-zoom-in');
    assert.equal(await page.textContent('#board-zoom-reset'),'140%');
    assert.equal(await page.isDisabled('#board-zoom-in'),true);
    await page.click('#board-zoom-reset');
    assert.equal(await page.textContent('#board-zoom-reset'),'100%');
    await page.evaluate(()=>{state.view='stages';});
    await page.keyboard.press('Control+-');
    assert.equal(await page.textContent('#board-zoom-reset'),'100%','stages does not change board zoom');
    console.log('Zoom controls passed: buttons, limits, shortcuts, reset, persistence bridge and view isolation.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
