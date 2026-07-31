-- Linguar Hub — schema v5: per-child job settings.
--
-- A unit or a claim carries its OWN claim number, date of loss and cause.
-- Six units on one property are rarely one claim, and on live data none of
-- the 139 children has a Trello card of its own — so the Hub is the only
-- place that record can live.
--
-- `jobs.metadata_json` already existed and was unused (0 of 415 rows), so
-- client-level settings need no new column: the four fields with real
-- columns (carrier, claim_number, loss_type, date_received) use them, and
-- everything else — adjuster, deductible, links, the sync baseline — is
-- JSON alongside.
--
-- Run once in the Supabase SQL editor. Idempotent — safe to re-run.

alter table job_children
    add column if not exists metadata_json text;

update meta set value = '5' where key = 'schema_version';
insert into meta (key, value) values ('schema_version', '5')
    on conflict (key) do update set value = excluded.value;

-- ── Verify ─────────────────────────────────────────────────────────────

select column_name, data_type
from information_schema.columns
where table_name = 'job_children'
order by ordinal_position;
