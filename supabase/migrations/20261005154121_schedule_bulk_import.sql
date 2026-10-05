begin;
alter table public.schedule_visits alter column job_id drop not null;
alter table public.schedule_visits add column entry_title text not null default '' check(length(entry_title)<=300);
alter table public.schedule_visits add column source_key text check(length(source_key)<=160);
create unique index schedule_source_once on public.schedule_visits(department,source_key) where source_key is not null;
alter function private.valid_schedule_payload(jsonb) rename to valid_schedule_payload_linked;
create function private.valid_schedule_payload(p jsonb) returns boolean language sql immutable set search_path='' as $$
 select private.valid_schedule_payload_linked(case when p->'job_id'='null'::jsonb then
 jsonb_set(p,'{job_id}','"00000000-0000-4000-8000-000000000000"'::jsonb) else p end)
$$;
revoke all on function private.valid_schedule_payload(jsonb) from public,anon,authenticated;
alter table public.schedule_visits drop constraint schedule_payload_valid;
alter table public.schedule_visits add constraint schedule_payload_valid check(private.valid_schedule_payload(payload));
alter table public.schedule_visits drop constraint schedule_payload_identity;
alter table public.schedule_visits add constraint schedule_payload_identity check(
 (payload->>'id')::uuid=id and (payload->>'job_id')::uuid is not distinct from job_id);
alter table public.schedule_visits add constraint schedule_unlinked_title check(job_id is not null or length(btrim(entry_title))>0);
drop policy schedule_read on public.schedule_visits;
create policy schedule_read on public.schedule_visits for select to authenticated using(
 department in(select public.my_departments()) and (job_id is null or exists(
 select 1 from public.jobs j where j.job_id=schedule_visits.job_id and j.department=schedule_visits.department)));

