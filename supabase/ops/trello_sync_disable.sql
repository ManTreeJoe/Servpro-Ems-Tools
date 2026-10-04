-- Stop the new mirror without disabling the existing desktop Trello adapter.
-- Retain imported data and checkpoints for recovery; this deletes no job data.
begin;
update public.hub_trello_sync_control set enabled=false where singleton;
select cron.unschedule(jobid) from cron.job where jobname='linguar-trello-sync-v1';
commit;
