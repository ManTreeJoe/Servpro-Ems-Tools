// Real PostgreSQL engine (PGlite), entirely in memory; no live provider or DB access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { PGlite } = require('@electric-sql/pglite');

async function main() {
  const db = new PGlite();
  try {
    await db.exec('create role anon; create role authenticated; create role service_role bypassrls;');
    await db.exec(fs.readFileSync(path.join(__dirname, '../../supabase/migrations/20260918215614_trello_server_mirror.sql'), 'utf8'));
    const migrationDir = path.join(__dirname, '../../supabase/migrations');
    const cadenceMigration = fs.readdirSync(migrationDir).find(name => name.endsWith('_trello_sync_poll_cadence.sql'));
    await db.exec(fs.readFileSync(path.join(migrationDir, cadenceMigration), 'utf8'));
    const detailMigration = fs.readdirSync(migrationDir).find(name => name.endsWith('_trello_sync_card_details.sql'));
    await db.exec(fs.readFileSync(path.join(migrationDir, detailMigration), 'utf8'));
    const scalar = async (sql, params = []) => Object.values((await db.query(sql, params)).rows[0])[0];
    const rpc = async (name, args = []) => {
      const expression = `public.${name}(${args.map((_, i) => '$' + (i + 1)).join(',')})`;
      return name === 'hub_trello_comment_work' ? (await db.query(`select * from ${expression}`, args)).rows : scalar(`select ${expression}`, args);
    };
    const boardId = '000000000000000000000001', cardId = '000000000000000000000002';
    const laneId = '000000000000000000000003';
    const board = { id: boardId, name: 'Synthetic board' };
    const lists = [{ id: laneId, idBoard: boardId, name: 'Lane' }];
    const cards = [{ id: cardId, idBoard: boardId, idList: laneId, name: 'Synthetic job', dateLastActivity: '2026-09-18' }];
    const action = n => ({ id: n.toString(16).padStart(24, '0'), type: 'commentCard', date: '2026-09-18', data: { card: { id: cardId }, text: 'Synthetic note ' + n } });
    await db.exec('set role service_role');
    assert.equal(await rpc('hub_trello_claim'), null, 'disabled by default');
    await db.query('insert into public.hub_trello_sync_sources(board_id,label) values($1,$2)', [boardId, 'Pilot']);
    await db.exec('update public.hub_trello_sync_control set enabled=true; update public.hub_trello_sync_sources set enabled=true');
    let lease = await rpc('hub_trello_claim'); assert(lease);
    assert.equal(await rpc('hub_trello_claim'), null, 'only one worker owns lease');
    const commit = (data = cards) => rpc('hub_trello_commit_board', [lease, boardId, board, JSON.stringify(lists), JSON.stringify(data)]);
    const row = async () => (await db.query('select * from public.hub_trello_mirror_cards where card_id=$1', [cardId])).rows[0];
    await commit(); let revision = (await row()).revision;
    assert.equal(await rpc('hub_trello_card_detail', [lease, boardId, cardId, revision, cards[0]]), true);
    assert.equal(await rpc('hub_trello_card_detail', [lease, boardId, cardId, revision, { ...cards[0], idBoard: cardId }]), false);
    const page = (before, actions, next) => rpc('hub_trello_comment_page', [lease, boardId, cardId, revision, before, JSON.stringify(actions), next]);
    assert.equal(await page(null, [action(9)], null), true);
    assert.equal((await row()).comments_json.length, 1);
    await commit(); assert.equal((await row()).revision, revision, 'repeat snapshot stable');
    assert.equal((await rpc('hub_trello_comment_work', [lease, boardId, 20])).length, 0);

    cards[0].dateLastActivity = '2026-09-19'; await commit(); revision = (await row()).revision;
    const cursor = action(8).id;
    await page(null, [action(10), action(8)], cursor);
    assert.deepEqual((await row()).comments_json, [action(9)], 'partial scan preserves last complete conversation');
    assert.equal(await page(null, [action(10), action(8)], cursor), false, 'replayed page rejected');
    assert.equal((await rpc('hub_trello_comment_work', [lease, boardId, 20]))[0].before_cursor, cursor);
    await page(cursor, [action(7)], null);
    assert.equal((await row()).comments_json.length, 3, 'complete scan atomically replaces old comments, including deletions');
    assert.equal((await row()).comments_revision, revision);
    assert.deepEqual((await row()).scan_json, []);

    // Refresh daily even when upstream lastActivity didn't change (e.g. comment deletion).
    await db.exec("update public.hub_trello_mirror_cards set comments_completed_at=now()-interval '2 days'");
    assert.equal((await rpc('hub_trello_comment_work', [lease, boardId, 20])).length, 1);
    await page(null, [], null);
    assert.deepEqual((await row()).comments_json, [], 'explicit complete empty conversation is valid');
    await rpc('hub_trello_record_error', [lease, boardId, 'trello_http_500', cardId]);
    assert.equal((await row()).comment_error_code, 'trello_http_500');
    assert.equal((await row()).comments_revision, revision, 'failure does not erase last good revision');

    const before = await row();
    await assert.rejects(commit([{ ...cards[0], idBoard: cardId }]), /invalid_card_snapshot/);
    await assert.rejects(commit([cards[0], cards[0]]), /invalid_card_snapshot/);
    assert.deepEqual(await row(), before, 'invalid snapshots leave the whole board unchanged');
    await commit([]); assert.equal((await row()).present, false, 'removed card retained, no destructive delete');
    await commit(); assert.equal((await row()).present, true);
    const oldRevision = revision;
    cards[0].name = 'Changed job'; await commit();
    assert.equal(await rpc('hub_trello_comment_page', [lease, boardId, cardId, oldRevision, null, JSON.stringify([action(5)]), null]), false);

    await rpc('hub_trello_finish_source', [lease, boardId, true]);
    assert.equal(await scalar('select next_poll_at = date_trunc(\'minute\',last_started_at) + interval \'120 seconds\' from public.hub_trello_sync_sources cross join public.hub_trello_sync_control'), true,
      'poll time anchored to the cron minute, not function arrival/finish (otherwise every other run skips)');
    await rpc('hub_trello_finish_source', [lease, boardId, false]);
    assert.equal(await scalar('select consecutive_failures from public.hub_trello_sync_sources'), 1);
    assert.equal(await scalar('select next_poll_at > now() + interval \'3 minutes\' from public.hub_trello_sync_sources'), true);

    await db.exec("update public.hub_trello_sync_control set lease_until=now()-interval '1 second'");
    await assert.rejects(commit(), /sync_lease_expired/);
    const oldLease = lease; lease = await rpc('hub_trello_claim'); assert.notEqual(lease, oldLease);
    await rpc('hub_trello_release', [oldLease, 3600]);
    assert.equal(await scalar('select lease_id from public.hub_trello_sync_control'), lease, 'old worker cannot release successor');
    await rpc('hub_trello_release', [lease, 300]);
    assert.equal(await rpc('hub_trello_claim'), null, 'rate-limit cooldown persists across invocations');

    // Run the actual worker against PostgreSQL with only the provider mocked.
    // This catches JSON/RPC contract drift that separate worker and SQL mocks miss.
    const { runSync, PAGE_SIZE } = await import('../../supabase/functions/trello-sync/core.ts');
    const integrationRpc = async (name, args = {}) => {
      const entries = Object.entries(args);
      const expression = `public.${name}(${entries.map(([key], i) => `${key}=>$${i+1}`).join(',')})`;
      const values = entries.map(([, v]) => v && typeof v === 'object' ? JSON.stringify(v) : v);
      return name === 'hub_trello_comment_work' ? (await db.query(`select * from ${expression}`, values)).rows : scalar(`select ${expression}`, values);
    };
    const store = { rpc: integrationRpc, dueSources: async () => [{ board_id: boardId }] };
    const makeDue = () => db.exec('update public.hub_trello_sync_control set not_before=now(); update public.hub_trello_sync_sources set next_poll_at=now();');
    const memberId = '000000000000000000000004';
    const allActions = Array.from({ length: PAGE_SIZE+1 }, (_, n) => action(3000-n));
    const provider = async (endpoint, params = {}) => {
      if (endpoint === '/members/me') return { id: memberId };
      if (endpoint === `/cards/${cardId}`) return { ...cards[0], checklists: [], attachments: [] };
      if (endpoint.endsWith('/lists')) return lists;
      if (endpoint.endsWith('/cards/open')) return cards.map(c => ({ ...c, closed: false }));
      if (endpoint.endsWith('/actions')) return allActions.filter(a => !params.before || a.id < params.before).slice(0, PAGE_SIZE);
      return { ...board, closed: false };
    };
    await makeDue();
    assert.equal((await runSync(store, provider, memberId)).comment_pages, 1);
    assert.equal((await row()).scan_json.length, PAGE_SIZE);
    assert.deepEqual((await row()).comments_json, [], 'first invocation never exposes the partial history');
    await makeDue();
    assert.equal((await runSync(store, provider, memberId)).comment_pages, 1);
    assert.equal((await row()).comments_json.length, PAGE_SIZE+1, 'next invocation resumes the persisted page cursor');
    await makeDue();
    assert.equal((await runSync(store, provider, memberId)).comment_pages, 0, 'unchanged cards do not repeatedly download history');

    // Test actual permissions, not just policy text. No staff role has any mirror access.
    await db.exec('reset role');
    for (const role of ['anon', 'authenticated']) {
      await db.exec('set role ' + role);
      for (const table of ['hub_trello_sync_control', 'hub_trello_sync_sources', 'hub_trello_mirror_cards']) {
        await assert.rejects(db.query('select * from public.' + table), /permission denied/);
        await assert.rejects(db.query('delete from public.' + table), /permission denied/);
      }
      await assert.rejects(rpc('hub_trello_claim'), /permission denied/);
      await assert.rejects(rpc('hub_trello_assert_lease', [lease]), /permission denied/);
      await db.exec('reset role');
    }
    const functions = (await db.query("select p.oid::regprocedure::text as name, p.prosecdef, has_function_privilege('anon',p.oid,'execute') as anon, has_function_privilege('authenticated',p.oid,'execute') as staff from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.proname like 'hub_trello_%'")).rows;
    assert.equal(functions.length, 9);
    assert(functions.every(f => !f.prosecdef && !f.anon && !f.staff));
    assert.equal(await scalar("select count(*)::int from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relname like 'hub_trello_%' and c.relkind='r' and not c.relrowsecurity"), 0);
    console.log('PASS: PostgreSQL migration, atomic snapshots, resumable comments, fencing, cooldown, and role isolation');
  } finally { await db.close(); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
