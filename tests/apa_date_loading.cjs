const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const source = fs.readFileSync('apa_web_assets/app.js', 'utf8');
const start = source.indexOf('async function loadToday()');
const end = source.indexOf('\nfunction stepDate(', start);
const pending = [], messages = [];
const context = {state: {doc: null, active_date: null, loadSeq: 0},
  pywebview: {api: {today_doc: request, doc_for_date: request}},
  setStatus: (...args) => messages.push(args), renderAll() {}};
function request() {return new Promise((resolve, reject) => pending.push({resolve, reject}));}
vm.createContext(context); vm.runInContext(source.slice(start, end), context);
(async () => {
  const old = context.loadToday(), latest = context.loadDate('2026-09-11');
  pending[1].resolve({date_iso:'2026-09-11'}); assert.equal(await latest, true);
  pending[0].resolve({date_iso:'2026-09-14'}); assert.equal(await old, false);
  assert.equal(context.state.active_date, '2026-09-11', 'Late Today response must not replace the selected date');
  const failed = context.loadDate('2026-09-10');
  pending[2].reject(new Error('Share unavailable')); assert.equal(await failed, false);
  assert.equal(context.state.active_date, '2026-09-11', 'Failed load preserves displayed document');
  assert.match(messages.at(-1)[0], /Share unavailable/);
  assert.equal(messages.at(-1)[1], 'error');
  const retry = context.loadDate('2026-09-10');
  pending[3].resolve({date_iso:'2026-09-10'}); await retry;
  assert.equal(context.state.active_date, '2026-09-10');
  console.log('APA date switching, failed-load feedback, and retry passed.');
})().catch(e => {console.error(e); process.exitCode=1;});
