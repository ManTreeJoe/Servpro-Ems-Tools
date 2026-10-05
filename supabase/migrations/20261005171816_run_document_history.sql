begin;
create schema if not exists private;
create table public.run_history_documents (
 id uuid primary key default gen_random_uuid(), department text not null,
 run_date date not null, source_digest text not null check(source_digest ~ '^[a-f0-9]{64}$'),
 filename text not null check(length(filename) between 1 and 500),
 snapshot jsonb not null check(jsonb_typeof(snapshot)='object'),
 imported_by uuid not null references auth.users(id), imported_at timestamptz not null default now(),
 unique(department,run_date,source_digest)
);
create table public.run_history_rows (
 id uuid primary key default gen_random_uuid(), document_id uuid not null references public.run_history_documents(id),
 source_index integer not null, raw_text text not null, section text not null, struck boolean not null,
 job_id uuid references public.jobs(job_id), revision bigint not null default 1,
 unique(document_id,source_index)
);
create index run_history_date on public.run_history_documents(department,run_date);
create index run_history_job on public.run_history_rows(job_id);
create index run_history_importer on public.run_history_documents(imported_by);
create table public.run_history_link_changes (
 id bigint generated always as identity primary key, row_id uuid not null references public.run_history_rows(id),
 old_job_id uuid, new_job_id uuid, actor uuid not null references auth.users(id),
 occurred_at timestamptz not null default now(), revision bigint not null
);
create index run_history_changes_row on public.run_history_link_changes(row_id);
create index run_history_changes_actor on public.run_history_link_changes(actor);
alter table public.run_history_documents enable row level security;
alter table public.run_history_rows enable row level security;
alter table public.run_history_link_changes enable row level security;
revoke all on public.run_history_documents,public.run_history_rows,public.run_history_link_changes from public,anon,authenticated;
grant select on public.run_history_documents,public.run_history_rows,public.run_history_link_changes to authenticated;
create policy history_documents_read on public.run_history_documents for select to authenticated using(department in(select public.my_departments()));
create policy history_rows_read on public.run_history_rows for select to authenticated using(exists(select 1 from public.run_history_documents d where d.id=document_id));
create policy history_changes_read on public.run_history_link_changes for select to authenticated using(exists(select 1 from public.run_history_rows r where r.id=row_id));

-- Definer enforces immutable source records and revision-checked link corrections.
-- Only these narrow operations may mutate history; every operation checks office access.
create function private.import_run_history(p_department text,p_document jsonb) returns uuid
language plpgsql security definer set search_path='' as $$
declare doc uuid; item jsonb; jid uuid;
begin
 if auth.uid() is null or not exists(select 1 from public.my_departments() d where d=p_department) then raise exception 'Office access required' using errcode='42501'; end if;
 if jsonb_typeof(p_document->'rows') is distinct from 'array' or jsonb_array_length(p_document->'rows')>2000 or octet_length(p_document::text)>4000000 then raise exception 'Invalid history document'; end if;
 insert into public.run_history_documents(department,run_date,source_digest,filename,snapshot,imported_by)
 values(p_department,(p_document->>'run_date')::date,p_document->>'source_digest',p_document->>'filename',p_document->'snapshot',auth.uid())
 on conflict(department,run_date,source_digest) do nothing returning id into doc;
 if doc is null then
  select id into doc from public.run_history_documents where department=p_department and run_date=(p_document->>'run_date')::date and source_digest=p_document->>'source_digest';
  return doc;
 end if;
 for item in select value from jsonb_array_elements(p_document->'rows') loop
  jid:=(item->>'job_id')::uuid;
  if jid is not null and not exists(select 1 from public.jobs j where j.job_id=jid and j.department=p_department) then raise exception 'Job unavailable' using errcode='42501'; end if;
  insert into public.run_history_rows(document_id,source_index,raw_text,section,struck,job_id)
  values(doc,(item->>'source_index')::integer,item->>'raw_text',item->>'section',(item->>'struck')::boolean,jid);
 end loop;
 return doc;
end $$;
create function private.link_run_history(p_row uuid,p_job uuid,p_revision bigint) returns bigint
language plpgsql security definer set search_path='' as $$
declare r public.run_history_rows; office text;
begin
 select * into r from public.run_history_rows where id=p_row for update;
 select department into office from public.run_history_documents where id=r.document_id;
 if auth.uid() is null or office is null or not exists(select 1 from public.my_departments() d where d=office) then raise exception 'Office access required' using errcode='42501'; end if;
 if p_job is not null and not exists(select 1 from public.jobs j where j.job_id=p_job and j.department=office) then raise exception 'Job unavailable' using errcode='42501'; end if;
 if r.job_id is not distinct from p_job then return r.revision; end if;
 if r.revision is distinct from p_revision then raise exception 'History link changed elsewhere. Reopen this entry.' using errcode='40001'; end if;
 update public.run_history_rows set job_id=p_job,revision=revision+1 where id=p_row;
 insert into public.run_history_link_changes(row_id,old_job_id,new_job_id,actor,revision) values(p_row,r.job_id,p_job,auth.uid(),r.revision+1);
 return r.revision+1;
end $$;
revoke all on function private.import_run_history(text,jsonb),private.link_run_history(uuid,uuid,bigint) from public,anon,authenticated;
grant usage on schema private to authenticated;
grant execute on function private.import_run_history(text,jsonb),private.link_run_history(uuid,uuid,bigint) to authenticated;
create function public.import_run_history(p_department text,p_document jsonb) returns uuid language sql security invoker set search_path='' as $$select private.import_run_history(p_department,p_document)$$;
create function public.link_run_history(p_row uuid,p_job uuid,p_revision bigint) returns bigint language sql security invoker set search_path='' as $$select private.link_run_history(p_row,p_job,p_revision)$$;
revoke all on function public.import_run_history(text,jsonb),public.link_run_history(uuid,uuid,bigint) from public,anon;
grant execute on function public.import_run_history(text,jsonb),public.link_run_history(uuid,uuid,bigint) to authenticated;
commit;
