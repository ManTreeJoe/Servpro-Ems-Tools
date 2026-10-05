-- Digital drafts only. No Word, Trello, job-fact or comment writes.
begin;
create schema if not exists private;

create table public.schedule_visits (
 id uuid primary key,
 job_id uuid not null references public.jobs(job_id),
 department text not null,
 payload jsonb not null,
 revision bigint not null check(revision > 0),
 position numeric not null,
 queue_entered_at timestamptz not null default now(),
 updated_at timestamptz not null default now(),
 updated_by uuid not null references auth.users(id)
);
create unique index schedule_one_active_job on public.schedule_visits(job_id)
 where payload->>'status' = 'active';
create index schedule_department_order on public.schedule_visits(department,position,id);
create index schedule_job_history on public.schedule_visits(job_id);
create index schedule_updated_actor on public.schedule_visits(updated_by);
create table public.schedule_changes (
 operation_id uuid primary key,
 visit_id uuid not null references public.schedule_visits(id),
 department text not null,
 actor uuid not null references auth.users(id),
 command jsonb not null,
 result jsonb not null,
 occurred_at timestamptz not null default now()
);
create index schedule_changes_visit on public.schedule_changes(visit_id,occurred_at);
create index schedule_changes_actor on public.schedule_changes(actor);
alter table public.schedule_visits enable row level security;
alter table public.schedule_changes enable row level security;
revoke all on public.schedule_visits,public.schedule_changes from public,anon,authenticated;
grant select on public.schedule_visits,public.schedule_changes to authenticated;
create policy schedule_read on public.schedule_visits for select to authenticated using (
 department in (select public.my_departments()) and exists (
 select 1 from public.jobs j where j.job_id=schedule_visits.job_id and j.department=schedule_visits.department));
create policy schedule_history_read on public.schedule_changes for select to authenticated using (
 exists(select 1 from public.schedule_visits v where v.id=schedule_changes.visit_id));