create function private.save_schedule_entry(c jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare who uuid:=auth.uid(); dept text:=c->>'department'; v jsonb:=c->'visit';
 vid uuid:=(v->>'id')::uuid; jid uuid:=(v->>'job_id')::uuid; op uuid:=(c->>'operation_id')::uuid;
 expected bigint; previous public.schedule_visits; saved public.schedule_visits; receipt public.schedule_changes;
 anchor public.schedule_visits; before_id uuid:=(c->>'before_id')::uuid; pos numeric; low_pos numeric;
 title text:=c->>'entry_title'; source text:=c->>'source_key';
begin
 if who is null or dept is null or not exists(select 1 from public.app_user_departments m where m.user_id=who and m.department=dept) then raise exception 'Office access required' using errcode='42501'; end if;
 if c->'contract_version' is distinct from '2'::jsonb or op is null or vid is null or
 jsonb_typeof(c->'expected_revision') is distinct from 'number' or c->>'expected_revision' !~ '^[0-9]+$' or
 jsonb_typeof(c->'entry_title') is distinct from 'string' or length(title)>300 or (jid is null and length(btrim(title))=0) or
 (source is not null and (length(source)>160 or length(source)=0)) or octet_length(c::text)>100000 then raise exception 'Invalid schedule entry'; end if;
 expected:=(c->>'expected_revision')::bigint;
 v:=v||jsonb_build_object('contract_version',1);
 if not private.valid_schedule_payload(v) then raise exception 'Invalid visit details'; end if;
 if jid is not null and not exists(select 1 from public.jobs where job_id=jid and department=dept) then raise exception 'Job unavailable in office' using errcode='42501'; end if;
 perform pg_advisory_xact_lock(hashtextextended('schedule:'||dept,0));
 select * into receipt from public.schedule_changes where operation_id=op;
 if found then
   if receipt.actor<>who or receipt.command<>c then raise exception 'Operation ID reused'; end if;
   return receipt.result;
 end if;
 select * into previous from public.schedule_visits where id=vid for update;
 if found then
   if previous.department<>dept or (previous.job_id is not null and not exists(select 1 from public.jobs where job_id=previous.job_id and department=dept)) then raise exception 'Visit unavailable in office' using errcode='42501'; end if;
   if previous.revision<>expected then raise exception 'Visit changed elsewhere' using errcode='40001'; end if;
   if previous.source_key is distinct from source then raise exception 'Import source cannot change'; end if;
 elsif expected<>0 then raise exception 'Visit no longer exists' using errcode='40001'; end if;
 pos:=previous.position;
 if before_id is not null then
   select * into anchor from public.schedule_visits where id=before_id and department=dept and id<>vid;
   if not found or anchor.payload->>'queue'<>v->>'queue' or anchor.payload->>'group'<>v->>'group' or anchor.payload->'date'<>v->'date' then raise exception 'Drop destination changed' using errcode='40001'; end if;
   select max(position) into low_pos from public.schedule_visits where department=dept and position<anchor.position and id<>vid;
   pos:=(coalesce(low_pos,anchor.position-2)+anchor.position)/2;
 elsif pos is null or c ? 'before_id' then select coalesce(max(position),0)+1 into pos from public.schedule_visits where department=dept; end if;
 insert into public.schedule_visits(id,job_id,department,payload,revision,position,updated_by,entry_title,source_key)
 values(vid,jid,dept,v,1,pos,who,title,source)
 on conflict(id) do update set job_id=excluded.job_id,payload=excluded.payload,revision=schedule_visits.revision+1,
 position=excluded.position,updated_by=who,updated_at=now(),entry_title=excluded.entry_title,
 queue_entered_at=case when schedule_visits.payload->>'queue'<>excluded.payload->>'queue' then now() else schedule_visits.queue_entered_at end
 returning * into saved;
 insert into public.schedule_changes(operation_id,visit_id,department,actor,command,result) values(op,vid,dept,who,c,to_jsonb(saved));
 return to_jsonb(saved);
end $$;
revoke all on function private.save_schedule_entry(jsonb) from public,anon,authenticated;
grant execute on function private.save_schedule_entry(jsonb) to authenticated;
create function public.save_schedule_entry(p_command jsonb) returns jsonb language sql security invoker set search_path='' as $$select private.save_schedule_entry(p_command)$$;
revoke all on function public.save_schedule_entry(jsonb) from public,anon,authenticated;
grant execute on function public.save_schedule_entry(jsonb) to authenticated;

create function private.import_schedule_entries(p_department text,p_entries jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare c jsonb; saved jsonb; previous public.schedule_visits; jid uuid; added int:=0; reused int:=0; unlinked int:=0;
begin
 if auth.uid() is null or not exists(select 1 from public.app_user_departments where user_id=auth.uid() and department=p_department) then raise exception 'Office access required' using errcode='42501'; end if;
 if jsonb_typeof(p_entries) is distinct from 'array' or jsonb_array_length(p_entries)>500 or octet_length(p_entries::text)>5000000 then raise exception 'Import must contain at most 500 entries'; end if;
 perform pg_advisory_xact_lock(hashtextextended('schedule:'||p_department,0));
 for c in select value from jsonb_array_elements(p_entries) loop
   if c->>'department' is distinct from p_department or c->>'source_key' is null or c->'expected_revision' is distinct from '0'::jsonb then raise exception 'Invalid import entry'; end if;
   select * into previous from public.schedule_visits where department=p_department and source_key=c->>'source_key';
   if found then reused:=reused+1; continue; end if;
   jid:=(c->'visit'->>'job_id')::uuid;
   if jid is not null and not exists(select 1 from public.jobs where job_id=jid and department=p_department) then raise exception 'Job unavailable in office' using errcode='42501'; end if;
   -- Never overwrite a previously scheduled job: retain the new source as needs-link.
   if jid is not null and exists(select 1 from public.schedule_visits where job_id=jid and payload->>'status'='active') then
     c:=jsonb_set(c,'{visit,job_id}','null'::jsonb);
   end if;
   saved:=private.save_schedule_entry(c);added:=added+1;
   if saved->'job_id'='null'::jsonb then unlinked:=unlinked+1; end if;
 end loop;
 return jsonb_build_object('added',added,'already_imported',reused,'needs_link',unlinked);
end $$;
revoke all on function private.import_schedule_entries(text,jsonb) from public,anon,authenticated;
grant execute on function private.import_schedule_entries(text,jsonb) to authenticated;
create function public.import_schedule_entries(p_department text,p_entries jsonb) returns jsonb language sql security invoker set search_path='' as $$select private.import_schedule_entries(p_department,p_entries)$$;
revoke all on function public.import_schedule_entries(text,jsonb) from public,anon,authenticated;
grant execute on function public.import_schedule_entries(text,jsonb) to authenticated;
commit;
