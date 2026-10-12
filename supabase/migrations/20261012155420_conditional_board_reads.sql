-- Additive API: old clients/card readers are unchanged. Every call uses the
-- caller's RLS permissions, even when its content version matches.
begin;
create function public.hub_trello_boards(
  p_department text, p_workspace text, p_board_ids text[],
  p_versions jsonb default '{}'::jsonb
) returns jsonb language sql stable security invoker set search_path = '' as $$
  with selected as materialized (
    select s.board_id, s.board_json, s.lists_json, s.last_metadata_at,
      s.last_error_code,
      coalesce((select jsonb_agg(c.payload order by c.card_id)
        from public.hub_trello_mirror_cards c
        where c.board_id=s.board_id and c.present), '[]'::jsonb) as cards
    from public.hub_trello_sync_sources s
    where s.reader_department=p_department and s.reader_workspace=p_workspace
      and s.enabled and s.board_id=any(p_board_ids)
  ), versioned as (
    select *, md5(jsonb_build_array(board_json,lists_json,cards)::text) as version
    from selected
  )
  select jsonb_build_object('source','server_mirror','server_time',now(),
    'boards',coalesce(jsonb_agg(
      jsonb_build_object('board',board_json,'lists',lists_json,
        'version',version,'saved_at',last_metadata_at,
        'safe_after',last_metadata_at-interval '3 minutes',
        'ready',last_metadata_at>now()-interval '6 minutes' and last_error_code is null)
      || case when p_versions->>board_id=version
        then jsonb_build_object('unchanged',true)
        else jsonb_build_object('cards',cards) end
      order by board_id), '[]'::jsonb)) from versioned;
$$;
revoke all on function public.hub_trello_boards(text,text,text[],jsonb) from public, anon;
grant execute on function public.hub_trello_boards(text,text,text[],jsonb) to authenticated;
commit;
