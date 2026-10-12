-- Visits have their own identity; a job may need several separate visits.
-- Keep schedule_source_once and operation receipts for import/retry safety.
drop index public.schedule_one_active_job;

create or replace function private.import_schedule_entries(p_department text, p_entries jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
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
   saved:=private.save_schedule_entry(c);added:=added+1;
   if saved->'job_id'='null'::jsonb then unlinked:=unlinked+1; end if;
 end loop;
 return jsonb_build_object('added',added,'already_imported',reused,'needs_link',unlinked);
end $$;
