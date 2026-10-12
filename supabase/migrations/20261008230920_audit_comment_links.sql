begin;
alter table public.logs_audit_records drop constraint logs_audit_records_kind_check;
alter table public.logs_audit_records add constraint logs_audit_records_kind_check
 check(kind in ('drafts','operations','ar_links','legacy','links'));
-- Extend the existing CAS/history writer without changing its permissions.
do $$ declare definition text; begin
 definition:=pg_get_functiondef('private.logs_audit_store(text,bigint,jsonb)'::regprocedure);
 if position('''drafts'',''operations'',''ar_links'',''legacy''' in definition)=0 then
  raise exception 'Unexpected audit storage function; review migration';
 end if;
 execute replace(definition,'''drafts'',''operations'',''ar_links'',''legacy''',
                            '''drafts'',''operations'',''ar_links'',''legacy'',''links''');
end $$;
commit;
