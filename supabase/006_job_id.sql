-- Linguar Hub — schema v7: give every job a stable id.
--
-- Today the primary key IS the name: `jobs.canon_key` is derived from
-- display_name, and job_aliases / job_links / job_events all reference
-- it. So identity moves whenever the name moves — "Seth Knudsen" and
-- "Knudsen, Seth - Mercury" canonicalise to different keys and become
-- two different jobs for one insured.
--
-- `job_id` is the thing that never changes. It is assigned once, at
-- creation, and survives every rename. When two rows are folded together
-- the survivor keeps its id and the folded one is recorded in job_events,
-- so an older reference can still be traced to where it went.
--
-- ⚠ An id alone does NOT stop the splitting — it would just mint two ids
-- for one person. It is the anchor; swap-aware resolution at creation is
-- what stops the second row being made. They go together.
--
-- canon_key stays the primary key here on purpose. Re-pointing four
-- foreign keys, every pin in state.json and persistence._canon_pin_key
-- is a migration of a different size, and nothing needs it yet: what
-- needs a stable handle is everything that points AT a job.
--
-- Run in the Supabase SQL editor. Idempotent — safe to re-run.

-- ── 1. The column ──────────────────────────────────────────────────────
-- Nullable first so the backfill can fill existing rows; the default
-- covers every row created from here on.

alter table jobs
    add column if not exists job_id uuid default gen_random_uuid();

-- ── 2. Backfill ────────────────────────────────────────────────────────
-- `default` only applies to new rows, so rows written before this
-- migration would sit with a NULL id forever.

update jobs set job_id = gen_random_uuid() where job_id is null;

-- ── 3. Constraints ─────────────────────────────────────────────────────
-- Unique so it can be referenced, and NOT NULL so "the job with no id"
-- can never be a case anything has to handle.

create unique index if not exists idx_jobs_job_id on jobs (job_id);

alter table jobs alter column job_id set not null;

update meta set value = '7' where key = 'schema_version';
insert into meta (key, value) select 'schema_version', '7'
where not exists (select 1 from meta where key = 'schema_version');

-- ── Verify ─────────────────────────────────────────────────────────────

select count(*) as jobs,
       count(job_id) as with_id,
       count(distinct job_id) as distinct_ids
from jobs;
