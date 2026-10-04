-- A cron invocation arrives seconds after its minute boundary. Scheduling the
-- next poll relative to that arrival caused the next two-minute tick to skip.
create or replace function public.hub_trello_finish_source(p_lease uuid, p_board_id text, p_ok boolean)
returns void language plpgsql security invoker set search_path = '' as $$
begin
  perform public.hub_trello_assert_lease(p_lease);
  update public.hub_trello_sync_sources
     set last_attempt_at = clock_timestamp(),
         consecutive_failures = case when p_ok then 0 else least(consecutive_failures+1,10) end,
         last_error_code = case when p_ok then null else coalesce(last_error_code,'sync_failed') end,
         next_poll_at = case when p_ok then
           (select date_trunc('minute',last_started_at) + interval '120 seconds'
              from public.hub_trello_sync_control where singleton)
           else clock_timestamp() + make_interval(secs => least(1800,120 * (2^least(consecutive_failures+1,4))::integer)) end
   where board_id = p_board_id;
end;
$$;