create function private.valid_schedule_payload(p jsonb) returns boolean
language plpgsql immutable set search_path='' as $$
declare a jsonb; person jsonb; k text; labels text[] := '{}'; people text[]; d date;
begin
 if jsonb_typeof(p) is distinct from 'object' then return false; end if;
 if (select count(*) from jsonb_object_keys(p)) <> 12 or exists (
   select 1 from jsonb_object_keys(p) x where x not in
   ('id','job_id','queue','group','date','arrival','activities','equipment','access','notes','status','contract_version')) then return false; end if;
 if p->'contract_version' <> '1'::jsonb then return false; end if;
 perform (p->>'id')::uuid, (p->>'job_id')::uuid;
 if p->>'id' is null or p->>'job_id' is null then return false; end if;
 if not ((p->>'queue'='scheduled' and p->>'group' in ('Monitor','Work To Be Performed'))
 or (p->>'queue'='tbs' and p->>'group' in ('TBS New Loss /Reinspection','TBS Mitigation','TBS Contents'))
 or (p->>'queue'='pending' and p->>'group' in ('Pending Testing/Clearance/Abatement','Pending Approvals – Insurance/Self Pay','Pending Approvals – Property Management'))
 or (p->>'queue'='hold' and p->>'group'='On Hold')) then return false; end if;
 if p->>'status' not in ('active','completed','canceled') then return false; end if;
 foreach k in array array['id','job_id','queue','group','status','arrival','equipment','access','notes'] loop
   if jsonb_typeof(p->k) is distinct from 'string' then return false; end if;
 end loop;
 if length(p->>'arrival')>120 or length(p->>'equipment')>4000 or length(p->>'access')>4000 or length(p->>'notes')>4000 then return false; end if;
 if p->>'queue'='scheduled' then
   if jsonb_typeof(p->'date') is distinct from 'string' or p->>'date' !~ '^\d{4}-\d{2}-\d{2}$' then return false; end if;
   d := (p->>'date')::date;
 else
   if p->'date' is distinct from 'null'::jsonb then return false; end if;
 end if;
 if jsonb_typeof(p->'activities') is distinct from 'array' then return false; end if;
 if jsonb_array_length(p->'activities') not between 1 and 30 then return false; end if;
 for a in select value from jsonb_array_elements(p->'activities') loop
   if jsonb_typeof(a) is distinct from 'object' then return false; end if;
   if (select count(*) from jsonb_object_keys(a)) <> 2 or jsonb_typeof(a->'label') is distinct from 'string' or jsonb_typeof(a->'people') is distinct from 'array' then return false; end if;
   if length(btrim(a->>'label')) not between 1 and 120 or lower(btrim(a->>'label'))=any(labels) then return false; end if;
   labels:=array_append(labels,lower(btrim(a->>'label'))); people:='{}';
   if jsonb_array_length(a->'people')>30 then return false; end if;
   for person in select value from jsonb_array_elements(a->'people') loop
     if jsonb_typeof(person) is distinct from 'string' or length(btrim(person#>>'{}')) not between 1 and 120 or lower(btrim(person#>>'{}'))=any(people) then return false; end if;
     people:=array_append(people,lower(btrim(person#>>'{}')));
   end loop;
 end loop;
 return true;
exception when others then return false;
end $$;
revoke all on function private.valid_schedule_payload(jsonb) from public,anon,authenticated;
alter table public.schedule_visits add constraint schedule_payload_valid check(private.valid_schedule_payload(payload));
alter table public.schedule_visits add constraint schedule_payload_identity check (
 (payload->>'id')::uuid=id and (payload->>'job_id')::uuid=job_id);

-- Private definer is needed to deny all direct client mutations and make
-- revision/idempotency/history enforcement unavoidable. Authorization is
-- explicit against current membership and job department, never JWT metadata.
create function private.save_schedule_draft(p_command jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare
 who uuid:=auth.uid(); dept text:=p_command->>'department';
 v jsonb:=p_command->'visit'; previous public.schedule_visits;
 saved public.schedule_visits; receipt public.schedule_changes;
 op uuid:=(p_command->>'operation_id')::uuid; vid uuid:=(v->>'id')::uuid;
 jid uuid:=(v->>'job_id')::uuid; expected bigint; pos numeric; low_pos numeric;
 before_id uuid:=nullif(p_command->>'before_id','')::uuid; anchor public.schedule_visits;
begin
 if who is null or dept is null or op is null then raise exception 'Sign in and select an office' using errcode='42501'; end if;
 if jsonb_typeof(p_command) is distinct from 'object' or octet_length(p_command::text)>100000 or exists (
 select 1 from jsonb_object_keys(p_command) x where x not in ('contract_version','department','operation_id','expected_revision','visit','before_id')) then
 raise exception 'Invalid schedule command'; end if;
 if p_command->'contract_version' is distinct from '1'::jsonb or
 jsonb_typeof(p_command->'expected_revision') is distinct from 'number' or
 p_command->>'expected_revision' !~ '^[0-9]+$' then raise exception 'Invalid schedule command'; end if;
 expected:=(p_command->>'expected_revision')::bigint;
 v:=v||jsonb_build_object('contract_version',1);
 if not private.valid_schedule_payload(v) then raise exception 'Invalid visit details'; end if;
 if not exists(select 1 from public.app_user_departments m where m.user_id=who and m.department=dept)
 or not exists(select 1 from public.jobs j where j.job_id=jid and j.department=dept) then
 raise exception 'Job is unavailable in this office' using errcode='42501'; end if;
 -- Serialize placement operations per office; same operation retries are safe.
 perform pg_advisory_xact_lock(hashtextextended('schedule:'||dept,0));
 select * into receipt from public.schedule_changes where operation_id=op;
 if found then
   if receipt.actor<>who or receipt.command<>p_command then raise exception 'Operation ID reused'; end if;
   return receipt.result;
 end if;
 select * into previous from public.schedule_visits where id=vid for update;
 if found then
   if previous.job_id<>jid or previous.department<>dept then raise exception 'Visit identity cannot change' using errcode='42501'; end if;
   if previous.revision<>expected then raise exception 'Visit changed elsewhere. Reload before saving.' using errcode='40001'; end if;
 else
   if expected<>0 then raise exception 'Visit no longer exists' using errcode='40001'; end if;
 end if;
 pos:=previous.position;
 if before_id is not null then
   select * into anchor from public.schedule_visits where id=before_id and department=dept and id<>vid;
   if not found or anchor.payload->>'queue'<>v->>'queue' or anchor.payload->>'group'<>v->>'group' or anchor.payload->'date'<>v->'date' then raise exception 'Drop destination changed. Try again.' using errcode='40001'; end if;
   select max(position) into low_pos from public.schedule_visits where department=dept and position<anchor.position and id<>vid;
   pos:=(coalesce(low_pos,anchor.position-2)+anchor.position)/2;
 elsif pos is null or p_command ? 'before_id' then
   select coalesce(max(position),0)+1 into pos from public.schedule_visits where department=dept;
 end if;
 insert into public.schedule_visits(id,job_id,department,payload,revision,position,updated_by)
 values(vid,jid,dept,v,1,pos,who)
 on conflict(id) do update set payload=excluded.payload, revision=schedule_visits.revision+1,
 position=excluded.position,updated_by=who,updated_at=now(),
 queue_entered_at=case when schedule_visits.payload->>'queue'<>excluded.payload->>'queue' then now() else schedule_visits.queue_entered_at end
 returning * into saved;
 insert into public.schedule_changes(operation_id,visit_id,department,actor,command,result)
 values(op,vid,dept,who,p_command,to_jsonb(saved));
 return to_jsonb(saved);
end $$;
revoke all on function private.save_schedule_draft(jsonb) from public,anon,authenticated;
grant usage on schema private to authenticated;
grant execute on function private.save_schedule_draft(jsonb) to authenticated;
create function public.save_schedule_draft(p_command jsonb) returns jsonb
language sql security invoker set search_path='' as $$select private.save_schedule_draft(p_command)$$;
revoke all on function public.save_schedule_draft(jsonb) from public,anon,authenticated;
grant execute on function public.save_schedule_draft(jsonb) to authenticated;
commit;
