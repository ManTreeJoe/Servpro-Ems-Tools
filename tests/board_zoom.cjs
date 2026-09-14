const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({channel:'msedge', headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:800}});
    const root = path.resolve(__dirname,'..');
    await page.setContent(`<header class="topbar">Jobs</header><main id="board-view" class="board-wrap"><div class="board-tabs">EMS</div><div class="lanes-row">${Array.from({length:8},()=>`<section class="lane"><header class="lane-head">Scheduled</header><div class="lane-cards">${Array.from({length:25},(_,i)=>`<article class="kcard"><span class="kcard-title">Job ${i}</span><p>Arrival 12–3 PM</p></article>`).join('')}</div></section>`).join('')}</div></main>`);
    await page.addStyleTag({path:path.join(root,'web_shared/theme.css')});
    await page.addStyleTag({path:path.join(root,'pipeline_web_assets/app.css')});
    const measure = () => page.evaluate(() => {
      const rect = s => document.querySelector(s).getBoundingClientRect();
      const lane = document.querySelector('.lane-cards');
      const row = document.querySelector('.lanes-row');
      lane.scrollTop = 100; row.scrollLeft = 100;
      return {width:rect('.lane').width,card:rect('.kcard').height,text:rect('.kcard-title').height,chrome:rect('.topbar').height,bottom:rect('#board-view').bottom,vertical:lane.scrollTop,horizontal:row.scrollLeft};
    });
    const base = await measure();
    for (const zoom of [.5,.6,.7,.8,1.4,1]) {
      await page.evaluate(z=>document.querySelector('#board-view').style.setProperty('--board-zoom',z),zoom);
      const result = await measure();
      for (const prop of ['width','card','text']) assert.ok(Math.abs(result[prop]-base[prop]*zoom)<1.5,`${prop} scales at ${zoom}: ${result[prop]} vs ${base[prop]*zoom}`);
      assert.equal(result.chrome,base.chrome);
      assert.ok(result.bottom<=801,'board fits viewport');
      assert.ok(result.vertical>0,'lane scrolling works');
      if (zoom >= .6) assert.ok(result.horizontal>0,'overflowing board scrolls horizontally');
    }
    await page.screenshot({path:path.join(require('os').tmpdir(),'linguar-board-zoom.png')});
    console.log('Board zoom: proportional cards/text/lanes, fixed chrome and scrolling passed.');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
