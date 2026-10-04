-- Board-wide nested checklists fail on large boards (Trello: "Too many checklists").
-- Filename matches the applied migration version in the linked project.
-- Keep board metadata fast; checkpoint full details per changed card instead.
begin;
alter table public.hub_trello_mirror_cards
  add column details_json jsonb,
  add column details_revision text,
  add column details_checked_at timestamptz;

create function public.hub_trello_card_detail(
  p_lease uuid, p_board_id text, p_card_id text, p_revision text, p_detail jsonb
) returns boolean language plpgsql security invoker set search_path = '' as $$
declare c public.hub_trello_mirror_cards%rowtype;
begin
  perform public.hub_trello_assert_lease(p_lease);
  select * into c from public.hub_trello_mirror_cards
   where board_id = p_board_id and card_id = p_card_id and present for update;
  if not found or c.revision <> p_revision then return false; end if;
  if p_detail is null or jsonb_typeof(p_detail) <> 'object'
    or p_detail->>'id' is distinct from p_card_id then
    raise exception 'invalid_card_detail';
  end if;
  if p_detail->>'idBoard' is distinct from p_board_id
    or p_detail->>'dateLastActivity' is distinct from c.payload->>'dateLastActivity' then
    -- Card changed or moved after the board fetch. Retry against the next snapshot.
    return false;
  end if;
  update public.hub_trello_mirror_cards set details_json = p_detail,
    details_revision = p_revision, details_checked_at = clock_timestamp()
   where board_id = p_board_id and card_id = p_card_id;
  return true;
end;
$$;
revoke all on function public.hub_trello_card_detail(uuid,text,text,text,jsonb) from public, anon, authenticated;
grant execute on function public.hub_trello_card_detail(uuid,text,text,text,jsonb) to service_role;

create or replace function public.hub_trello_comment_work(p_lease uuid, p_board_id text, p_limit integer default 20)
returns table(card_id text, revision text, before_cursor text)
language plpgsql security invoker set search_path = '' as $$
begin
  perform public.hub_trello_assert_lease(p_lease);
  return query
    select c.card_id, c.revision,
           case when c.scan_revision = c.revision then c.scan_before else null end
      from public.hub_trello_mirror_cards c
      join public.hub_trello_sync_sources s using(board_id)
     where c.board_id = p_board_id and s.enabled and c.present
       and (c.comments_revision is distinct from c.revision
         or c.details_revision is distinct from c.revision
         or c.comments_completed_at < clock_timestamp() - interval '1 day'
         or c.scan_revision is not null)
     order by c.comment_attempt_at nulls first, c.card_id
     limit greatest(1, least(coalesce(p_limit,20),100));
end;
$$;
commit;
