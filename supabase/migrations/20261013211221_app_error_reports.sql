begin;
create table private.app_error_reports (
 id uuid primary key default gen_random_uuid(),
 occurred_at timestamptz not null default clock_timestamp(),
 user_id uuid not null, department text not null, report jsonb not null
);
alter table private.app_error_reports enable row level security;
revoke all on private.app_error_reports from public, anon, authenticated;
create index app_error_reports_user_time on private.app_error_reports(user_id, occurred_at);

create function private.report_app_error(p_report jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare uid uuid:=auth.uid(); k text; v text;
begin
 if uid is null or not exists(select 1 from public.app_user_departments
   where user_id=uid and department=p_report->>'department') then
   raise exception 'Office access required' using errcode='42501'; end if;
 if jsonb_typeof(p_report) is distinct from 'object' or octet_length(p_report::text)>2000 then
   raise exception 'Invalid diagnostic'; end if;
 for k,v in select key,value from jsonb_each_text(p_report) loop
   if k not in ('department','panel','action','code','table_name','cached','app_version','channel','fingerprint')
     or v is null or v !~ '^[A-Za-z0-9_.-]{0,100}$' then raise exception 'Invalid diagnostic field'; end if;
 end loop;
 if coalesce(p_report->>'fingerprint','') !~ '^[a-f0-9]{64}$' then raise exception 'Invalid fingerprint'; end if;
 perform pg_advisory_xact_lock(hashtextextended('app-errors:'||uid::text,0));
 if exists(select 1 from private.app_error_reports where user_id=uid
     and department=p_report->>'department' and report=p_report
     and occurred_at>clock_timestamp()-interval '5 minutes') then
   return '{"ok":true,"duplicate":true}'::jsonb; end if;
 if (select count(*) from private.app_error_reports where user_id=uid
     and occurred_at>clock_timestamp()-interval '1 day')>=200 then
   return '{"ok":false,"limited":true}'::jsonb; end if;
 insert into private.app_error_reports(user_id,department,report)
 values(uid,p_report->>'department',p_report);
 return '{"ok":true}'::jsonb;
end $$;
revoke all on function private.report_app_error(jsonb) from public,anon;
grant execute on function private.report_app_error(jsonb) to authenticated;
create function public.report_app_error(p_report jsonb) returns jsonb
language sql security invoker set search_path='' as $$
 select private.report_app_error(p_report);
$$;
revoke all on function public.report_app_error(jsonb) from public,anon;
grant execute on function public.report_app_error(jsonb) to authenticated;
commit;
