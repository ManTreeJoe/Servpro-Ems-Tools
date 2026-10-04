-- Copy-only document pilot. No existing jobs/files are changed and no user or
-- job is opted in by this migration. Provision both allowlists deliberately.
begin;

create table public.document_pilot_users (
  user_id uuid primary key references auth.users(id),
  enabled boolean not null default true
);
create table public.document_pilot_jobs (
  job_id uuid primary key references public.jobs(job_id),
  enabled boolean not null default true
);
alter table public.document_pilot_users enable row level security;
alter table public.document_pilot_jobs enable row level security;
revoke all on public.document_pilot_users, public.document_pilot_jobs from public, anon, authenticated;
grant select on public.document_pilot_users, public.document_pilot_jobs to authenticated;
create policy document_pilot_self on public.document_pilot_users for select to authenticated
  using (user_id = (select auth.uid()));
create policy document_pilot_job_read on public.document_pilot_jobs for select to authenticated
  using (
    exists (select 1 from public.document_pilot_users u where u.enabled)
    and exists (select 1 from public.jobs j where j.job_id = document_pilot_jobs.job_id)
  );

create table public.job_documents (
  file_id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.jobs(job_id),
  relative_path text not null check (
    length(relative_path) between 1 and 1000
    and relative_path !~ E'(^/|\\\\|:|(^|/)\\.\\.?(/|$)|//|/$|[[:cntrl:]])'
    and relative_path ~* '\.(pdf|doc|docx|xls|xlsx|txt|csv|rtf)$'
  ),
  path_key text generated always as (lower(relative_path)) stored,
  created_by uuid not null default auth.uid() references auth.users(id),
  created_at timestamptz not null default now(),
  unique(job_id, path_key)
);
create table public.job_document_versions (
  version_id uuid primary key default gen_random_uuid(),
  file_id uuid not null references public.job_documents(file_id),
  version_order bigint generated always as identity unique,
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  byte_size bigint not null check (byte_size between 1 and 52428800),
  content_type text not null check (content_type in (
    'application/pdf', 'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'text/plain', 'text/csv', 'application/rtf'
  )),
  source_modified_at timestamptz,
  provider text not null default 'supabase' check (provider = 'supabase'),
  bucket text not null default 'job-documents' check (bucket = 'job-documents'),
  object_key text generated always as (file_id::text || '/' || version_id::text) stored,
  created_by uuid not null default auth.uid() references auth.users(id),
  created_at timestamptz not null default now()
);
create index job_document_versions_file_order on public.job_document_versions(file_id, version_order desc);
-- A version is not visible as a completed import until read-back verification.
create table public.job_document_receipts (
  version_id uuid primary key references public.job_document_versions(version_id),
  verified_by uuid not null default auth.uid() references auth.users(id),
  verified_at timestamptz not null default now()
);

alter table public.job_documents enable row level security;
alter table public.job_document_versions enable row level security;
alter table public.job_document_receipts enable row level security;
revoke all on public.job_documents, public.job_document_versions, public.job_document_receipts from public, anon, authenticated;
grant select on public.job_documents, public.job_document_versions, public.job_document_receipts to authenticated;
grant insert(job_id, relative_path) on public.job_documents to authenticated;
grant insert(file_id, sha256, byte_size, content_type, source_modified_at) on public.job_document_versions to authenticated;
grant insert(version_id) on public.job_document_receipts to authenticated;

create policy documents_read on public.job_documents for select to authenticated using (
  exists (select 1 from public.document_pilot_users u where u.enabled)
  and exists (select 1 from public.jobs j where j.job_id = job_documents.job_id)
);
create policy documents_insert on public.job_documents for insert to authenticated with check (
  created_by = (select auth.uid())
  and exists (select 1 from public.document_pilot_jobs p where p.enabled and p.job_id = job_documents.job_id)
);
create policy document_versions_read on public.job_document_versions for select to authenticated using (
  exists (select 1 from public.job_documents d where d.file_id = job_document_versions.file_id)
);
create policy document_versions_insert on public.job_document_versions for insert to authenticated with check (
  created_by = (select auth.uid())
  and exists (select 1 from public.job_documents d join public.document_pilot_jobs p using(job_id)
              where d.file_id = job_document_versions.file_id and p.enabled)
);
create policy document_receipts_read on public.job_document_receipts for select to authenticated using (
  exists (select 1 from public.job_document_versions v where v.version_id = job_document_receipts.version_id)
);

insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
values ('job-documents', 'job-documents', false, 52428800, array[
  'application/pdf', 'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'text/plain', 'text/csv', 'application/rtf'
]);
-- No UPDATE or DELETE policies: an uploaded object is immutable.
create policy pilot_document_object_read on storage.objects for select to authenticated using (
  bucket_id = 'job-documents' and exists (
    select 1 from public.job_document_versions v where v.object_key = name and v.bucket = bucket_id
  )
);
create policy pilot_document_object_insert on storage.objects for insert to authenticated with check (
  bucket_id = 'job-documents' and exists (
    select 1 from public.job_document_versions v
    join public.job_documents d using(file_id)
    join public.document_pilot_jobs p using(job_id)
    where v.object_key = name and v.bucket = bucket_id and p.enabled
      and v.created_by = (select auth.uid())
      and v.created_at > now() - interval '1 hour'
  )
);
create policy document_receipts_insert on public.job_document_receipts for insert to authenticated with check (
  verified_by = (select auth.uid()) and exists (
    select 1 from public.job_document_versions v
    join public.job_documents d using(file_id)
    join public.document_pilot_jobs p using(job_id)
    join storage.objects o on o.bucket_id = v.bucket and o.name = v.object_key
    where v.version_id = job_document_receipts.version_id and p.enabled
      and v.created_by = (select auth.uid())
      and (o.metadata->>'size')::bigint = v.byte_size
  )
);

create function public.prepare_job_document(
  p_job_id uuid, p_relative_path text, p_sha256 text, p_byte_size bigint,
  p_content_type text, p_source_modified_at timestamptz default null
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  doc public.job_documents;
  version public.job_document_versions;
begin
  if auth.uid() is null or not exists (
    select 1 from public.document_pilot_jobs p where p.job_id = p_job_id and p.enabled
  ) then
    raise exception 'This job is not enabled for your document pilot.' using errcode = '42501';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_job_id::text || '/' || lower(p_relative_path), 0));
  insert into public.job_documents(job_id, relative_path) values(p_job_id, p_relative_path)
    on conflict(job_id, path_key) do nothing;
  select * into strict doc from public.job_documents where job_id = p_job_id and path_key = lower(p_relative_path);
  select v.* into version from public.job_document_versions v
    join public.job_document_receipts r using(version_id)
    where v.file_id = doc.file_id order by v.version_order desc limit 1;
  if found and version.sha256 = p_sha256 and version.byte_size = p_byte_size then
    return jsonb_build_object('action', 'unchanged', 'version', to_jsonb(version));
  end if;
  select v.* into version from public.job_document_versions v
    where v.file_id = doc.file_id and v.created_at > now() - interval '1 hour'
      and not exists(select 1 from public.job_document_receipts r where r.version_id = v.version_id)
    order by v.version_order desc limit 1;
  if found then
    if version.created_by = auth.uid() and version.sha256 = p_sha256 and version.byte_size = p_byte_size then
      return jsonb_build_object('action', 'upload', 'version', to_jsonb(version));
    end if;
    raise exception 'Another import for this document is still pending. Retry after it finishes.' using errcode = '55000';
  end if;
  insert into public.job_document_versions(file_id, sha256, byte_size, content_type, source_modified_at)
    values(doc.file_id, p_sha256, p_byte_size, p_content_type, p_source_modified_at)
    returning * into version;
  return jsonb_build_object('action', 'upload', 'version', to_jsonb(version));
end;
$$;
revoke all on function public.prepare_job_document(uuid,text,text,bigint,text,timestamptz) from public, anon;
grant execute on function public.prepare_job_document(uuid,text,text,bigint,text,timestamptz) to authenticated;
-- Receipts are idempotent and can never edit prior versions.
create function public.confirm_job_document(p_version_id uuid)
returns void language sql security invoker set search_path = '' as $$
  insert into public.job_document_receipts(version_id) values(p_version_id)
    on conflict(version_id) do nothing;
$$;
revoke all on function public.confirm_job_document(uuid) from public, anon;
grant execute on function public.confirm_job_document(uuid) to authenticated;

comment on table public.job_document_receipts is 'Client read-back SHA-256 verification receipts. Storage existence/size are checked by RLS. Not a server malware scan or server-computed checksum.';
commit;
