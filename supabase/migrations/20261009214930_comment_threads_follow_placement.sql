-- Identity stays card_id. Placement ownership survives moves and archives.
create function private.comment_card_access(p_card text) returns boolean
language sql stable security definer set search_path='' as $$
 select auth.uid() is not null and case
 when exists(select 1 from public.app_card_placements where card_id=p_card) then
 exists(select 1 from public.app_card_placements p join public.app_job_boards b using(board_id)
  where p.card_id=p_card and p.state in('active','archived') and b.enabled
  and p.workspace=b.workspace and cardinality(p.required_departments)>0
  and cardinality(b.required_departments)>0
  and p.required_departments <@ array(select public.my_departments())
  and b.required_departments <@ array(select public.my_departments()))
 else exists(select 1 from public.hub_trello_mirror_cards c
  join public.hub_trello_sync_sources s using(board_id)
  where c.card_id=p_card and c.present and s.enabled and s.reader_workspace is not null
  and s.reader_department=any(s.required_departments) and cardinality(s.required_departments)>0
  and s.required_departments <@ array(select public.my_departments())) end
$$;
revoke all on function private.comment_card_access(text) from public,anon,authenticated;
grant execute on function private.comment_card_access(text) to authenticated;
alter policy comment_threads_read on public.job_comment_threads
 using(private.comment_card_access(card_id));

-- Preserve the deployed delivery/idempotency implementation; replace only
-- the two verified active-snapshot assumptions. Abort on unexpected drift.
do $migration$
declare definition text; old_guard text := $guard$if who is null or not exists(select 1 from public.hub_trello_mirror_cards c
  join public.hub_trello_sync_sources s using(board_id) where c.card_id=p_card and c.present
  and s.enabled and s.reader_workspace is not null and s.reader_department=any(s.required_departments)
  and cardinality(s.required_departments)>0 and s.required_departments<@allowed) then$guard$;
 old_parent text := 'where c.card_id=p_card and c.present and item->>''id''=k';
begin
 definition:=pg_get_functiondef('private.job_comment_threads(text,text,jsonb)'::regprocedure);
 if strpos(definition,old_guard)=0 or strpos(definition,old_parent)=0 then
  raise exception 'Thread function changed; review migration before applying';
 end if;
 definition:=replace(definition,old_guard,'if not private.comment_card_access(p_card) then');
 definition:=replace(definition,old_parent,'where c.card_id=p_card and item->>''id''=k');
 execute definition;
end $migration$;
