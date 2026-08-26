-- Linguar Hub — schema v9: master job CRM foundation.
--
-- One real job remains one row in `jobs`. `job_id` is the permanent handle
-- that survives renames; `canon_key` remains the compatibility key used by
-- existing Trello/folder tools. Overall lifecycle is deliberately separate
-- from Trello list names, and EMS / Contents / Recon each get their own state.
--
-- Existing rows are marked legacy_unclassified. We cannot honestly claim
-- they entered Intake today; reconciliation can assign their real stage.
-- New rows default to Intake so every future job is tracked from its start.
-- Idempotent: safe to run more than once.

create extension if not exists pgcrypto;

alter table jobs add column if not exists job_id uuid default gen_random_uuid();
update jobs set job_id = gen_random_uuid() where job_id is null;
create unique index if not exists idx_jobs_job_id on jobs(job_id);
alter table jobs alter column job_id set not null;

alter table jobs add column if not exists lifecycle_stage text;
alter table jobs add column if not exists stage_entered_at text;
alter table jobs add column if not exists job_type text;
alter table jobs add column if not exists priority text default 'normal';
alter table jobs add column if not exists closed_at text;

update jobs
set lifecycle_stage = 'legacy_unclassified'
where lifecycle_stage is null or btrim(lifecycle_stage) = '';

alter table jobs alter column lifecycle_stage set default 'intake';
alter table jobs alter column lifecycle_stage set not null;

alter table jobs drop constraint if exists jobs_lifecycle_stage_check;
alter table jobs add constraint jobs_lifecycle_stage_check check (
  lifecycle_stage in (
    'intake', 'contacted', 'scheduled', 'active', 'monitoring',
    'ready_for_billing', 'closeout', 'closed', 'legacy_unclassified'
  )
);
alter table jobs drop constraint if exists jobs_job_type_check;
alter table jobs add constraint jobs_job_type_check check (
  job_type is null or job_type in
    ('insurance', 'self_pay', 'commercial', 'management')
);
alter table jobs drop constraint if exists jobs_priority_check;
alter table jobs add constraint jobs_priority_check check (
  priority is null or priority in ('low', 'normal', 'high', 'urgent')
);
create index if not exists idx_jobs_lifecycle_stage
  on jobs(lifecycle_stage);

create table if not exists crm_job_departments (
  job_id             uuid not null references jobs(job_id) on delete cascade,
  work_environment   text not null check (
    work_environment in ('EMS', 'Contents', 'Recon')),
  stage              text,
  status             text,
  owner              text,
  stage_entered_at   text,
  started_at         text,
  completed_at       text,
  updated_at         text not null,
  primary key (job_id, work_environment)
);
create index if not exists idx_crm_departments_stage
  on crm_job_departments(work_environment, stage);

create table if not exists crm_job_relationships (
  job_id             uuid not null references jobs(job_id) on delete cascade,
  related_job_id     uuid not null references jobs(job_id) on delete cascade,
  relationship_type text not null,
  created_at         text not null,
  created_by         text,
  primary key (job_id, related_job_id, relationship_type),
  check (job_id <> related_job_id)
);

alter table crm_job_departments enable row level security;
alter table crm_job_relationships enable row level security;

drop policy if exists crm_job_departments_rw on crm_job_departments;
create policy crm_job_departments_rw on crm_job_departments
  for all to authenticated
  using (exists (select 1 from jobs j where j.job_id = crm_job_departments.job_id))
  with check (exists (select 1 from jobs j where j.job_id = crm_job_departments.job_id));

drop policy if exists crm_job_relationships_rw on crm_job_relationships;
create policy crm_job_relationships_rw on crm_job_relationships
  for all to authenticated
  using (
    exists (select 1 from jobs j where j.job_id = crm_job_relationships.job_id)
    and exists (select 1 from jobs j where j.job_id = crm_job_relationships.related_job_id)
  )
  with check (
    exists (select 1 from jobs j where j.job_id = crm_job_relationships.job_id)
    and exists (select 1 from jobs j where j.job_id = crm_job_relationships.related_job_id)
  );

update meta set value = '9' where key = 'schema_version';
insert into meta (key, value) values ('schema_version', '9')
  on conflict (key) do update set value = excluded.value;

-- Verification: no missing/duplicate stable IDs and expected CRM columns.
select count(*) as jobs,
       count(job_id) as with_id,
       count(distinct job_id) as distinct_ids
from jobs;
