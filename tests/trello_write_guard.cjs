const assert = require('node:assert/strict');
const fs = require('node:fs');
(async () => {
  const {guardedTrelloFetch} = await import('../supabase/functions/_shared/trello-write-guard.mjs');
  let calls = 0;
  const fake = () => { calls++; return Promise.resolve(Response.json({ok:true})); };
  for (const value of [undefined, '', 'false', '1', 'TRUE']) {
    for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
      assert.throws(() => guardedTrelloFetch(fake, {ONELOSS_TRELLO_WRITES_ENABLED:value})('https://fixture.invalid', {method}), /trello_writes_disabled/);
    }
  }
  assert.equal(calls, 0);
  assert.throws(() => guardedTrelloFetch(fake, {})(new Request('https://fixture.invalid', {method:'POST'})), /trello_writes_disabled/);
  await guardedTrelloFetch(fake, {})('https://fixture.invalid');
  await guardedTrelloFetch(fake, {ONELOSS_TRELLO_WRITES_ENABLED:'true'})('https://fixture.invalid', {method:'POST'});
  assert.equal(calls, 2);
  const core = fs.readFileSync('supabase/functions/trello-sync/core.ts','utf8');
  const providerCalls = core.split('\n').filter(line => line.includes('api.trello.com'));
  assert.equal(providerCalls.length, 2);
  assert(providerCalls.every(line => line.includes('safeJson(trelloFetch,')), 'Provider call bypasses guarded fetch');
  assert(core.includes('const trelloFetch = guardedTrelloFetch(boundedFetch, env);'));
  const parent = fs.readFileSync('supabase/functions/comment-parent/core.mjs','utf8');
  assert(parent.includes('guardedTrelloFetch(fetcher, {})(url,'));
  console.log('PASS: writes default off, exact opt-in, Request method checked, both server transports guarded.');
})().catch(error => { console.error(error); process.exitCode=1; });
