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
  const {stripTypeScriptTypes} = require('node:module');
  const moduleUrl = source => 'data:text/javascript;base64,' + Buffer.from(stripTypeScriptTypes(source, {mode:'transform'})).toString('base64');
  const emsUrl = moduleUrl(fs.readFileSync('supabase/functions/trello-sync/ems_comments.ts','utf8'));
  const guardUrl = require('node:url').pathToFileURL(require('node:path').resolve('supabase/functions/_shared/trello-write-guard.mjs')).href;
  const sync = await import(moduleUrl(core.replace('../_shared/trello-write-guard.mjs',guardUrl).replace('./ems_comments.ts',emsUrl)));
  await assert.rejects(sync.safeJson(guardedTrelloFetch(fake, {}), 'https://fixture.invalid', {method:'POST'}, 'trello'), e => e.code === 'trello_writes_disabled');
  const member = '000000000000000000000001';
  const requests = [];
  const transport = async (url, init) => {
    const u = new URL(url); requests.push([u.pathname, init.method || 'GET']);
    if (u.hostname === 'api.trello.com') {
      assert.equal(init.method, 'GET');
      assert.equal(u.pathname, '/1/members/me');
      return Response.json({id:member});
    }
    assert.equal(u.hostname, 'fixture.supabase.co');
    if (u.pathname.endsWith('/hub_trello_claim')) return Response.json('fixture-lease');
    if (u.pathname.endsWith('/hub_trello_release')) {
      assert.equal(JSON.parse(init.body).p_error, null);
      return Response.json(null);
    }
    assert.equal(u.pathname, '/rest/v1/hub_trello_sync_sources');
    return Response.json([]);
  };
  const env = {SUPABASE_URL:'https://fixture.supabase.co', SUPABASE_SERVICE_ROLE_KEY:'fake',
    TRELLO_SYNC_API_KEY:'fake', TRELLO_SYNC_TOKEN:'fake', TRELLO_EMS_COMMENTS_ENABLED:'true'};
  for (const flag of [undefined, 'false']) {
    const {store,get} = sync.adapters({...env, ONELOSS_TRELLO_WRITES_ENABLED:flag}, transport);
    assert.equal(store.mirrorEms, undefined);
    assert.equal((await sync.runSync(store,get,member)).state,'checked');
  }
  assert.equal(typeof sync.adapters({...env, ONELOSS_TRELLO_WRITES_ENABLED:'true'},transport).store.mirrorEms,'function');
  console.log('PASS: default-off writes; distinct denial error; comments enabled/writes off read sync checked; both flags required for mirror.');
})().catch(error => { console.error(error); process.exitCode=1; });
