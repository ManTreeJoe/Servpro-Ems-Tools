import assert from 'node:assert/strict';
import {readFileSync,readdirSync} from 'node:fs';
import {PGlite} from '@electric-sql/pglite';

const db = new PGlite();
const uid = n => `${String(n).repeat(8)}-${String(n).repeat(4)}-4000-8000-${String(n).repeat(12)}`;
const owner=uid(1), admin=uid(2), editor=uid(3), other=uid(4), pending=uid(5);
await db.exec(`
create role anon; create role authenticated; create role authenticator; create role service_role bypassrls; create role supabase_auth_admin;
create schema auth; create schema storage; create schema realtime;
grant usage on schema public,auth,storage,realtime to authenticated,anon;
create function auth.jwt() returns jsonb language sql stable as $$ select coalesce(nullif(current_setting('request.jwt.claims',true),''),'{}')::jsonb $$;
create function auth.uid() returns uuid language sql stable as $$ select (auth.jwt()->>'sub')::uuid $$;
create table auth.users(id uuid primary key,email text unique,raw_user_meta_data jsonb default '{}',created_at timestamptz default now(),email_confirmed_at timestamptz default now(),deleted_at timestamptz,banned_until timestamptz);
create table auth.identities(id uuid default gen_random_uuid(),user_id uuid references auth.users(id),provider text);
create table public.app_admins(user_id uuid primary key references auth.users(id),created_at timestamptz default now());
create table public.app_user_departments(user_id uuid references auth.users(id),department text,primary key(user_id,department));
create table public.jobs(job_id uuid primary key default gen_random_uuid(),department text,display_name text);
create table public.meta(key text primary key,value text);
create table storage.objects(id uuid default gen_random_uuid(),name text);
alter table public.app_admins enable row level security;
alter table public.app_user_departments enable row level security;
alter table public.jobs enable row level security;
alter table public.meta enable row level security;
alter table storage.objects enable row level security;
grant select on public.app_admins,public.app_user_departments to authenticated;
grant all on public.jobs,public.meta,storage.objects to authenticated;
create policy own_admin on public.app_admins for select to authenticated using(user_id=auth.uid());
create policy own_department on public.app_user_departments for select to authenticated using(user_id=auth.uid());
create function public.my_departments() returns setof text language sql stable as $$select department from public.app_user_departments where user_id=auth.uid()$$;
create function public.is_app_admin() returns boolean language sql stable as $$select exists(select 1 from public.app_admins where user_id=auth.uid())$$;
create function public.my_app_access() returns jsonb language sql stable as $$select '{}'::jsonb$$;
create policy jobs_rw on public.jobs for all to authenticated using(department is null or department in(select public.my_departments())) with check(department is null or department in(select public.my_departments()));
create policy meta_read on public.meta for select to authenticated using(true);
create policy object_rw on storage.objects for all to authenticated using(true) with check(true);
create function public.test_definer_leak() returns bigint language sql stable security definer as $$select count(*) from public.jobs$$;
create function public.test_volatile_rpc() returns integer language sql volatile as $$select 1$$;
insert into auth.users(id,email) values('${owner}','nathan@servpro10100.com'),('${admin}','admin@example.test'),('${editor}','pablo@servpro10100.com'),('${other}','other@example.test');
insert into auth.identities(user_id,provider) select id,'azure' from auth.users;
insert into public.app_admins(user_id) values('${owner}'),('${admin}');
insert into public.app_user_departments values('${owner}','IE'),('${admin}','IE'),('${editor}','IE'),('${other}','OC');
insert into public.jobs(department,display_name) values('IE','IE fixture'),('OC','OC fixture'),(null,'Unassigned fixture');
insert into public.meta values('fixture','shared');
insert into storage.objects(name) values('private-fixture.pdf');
`);
const file=readdirSync(new URL('../supabase/migrations/',import.meta.url)).find(f=>f.endsWith('_microsoft_employee_approval.sql'));
await db.exec(readFileSync(new URL('../supabase/migrations/'+file,import.meta.url),'utf8'));
await db.exec(`insert into auth.users(id,email) values('${pending}','pending@example.test');insert into auth.identities(user_id,provider) values('${pending}','azure');`);

