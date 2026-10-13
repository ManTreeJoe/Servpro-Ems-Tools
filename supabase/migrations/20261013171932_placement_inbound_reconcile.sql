-- A completed OneLoss move must not pin the card forever. Adopt subsequent
-- complete provider snapshots, never a read started before acknowledgement.
alter table public.app_card_placements add column confirmed_at timestamptz default clock_timestamp();

create function public.app_placement_confirmation_clock() returns trigger
language plpgsql security invoker set search_path='' as $$
begin
  if new.synced_version < new.version then
    new.confirmed_at := null;
  elsif new.synced_version is distinct from old.synced_version then
    new.confirmed_at := clock_timestamp();
  else
    new.confirmed_at := old.confirmed_at;
  end if;
  return new;
end $$;
revoke all on function public.app_placement_confirmation_clock() from public,anon,authenticated;
create trigger zz_app_placement_confirmation_clock before update on public.app_card_placements
for each row execute function public.app_placement_confirmation_clock();

-- Only a nested write by the trusted server importer may supply its own
-- version/history. Ordinary authenticated edits retain ALL existing guards.
-- Preserve deployed guard bodies (including any independently shipped fixes).
do $$
declare fn text; body text;
begin
  foreach fn in array array['app_placement_guard','app_placement_position_guard'] loop
    body := pg_get_functiondef(('public.'||fn||'()')::regprocedure);
    if position(E'begin\n' in body)=0 then raise exception 'Unknown placement guard format'; end if;
    body := overlay(body placing E'begin\n  if current_user = ''service_role'' and pg_trigger_depth() > 1 then return new; end if;\n'
                    from position(E'begin\n' in body) for length(E'begin\n'));
    execute body;
  end loop;
end $$;

create function public.app_placement_accept_mirror() returns trigger
language plpgsql security invoker set search_path='' as $$
declare p public.app_card_placements; b public.app_job_boards;
        started timestamptz; rank double precision;
begin
  if current_user <> 'service_role' or not new.present
     or coalesce((new.payload->>'closed')::boolean,false) then return new; end if;
  select * into p from public.app_card_placements where card_id=new.card_id for update;
  if not found or p.state <> 'active' or p.version <> p.synced_version
     or p.confirmed_at is null or p.lease_until > clock_timestamp() then return new; end if;
  select last_started_at into started from public.hub_trello_sync_control where singleton;
  if started is null or started <= p.confirmed_at or new.last_seen_at <= p.confirmed_at then return new; end if;
  if exists(select 1 from public.hub_trello_mirror_cards m
            where m.card_id=new.card_id and m.board_id<>new.board_id and m.present) then return new; end if;
  select * into b from public.app_job_boards where board_id=new.board_id and enabled;
  if not found or b.workspace<>p.workspace or not exists(
    select 1 from jsonb_array_elements(b.lists) l where l->>'id'=new.payload->>'idList'
    and not coalesce((l->>'closed')::boolean,false)) then return new; end if;
  if jsonb_typeof(new.payload->'pos') <> 'number' then return new; end if;
  rank := (new.payload->>'pos')::double precision;
  if rank is null or not (rank>0 and rank<'Infinity'::double precision) then return new; end if;
  if (p.board_id,p.list_id,p.position) is not distinct from
     (new.board_id,new.payload->>'idList',rank) then return new; end if;
  update public.app_card_placements set
    board_id=new.board_id,list_id=new.payload->>'idList',position=rank,
    title=coalesce(new.payload->>'name',p.title),card_json=new.payload,
    required_departments=array(select distinct unnest(p.required_departments||b.required_departments)),
    version=p.version+1,synced_version=p.version+1,updated_at=clock_timestamp(),sync_error=null,
    lease_token=null,lease_until=null,
    events=p.events||jsonb_build_array(jsonb_build_object(
      'source','trello','actor',null,'at',clock_timestamp(),
      'from_board',p.board_id,'from_list',p.list_id,'from_position',p.position,
      'board',new.board_id,'list',new.payload->>'idList','position',rank,
      'state','active','version',p.version+1))
    where card_id=p.card_id;
  return new;
end $$;
revoke all on function public.app_placement_accept_mirror() from public,anon,authenticated;
create trigger app_placement_accept_mirror after insert or update of payload,last_seen_at,present
on public.hub_trello_mirror_cards for each row execute function public.app_placement_accept_mirror();
