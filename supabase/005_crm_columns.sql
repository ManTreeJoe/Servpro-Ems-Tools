-- Linguar Hub — schema v6: promote the queryable job facts out of JSON.
--
-- These facts have always been parsed off the Trello card description by
-- `job_settings`, but only four of them had columns (claim_number,
-- carrier, loss_type, date_received). The rest lived in metadata_json,
-- where nothing can filter, group or report on them — "every AAA claim",
-- "every job for this adjuster", "losses in July" were all unanswerable.
--
-- TEXT on purpose, including the dates. The card holds whatever the
-- office typed ("7/2/26", "07-02-2026", "early July"); a DATE column
-- would reject the row rather than store what we were told. Normalising
-- is a separate, later job.
--
-- Run in the Supabase SQL editor. Idempotent — safe to re-run.

alter table jobs add column if not exists address        text;
alter table jobs add column if not exists phone          text;
alter table jobs add column if not exists email          text;
alter table jobs add column if not exists adjuster_name  text;
alter table jobs add column if not exists adjuster_email text;
alter table jobs add column if not exists adjuster_phone text;
alter table jobs add column if not exists agent_name     text;
alter table jobs add column if not exists deductible     text;
alter table jobs add column if not exists date_of_loss   text;
alter table jobs add column if not exists xa_id          text;
alter table jobs add column if not exists wc_project_id  text;

-- The three people actually search by. Carrier and adjuster drive the
-- "who do I chase" reports; wc_project_id is how a job is looked up in
-- WorkCenter, so it has to be findable from either direction.
create index if not exists idx_jobs_carrier
    on jobs (carrier) where carrier is not null;
create index if not exists idx_jobs_adjuster
    on jobs (adjuster_name) where adjuster_name is not null;
create index if not exists idx_jobs_wc_project
    on jobs (wc_project_id) where wc_project_id is not null;

update meta set value = '6' where key = 'schema_version';
insert into meta (key, value) select 'schema_version', '6'
where not exists (select 1 from meta where key = 'schema_version');

-- Verify
select column_name, data_type
from information_schema.columns
where table_name = 'jobs'
order by ordinal_position;