async function who(id,method='oauth',http='GET',path='/jobs') {
  await db.exec('RESET ROLE; SET LOCAL ROLE authenticated;');
  await db.query("select set_config('request.jwt.claims',$1,true),set_config('request.method',$2,true),set_config('request.path',$3,true)",
    [JSON.stringify({sub:id,role:'authenticated',amr:[{method}],user_metadata:{is_admin:true,approval_status:'approved'}}),http,path]);
}
const scalar=async sql=>(await db.query(sql)).rows[0];
let count=0;
async function check(name,body) {
  await db.exec('BEGIN');
  try {await body();count++;console.log('PASS:',name);} finally {await db.exec('ROLLBACK');}
}
async function denied(sql) {
  await db.exec('SAVEPOINT forbidden');
  let caught=false;
  try {await db.exec(sql);} catch(e) {caught=true;assert.ok(['42501','40001','22023'].includes(e.code),e.message);}
  await db.exec('ROLLBACK TO SAVEPOINT forbidden');
  assert.equal(caught,true,'Expected server denial');
}

await check('Existing accounts and memberships are preserved',async()=>{
  assert.equal((await scalar("select count(*)::int n from oneloss_access.accounts where status='approved'")).n,4);
  await who(owner);const r=await scalar('select public.my_app_access() a');
  assert.equal(r.a.is_admin,true);assert.deepEqual(r.a.departments,['IE']);
});
await check('New user is pending and metadata cannot self-approve',async()=>{
  await who(pending);const r=await scalar('select public.my_app_access() a');
  assert.equal(r.a.access_state,'pending');assert.equal(r.a.is_admin,false);
  assert.equal((await scalar('select count(*)::int n from public.jobs')).n,0);
  assert.equal((await scalar('select count(*)::int n from public.meta')).n,0);
  assert.equal((await scalar('select count(*)::int n from storage.objects')).n,0);
  await denied(`select public.employee_decide_user('${pending}','approve','admin',array['IE'],0)`);
  await denied('select public.employee_admin_snapshot()');
});
await check('Pending user cannot bypass RLS through a definer RPC',async()=>{
  await who(pending,'oauth','POST','/rpc/test_definer_leak');await denied('select oneloss_access.pre_request()');
  await who(pending,'oauth','POST','/rpc/my_app_access');await db.exec('select oneloss_access.pre_request()');
});
await check('Admin approves a viewer with only assigned franchise reads',async()=>{
  await who(owner,'oauth','POST','/rpc/employee_decide_user');await db.exec(`select public.employee_decide_user('${pending}','approve','viewer',array['IE'],0)`);
  await who(pending);const r=await scalar('select public.my_app_access() a');assert.equal(r.a.role,'viewer');assert.equal(r.a.access_state,'approved');
  assert.equal((await scalar('select count(*)::int n from public.jobs')).n,2);
  assert.equal((await scalar("select count(*)::int n from public.jobs where department='OC'")).n,0);
  await denied("insert into public.jobs(department,display_name) values(null,'blocked')");
  assert.equal((await db.query("update public.jobs set display_name='blocked' returning job_id")).rows.length,0);
  await denied("insert into storage.objects(name) values('blocked')");
  await who(pending,'oauth','POST','/rpc/test_volatile_rpc');await denied('select oneloss_access.pre_request()');
});
await check('Editor may update assigned jobs but not another franchise',async()=>{
  await who(editor);await db.exec("update public.jobs set display_name='edited' where department='IE'");
  assert.equal((await scalar("select count(*)::int n from public.jobs where display_name='edited'")).n,1);
  assert.equal((await db.query("update public.jobs set display_name='blocked' where department='OC' returning job_id")).rows.length,0);
});
await check('Approval validates franchise and revision',async()=>{
  await who(owner);await denied(`select public.employee_decide_user('${pending}','approve','editor',array['UNKNOWN'],0)`);
  await db.exec(`select public.employee_decide_user('${pending}','approve','editor',array['IE'],0)`);
  await denied(`select public.employee_decide_user('${pending}','approve','admin',array['IE'],0)`);
});
await check('Self-demotion and recovery administrator removal are blocked',async()=>{
  await who(owner);await denied(`select public.employee_decide_user('${owner}','suspend',null,array[]::text[],0)`);
  await who(admin);await denied(`select public.employee_decide_user('${owner}','approve','viewer',array['IE'],0)`);
});
await check('Suspension removes access immediately',async()=>{
  await who(owner);await db.exec(`select public.employee_decide_user('${editor}','suspend',null,array[]::text[],0)`);
  await who(editor);assert.equal((await scalar('select public.my_app_access() a')).a.access_state,'suspended');
  assert.equal((await scalar('select count(*)::int n from public.jobs')).n,0);
});
await check('Microsoft-only blocks employee passwords but preserves Nathan recovery',async()=>{
  await db.exec('update oneloss_access.controls set microsoft_only=true');
  await who(editor,'password');assert.equal((await scalar('select public.my_app_access() a')).a.access_state,'microsoft_required');
  assert.equal((await scalar('select count(*)::int n from public.jobs')).n,0);
  await who(owner,'password');const r=await scalar('select public.my_app_access() a');assert.equal(r.a.auth_mode,'emergency');assert.equal(r.a.is_admin,true);
});
await check('Auth hooks allow Azure signup and reject employee password without logging out other sessions',async()=>{
  await db.exec('RESET ROLE; SET LOCAL ROLE supabase_auth_admin');
  let r=await db.query('select oneloss_access.before_user_created($1::jsonb) a',[JSON.stringify({user:{app_metadata:{provider:'azure'}}})]);assert.deepEqual(r.rows[0].a,{});
  r=await db.query('select oneloss_access.before_user_created($1::jsonb) a',[JSON.stringify({user:{app_metadata:{provider:'email'},user_metadata:{provider:'azure'}}})]);assert.equal(r.rows[0].a.error.http_code,403);
  r=await db.query('select oneloss_access.password_verification($1::jsonb) a',[JSON.stringify({user_id:editor,valid:true})]);assert.equal(r.rows[0].a.decision,'reject');assert.equal(r.rows[0].a.should_logout_user,false);
  r=await db.query('select oneloss_access.password_verification($1::jsonb) a',[JSON.stringify({user_id:owner,valid:true})]);assert.equal(r.rows[0].a.decision,'continue');
});
await check('Anonymous users have no status or admin API access',async()=>{
  await db.exec('SET LOCAL ROLE anon');await denied('select public.employee_admin_snapshot()');await denied('select public.my_app_access()');
});
// Exercise the actual operator test script against synthetic PostgreSQL records.
const {execFileSync}=await import('node:child_process');
const saved={user_id:editor,email:'pablo@servpro10100.com',status:'approved',role:'editor',revision:0,
  departments:['IE'],is_admin:false,recovery:false};
const python=`import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('operator_test','deploy/employee-access/pablo_test.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
s=json.load(sys.stdin)
print(json.dumps({'pending':m.change_sql(s),'restore':m.change_sql(s,restore=True)}))`;
const operator=JSON.parse(execFileSync('python',['-c',python],{input:JSON.stringify(saved),encoding:'utf8'}));
await db.exec(operator.pending);
let operatorState=await scalar(`select status,role,revision from oneloss_access.accounts where user_id='${editor}'`);
assert.deepEqual(operatorState,{status:'pending',role:'editor',revision:1});
assert.deepEqual((await db.query(`select department from public.app_user_departments where user_id='${editor}'`)).rows,[{department:'IE'}]);
await db.exec(operator.restore);
operatorState=await scalar(`select status,role,revision from oneloss_access.accounts where user_id='${editor}'`);
assert.deepEqual(operatorState,{status:'approved',role:'editor',revision:2});
count++;console.log('PASS: actual Pablo pending/cancel SQL preserves account, role and franchise and restores approved access');
console.log(`${count} PostgreSQL access checks passed using synthetic records only.`);
await db.close();
