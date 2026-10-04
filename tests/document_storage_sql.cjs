/* Isolated PostgreSQL/WASM contract test. No live credentials or network.
 * Run with NODE_PATH containing @electric-sql/pglite (tested with 0.5.8).
 */
const { PGlite } = require('@electric-sql/pglite');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const db = new PGlite();
  await db.exec(`
    create role anon;
    create role authenticated;
    create schema auth;
    create schema storage;
    create table auth.users(id uuid primary key);
    create function auth.uid() returns uuid language sql stable as
      $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
    grant usage on schema auth, storage to authenticated, anon;
    grant execute on function auth.uid() to authenticated, anon;
    create table public.jobs(job_id uuid unique not null, department text);
    alter table public.jobs enable row level security;
    grant select on public.jobs to authenticated;
    create policy existing_office_access on public.jobs for select to authenticated
      using(department = current_setting('test.department', true));
    create table storage.buckets(id text primary key, name text, public boolean, file_size_limit bigint, allowed_mime_types text[]);
    create table storage.objects(id uuid default gen_random_uuid(), bucket_id text, name text, metadata jsonb);
    alter table storage.objects enable row level security;
    grant select,insert,update,delete on storage.objects to authenticated;
    insert into auth.users values
      ('11111111-1111-4111-8111-111111111111'),
      ('22222222-2222-4222-8222-222222222222');
    insert into public.jobs values
      ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa','IE'),
      ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb','OTHER');
  `);
  await db.exec(fs.readFileSync(path.join(__dirname, '../supabase/migrations/20261002185042_document_storage_pilot.sql'), 'utf8'));
  const asUser = async (id='11111111-1111-4111-8111-111111111111') => {
    await db.exec(`set role authenticated; set request.jwt.claim.sub = '${id}'; set test.department = 'IE';`);
  };
  const prepare = async (hash='a'.repeat(64), job='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', relative='DOCS/ATP.pdf') => {
    const {rows} = await db.query('select public.prepare_job_document($1,$2,$3,4,$4) as result', [job, relative, hash, 'application/pdf']);
    return rows[0].result;
  };
  await asUser();
  await assert.rejects(prepare(), /not enabled/);
  await assert.rejects(db.exec("insert into document_pilot_users(user_id) values(auth.uid())"), /permission denied/);
  await db.exec(`reset role;
    insert into document_pilot_users(user_id) values('11111111-1111-4111-8111-111111111111');
    insert into document_pilot_jobs(job_id) select job_id from jobs;
  `);
  await asUser();
  await assert.rejects(prepare(undefined, 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'), /not enabled/);
  for (const relative of ['../a.pdf','a/../b.pdf','/a.pdf','a//b.pdf','a\\b.pdf','photo.jpg']) {
    await assert.rejects(prepare(undefined, undefined, relative), /check constraint/);
  }
  let first = await prepare();
  assert.equal(first.action, 'upload');
  assert.equal((await prepare()).version.version_id, first.version.version_id, 'retry resumes pending version');
  await assert.rejects(prepare('b'.repeat(64)), /still pending/);
  await assert.rejects(db.query('select confirm_job_document($1)', [first.version.version_id]), /row-level security/);
  const put = async (version) => {
    await db.query("insert into storage.objects(bucket_id,name,metadata) values('job-documents',$1,'{\"size\":4}')", [version.object_key]);
    await db.query('select confirm_job_document($1)', [version.version_id]);
  };
  await put(first.version);
  assert.equal((await prepare()).action, 'unchanged');
  const second = await prepare('b'.repeat(64));
  assert.notEqual(second.version.version_id, first.version.version_id);
  await put(second.version);
  const revert = await prepare();
  assert.equal(revert.action, 'upload', 'A -> B -> A creates a new version');
  await put(revert.version);
  await assert.rejects(db.exec('delete from job_document_versions'), /permission denied/);
  await assert.rejects(db.exec("update job_documents set relative_path='changed.pdf'"), /permission denied/);
  await db.exec("update storage.objects set name='bad'; delete from storage.objects;");
  assert.equal((await db.query('select count(*)::int n from storage.objects')).rows[0].n, 3, 'objects immutable');
  await asUser('22222222-2222-4222-8222-222222222222');
  for (const table of ['job_documents','job_document_versions','job_document_receipts','storage.objects']) {
    assert.equal((await db.query(`select count(*)::int n from ${table}`)).rows[0].n, 0, 'nonpilot cannot read ' + table);
  }
  await assert.rejects(prepare(), /not enabled/);
  await db.exec('reset role; set role anon;');
  await assert.rejects(prepare(), /permission denied/);
  await db.close();
  console.log('Document storage SQL: pilot gating, office isolation, path validation, retries, versions, receipts, immutability and anonymous denial passed.');
})().catch(error => { console.error(error); process.exit(1); });
