-- Additive only: existing entries stay unclassified; existing RLS is unchanged.
ALTER TABLE IF EXISTS public.crm_job_log_entries
  ADD COLUMN IF NOT EXISTS work_party text NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS subcontractor text NOT NULL DEFAULT '';
