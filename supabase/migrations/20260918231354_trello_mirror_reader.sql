-- Read-only bridge. Mixed-location boards require EVERY listed membership.
-- Empty/unconfigured scope denies access; the desktop cannot configure it.
begin;
alter table public.hub_trello_sync_sources
  add column reader_department text,
  add column reader_workspace text,
  add column required_departments text[] not null default '{}';

create policy mirror_source_read on public.hub_trello_sync_sources
for select to authenticated using (
  enabled and reader_department is not null and reader_workspace is not null
  and cardinality(required_departments) > 0
  and reader_department = any(required_departments)
  and required_departments <@ array(select public.my_departments())
);
create policy mirror_card_read on public.hub_trello_mirror_cards
for select to authenticated using (present and exists (
  select 1 from public.hub_trello_sync_sources s
  where s.board_id = hub_trello_mirror_cards.board_id
));
grant select (board_id, enabled, reader_department, reader_workspace, required_departments,
  board_json, lists_json, last_metadata_at, last_error_code)
  on public.hub_trello_sync_sources to authenticated;
grant select (board_id, card_id, present, payload, revision, details_json,
  details_revision, details_checked_at, comments_json, comments_revision,
  comments_completed_at, comment_error_code)
  on public.hub_trello_mirror_cards to authenticated;

create function public.hub_trello_read(p_department text, p_workspace text, p_card_id text default null)
returns jsonb language sql stable security invoker set search_path = '' as $$
  select case when p_card_id is null then
    jsonb_build_object('source','server_mirror','server_time',now(),'boards',coalesce((
      select jsonb_agg(jsonb_build_object(
        'board',s.board_json,'lists',s.lists_json,'saved_at',s.last_metadata_at,
        'safe_after',s.last_metadata_at - interval '3 minutes',
        'ready',s.last_metadata_at > now()-interval '6 minutes' and s.last_error_code is null,
        'cards',coalesce((select jsonb_agg(c.payload order by c.card_id)
          from public.hub_trello_mirror_cards c where c.board_id=s.board_id and c.present),'[]'::jsonb)
      ) order by s.board_id) from public.hub_trello_sync_sources s
      where s.reader_department=p_department and s.reader_workspace=p_workspace
    ),'[]'::jsonb))
  else coalesce((select jsonb_build_object(
      'source','server_mirror','server_time',now(),
      'ready',s.last_metadata_at > now()-interval '6 minutes' and s.last_error_code is null
        and c.details_revision=c.revision and c.comments_revision=c.revision
        and c.comment_error_code is null,
      'safe_after',least(s.last_metadata_at,c.details_checked_at,c.comments_completed_at)-interval '3 minutes',
      'saved_at',s.last_metadata_at,
      'card',coalesce(c.details_json,'{}'::jsonb)||c.payload||jsonb_build_object('actions',c.comments_json)
    ) from public.hub_trello_mirror_cards c
    join public.hub_trello_sync_sources s using(board_id)
    where c.card_id=p_card_id and c.present and s.reader_department=p_department
      and s.reader_workspace=p_workspace limit 1),
    jsonb_build_object('source','server_mirror','ready',false)) end
$$;
revoke all on function public.hub_trello_read(text,text,text) from public, anon;
grant execute on function public.hub_trello_read(text,text,text) to authenticated;
commit;
