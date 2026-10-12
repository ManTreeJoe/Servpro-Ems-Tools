begin;
-- Office membership is the existing app boundary. Exact Trello card IDs are
-- retained even before a legacy card has a confirmed OneLoss job/loss ID.
create table public.logs_audit_records (
 department text not null,
 kind text not null check(kind in ('drafts','operations','ar_links','legacy')),
 record_id text not null check(length(record_id) between 1 and 128),
 payload jsonb not null,
 revision bigint not null,
 updated_at timestamptz not null default now(),
 updated_by uuid not null references auth.users(id),
 primary key(department,kind,record_id)
);
create index logs_audit_records_actor on public.logs_audit_records(updated_by);
create table public.logs_audit_changes (
 id bigint generated always as identity primary key,
 department text not null, kind text not null, record_id text not null,
 revision bigint not null, payload jsonb not null,
 occurred_at timestamptz not null default now(),
 actor uuid not null references auth.users(id)
);
create index logs_audit_changes_record on public.logs_audit_changes(department,kind,record_id,id);
create index logs_audit_changes_actor on public.logs_audit_changes(actor);
create table private.logs_audit_revisions (
 department text primary key, revision bigint not null default 0
);
alter table public.logs_audit_records enable row level security;
alter table public.logs_audit_changes enable row level security;
alter table private.logs_audit_revisions enable row level security;
revoke all on public.logs_audit_records,public.logs_audit_changes,private.logs_audit_revisions from public,anon,authenticated;
grant select on public.logs_audit_records,public.logs_audit_changes to authenticated;
create policy logs_audit_read on public.logs_audit_records for select to authenticated
 using(department in (select public.my_departments()));
create policy logs_audit_history_read on public.logs_audit_changes for select to authenticated
 using(department in (select public.my_departments()));

-- Private definer ensures every write uses a revision check and appends an
-- immutable server-authenticated history record; direct client writes denied.
create function private.logs_audit_store(p_department text,p_expected bigint default null,p_changes jsonb default null)
returns jsonb language plpgsql security definer set search_path='' as $$
declare who uuid:=auth.uid(); rev bigint; change jsonb; k text; rid text; value jsonb;
begin
 if who is null or p_department is distinct from 'IE' or not exists(
 select 1 from public.app_user_departments where user_id=who and department=p_department)
 then raise exception 'Logs audit office access required' using errcode='42501'; end if;
 -- One consistent snapshot includes drafts, pending publication and AR links.
 -- The short transaction lock never spans a Trello/network operation.
 perform pg_advisory_xact_lock(hashtextextended('logs-audit:'||p_department,0));
 insert into private.logs_audit_revisions(department) values(p_department) on conflict do nothing;
 select revision into rev from private.logs_audit_revisions where department=p_department;
 if p_changes is not null then
  if p_expected is distinct from rev then raise exception 'Audit changed on another device. Reopen the job before saving.' using errcode='40001'; end if;
  if jsonb_typeof(p_changes) is distinct from 'array' or jsonb_array_length(p_changes)>1000
   or octet_length(p_changes::text)>50000000 then raise exception 'Invalid audit changes'; end if;
  rev:=rev+1;
  for change in select * from jsonb_array_elements(p_changes) loop
   k:=change->>'kind';rid:=change->>'id';value:=change->'payload';
   if k is null or k not in ('drafts','operations','ar_links','legacy') or rid is null or length(rid) not between 1 and 128
    or value is null then raise exception 'Invalid audit record'; end if;
   if value <> 'null'::jsonb and ((k='ar_links' and jsonb_typeof(value)<>'string')
    or (k<>'ar_links' and jsonb_typeof(value)<>'object')) then raise exception 'Invalid audit payload'; end if;
   if k='legacy' and exists(select 1 from public.logs_audit_records where department=p_department and kind=k and record_id=rid)
    then raise exception 'Legacy audit backup is immutable'; end if;
   insert into public.logs_audit_records(department,kind,record_id,payload,revision,updated_by)
    values(p_department,k,rid,value,rev,who) on conflict(department,kind,record_id)
    do update set payload=excluded.payload,revision=excluded.revision,updated_by=excluded.updated_by,updated_at=now();
   insert into public.logs_audit_changes(department,kind,record_id,revision,payload,actor)
    values(p_department,k,rid,rev,value,who);
  end loop;
  update private.logs_audit_revisions set revision=rev where department=p_department;
 end if;
 return jsonb_build_object('revision',rev,'records',coalesce((select jsonb_agg(
 jsonb_build_object('kind',kind,'id',record_id,'payload',case when kind='legacy' then '{}'::jsonb else payload end)) from public.logs_audit_records
 where department=p_department),'[]'::jsonb));
end $$;
revoke all on function private.logs_audit_store(text,bigint,jsonb) from public,anon,authenticated;
grant usage on schema private to authenticated;
grant execute on function private.logs_audit_store(text,bigint,jsonb) to authenticated;
create function public.logs_audit_store(p_department text,p_expected bigint default null,p_changes jsonb default null)
returns jsonb language sql security invoker set search_path='' as $$
 select private.logs_audit_store(p_department,p_expected,p_changes);
$$;
revoke all on function public.logs_audit_store(text,bigint,jsonb) from public,anon;
grant execute on function public.logs_audit_store(text,bigint,jsonb) to authenticated;
commit;
