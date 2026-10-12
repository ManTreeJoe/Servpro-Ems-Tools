-- Run on a configured test/project connection; all sample rows roll back.
begin;
select set_config('request.jwt.claim.sub',
 (select user_id::text from public.app_user_departments where department='IE' limit 1),true);
set local role authenticated;
do $$
declare r jsonb; v bigint; n bigint;
begin
 r:=public.logs_audit_store('IE');v:=(r->>'revision')::bigint;
 r:=public.logs_audit_store('IE',v,'[{"kind":"drafts","id":"test-shared-audit","payload":{"fields":{"ems_estimator":"Mark L"}}}]');
 if (r->>'revision')::bigint<>v+1 then raise exception 'Revision did not advance'; end if;
 if not exists(select 1 from public.logs_audit_records where record_id='test-shared-audit' and updated_by=auth.uid()) then raise exception 'Missing actor'; end if;
 select count(*) into n from public.logs_audit_changes where record_id='test-shared-audit';
 if n<>1 then raise exception 'Missing history'; end if;
 begin
  perform public.logs_audit_store('IE',v,'[{"kind":"drafts","id":"test-shared-audit","payload":{}}]');
  raise exception 'Stale save succeeded';
 exception when serialization_failure then null; end;
 begin
  update public.logs_audit_records set payload='{}' where record_id='test-shared-audit';
  raise exception 'Direct write succeeded';
 exception when insufficient_privilege then null; end;
 begin
  perform public.logs_audit_store('OC');raise exception 'Other office succeeded';
 exception when insufficient_privilege then null; end;
end $$;
-- Authenticated but no office membership cannot read even through direct API.
select set_config('request.jwt.claim.sub','00000000-0000-0000-0000-000000000000',true);
do $$ begin
 if exists(select 1 from public.logs_audit_records) then raise exception 'RLS leak'; end if;
 begin
  perform public.logs_audit_store('IE');raise exception 'Nonmember RPC succeeded';
 exception when insufficient_privilege then null; end;
end $$;
reset role;
set local role anon;
do $$ begin
 begin
  perform public.logs_audit_store('IE');raise exception 'Anonymous RPC succeeded';
 exception when insufficient_privilege then null; end;
end $$;
rollback;
