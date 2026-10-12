const {PGlite}=require(process.env.PGLITE_MODULE||'@electric-sql/pglite');
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{const db=new PGlite();try{
 await db.exec(`create role anon;create role authenticated;
 create table hub_trello_sync_sources(board_id text,enabled boolean,reader_workspace text,reader_department text,board_json jsonb,lists_json jsonb,last_metadata_at timestamptz,last_error_code text);
 create table hub_trello_mirror_cards(card_id text,board_id text,present boolean,payload jsonb);
 alter table hub_trello_sync_sources enable row level security;
 alter table hub_trello_mirror_cards enable row level security;
 create policy sources on hub_trello_sync_sources for select to authenticated using(enabled and reader_department=current_setting('test.department',true));
 create policy cards on hub_trello_mirror_cards for select to authenticated using(exists(select 1 from hub_trello_sync_sources s where s.board_id=hub_trello_mirror_cards.board_id));
 grant select on hub_trello_sync_sources,hub_trello_mirror_cards to authenticated;
 insert into hub_trello_sync_sources values
 ('wip',true,'ws','IE','{"id":"wip"}','[]',now(),null),
 ('logs',true,'ws','IE','{"id":"logs"}','[]',now(),null),
 ('private',true,'ws','OC','{"id":"private"}','[]',now(),null);
 insert into hub_trello_mirror_cards values('c','wip',true,'{"id":"c","name":"original"}');
 select set_config('test.department','IE',false);`);
 await db.exec(fs.readFileSync('supabase/migrations/20261012155420_conditional_board_reads.sql','utf8'));
 const read=async(ids,versions={})=>(await db.query('select hub_trello_boards($1,$2,$3,$4::jsonb) r',['IE','ws',ids,JSON.stringify(versions)])).rows[0].r;
 await db.exec('set role authenticated');
 const first=await read(['wip','private']);assert.equal(first.boards.length,1);assert.equal(first.boards[0].cards.length,1);
 const versions={wip:first.boards[0].version};
 const same=await read(['wip'],versions);assert.equal(same.boards[0].unchanged,true);assert.equal(same.boards[0].cards,undefined);
 await db.exec("reset role;update hub_trello_sync_sources set last_metadata_at=now()+interval '1 second';set role authenticated");
 assert.equal((await read(['wip'],versions)).boards[0].unchanged,true,'poll time does not change content version');
 await db.exec(`reset role;update hub_trello_mirror_cards set payload='{"id":"c","name":"edited"}';set role authenticated`);
 assert.equal((await read(['wip'],versions)).boards[0].cards[0].name,'edited');
 await db.exec('reset role;update hub_trello_mirror_cards set present=false;set role authenticated');
 assert.deepEqual((await read(['wip'],versions)).boards[0].cards,[]);
 await db.exec("reset role;update hub_trello_sync_sources set enabled=false where board_id='wip';set role authenticated");
 assert.deepEqual((await read(['wip'],versions)).boards,[],'revocation ignores client version');
 await db.exec('reset role;set role anon');await assert.rejects(read(['wip']),/permission denied/);
 console.log('PASS: selected boards, unchanged transfer, edits/deletions, polling timestamps, RLS revocation and anonymous denial');
}finally{await db.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
