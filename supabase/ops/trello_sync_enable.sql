-- Run only AFTER the function, migration, verified account and board allowlist
-- are configured. Never place credentials in this file or the cron command.
begin;
do $$
begin
  if (select count(*) from vault.secrets where name in
      ('linguar_trello_sync_cron_secret','linguar_trello_sync_project_url')) <> 2 then
    raise exception 'Trello sync Vault configuration is missing';
  end if;
  if not exists(select 1 from public.hub_trello_sync_sources where enabled) then
    raise exception 'No explicitly enabled Trello boards';
  end if;
end;
$$;
select cron.schedule('linguar-trello-sync-v1', '*/2 * * * *', $job$
  select net.http_post(
    url := (select decrypted_secret from vault.decrypted_secrets where name='linguar_trello_sync_project_url') || '/functions/v1/trello-sync',
    headers := jsonb_build_object('Content-Type','application/json','Authorization',
      'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name='linguar_trello_sync_cron_secret')),
    body := '{}'::jsonb, timeout_milliseconds := 110000
  ) where (select enabled from public.hub_trello_sync_control where singleton);
$job$);
update public.hub_trello_sync_control set enabled=true where singleton;
commit;
