-- Add position to the existing app-owned placement and its durable sync state.
alter table public.app_card_placements add column position double precision;
alter table public.app_card_placements add constraint app_position_finite
check (position is null or (position > 0 and position < 'Infinity'::double precision));
grant update(position) on public.app_card_placements to authenticated;

create function public.app_placement_position_guard() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  if new.position is distinct from old.position then
    if auth.uid() is null then raise exception 'Sign in required'; end if;
    if old.state <> 'active' or new.state <> 'active' then
      raise exception 'Restore the card before reordering'; end if;
    if old.lease_until > now() then
      raise exception 'Trello sync is finishing. Try again shortly'; end if;
    new.version := old.version + 1;
    new.updated_at := now(); new.sync_error := null;
    new.lease_token := null; new.lease_until := null;
    new.events := new.events || jsonb_build_array(jsonb_build_object(
      'actor',auth.uid(),'at',now(),'from_position',old.position,
      'position',new.position,'version',new.version));
  end if;
  return new;
end $$;
create trigger app_placement_position_guard before update of position
on public.app_card_placements for each row execute function public.app_placement_position_guard();
revoke all on function public.app_placement_position_guard() from public,anon,authenticated;

create function public.app_placement_drop(p_card text,p_version integer,
 p_board text,p_list text,p_position double precision) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare r public.app_card_placements;
begin
  if p_position is null or not (p_position > 0 and p_position < 'Infinity'::double precision) then
    raise exception 'Invalid card position'; end if;
  -- Existing RPC owns authentication, RLS, revision and destination checks.
  -- Both updates commit together; failure rolls back the lane move too.
  perform public.app_placement_change(p_card,'move',p_version,p_board,p_list);
  update public.app_card_placements set position=p_position
    where card_id=p_card returning * into r;
  if r.card_id is null then raise exception 'Placement is not accessible'; end if;
  return to_jsonb(r);
end $$;
revoke all on function public.app_placement_drop(text,integer,text,text,double precision) from public,anon;
grant execute on function public.app_placement_drop(text,integer,text,text,double precision) to authenticated;
