do $$
begin
  if to_regclass('public.crm_job_log_entries') is not null then
    alter table public.crm_job_log_entries
      add column if not exists placement_card_id text;
    create index if not exists idx_crm_job_log_placement_date
      on public.crm_job_log_entries (placement_card_id, work_date, created_at);
  end if;
end
$$;
