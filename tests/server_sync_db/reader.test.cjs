// Real PostgreSQL RLS; no live customer data or credentials.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { PGlite } = require('@electric-sql/pglite');
(async () => {
  const db = new PGlite();
  try {
    await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
      create schema auth;
      create function auth.uid() returns uuid language sql stable as
      $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
      grant usage on schema auth to authenticated;
      create table public.app_user_departments(user_id uuid,department text);
      alter table public.app_user_departments enable row level security;
      create policy own on public.app_user_departments for select to authenticated using(user_id=auth.uid());
      grant select on public.app_user_departments to authenticated;
      create function public.my_departments() returns setof text language sql stable security invoker
        as $$select department from public.app_user_departments where user_id=auth.uid()$$;
    `);
    const dir=path.join(__dirname,'../../supabase/migrations');
    for(const suffix of ['trello_server_mirror','trello_sync_card_details','trello_mirror_reader']) {
      const file=fs.readdirSync(dir).find(f=>f.endsWith('_'+suffix+'.sql'));
      await db.exec(fs.readFileSync(path.join(dir,file),'utf8'));
    }
    const board='000000000000000000000001', card='000000000000000000000002';
    const ie='00000000-0000-0000-0000-000000000001', both='00000000-0000-0000-0000-000000000002';
    await db.query(`insert into app_user_departments values ($1,'IE'),($2,'IE'),($2,'OC')`,[ie,both]);
    await db.query(`insert into hub_trello_sync_sources(board_id,label,enabled,reader_department,reader_workspace,required_departments,last_metadata_at)
      values($1,'Synthetic',true,'IE','workspace',array['IE','OC'],now())`,[board]);
    await db.query(`insert into hub_trello_mirror_cards(board_id,card_id,payload,revision,present,details_json,details_revision,comments_revision,comments_json,details_checked_at,comments_completed_at)
      values($1,$2,'{"id":"000000000000000000000002"}','r1',true,'{"checklists":[],"attachments":[]}','r1','r1','[]',now(),now())`,[board,card]);
    const read=async (dept='IE',workspace='workspace',id=card)=>(await db.query('select hub_trello_read($1,$2,$3) as data',[dept,workspace,id])).rows[0].data;
    await db.exec('set role authenticated');
    await db.query(`select set_config('request.jwt.claim.sub',$1,false)`,[ie]);
    assert.equal((await read()).ready,false,'IE-only cannot read mixed-location cards');
    assert.deepEqual((await read('IE','workspace',null)).boards,[]);
    await db.query(`select set_config('request.jwt.claim.sub',$1,false)`,[both]);
    assert.equal((await read()).ready,true,'all required memberships may read');
    assert.equal((await read('OC')).ready,false,'wrong active workspace is rejected');
    assert.equal((await read('IE','other')).ready,false);
    assert.equal((await read('IE','workspace',null)).boards.length,1);
    await assert.rejects(db.exec('update hub_trello_sync_sources set required_departments=array[\'IE\']'),/permission denied/);
    await assert.rejects(db.exec('select scan_json from hub_trello_mirror_cards'),/permission denied/);
    await db.exec('reset role');
    await db.query('delete from app_user_departments where user_id=$1 and department=\'OC\'',[both]);
    await db.exec('set role authenticated');
    assert.equal((await read()).ready,false,'membership revocation takes effect without new JWT');
    await db.exec('reset role; set role anon');
    await assert.rejects(read(),/permission denied/);
    console.log('PASS: mirror reads require all memberships, exact workspace, deny anonymous/writes/staging, and honor revocation');
  } finally {await db.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
