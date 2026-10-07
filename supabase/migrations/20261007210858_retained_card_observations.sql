-- Observation retention only. observed_at is NEVER a verified move timestamp.
-- Filename matches the applied shared-backend migration version.
begin;
create table public.hub_card_observations (
  observation_id bigint generated always as identity primary key,
  board_id text not null,
  card_id text not null,
  observed_at timestamptz not null default clock_timestamp(),
  kind text not null check (kind in ('baseline','changed','source_removed')),
  reader_workspace text,
  required_departments text[] not null default '{}',
  before_data jsonb,
  after_data jsonb
);
create index hub_card_observations_card_idx
  on public.hub_card_observations(card_id, observed_at, observation_id);
create index hub_card_observations_board_idx
  on public.hub_card_observations(board_id, observed_at);
alter table public.hub_card_observations enable row level security;
revoke all on public.hub_card_observations from public, anon, authenticated, service_role;
grant select, insert on public.hub_card_observations to service_role;
grant usage, select on sequence public.hub_card_observations_observation_id_seq to service_role;

create function public.hub_retain_card_observation() returns trigger
language plpgsql security invoker set search_path='' as $$
declare prior jsonb; following jsonb; bid text; cid text;
begin
  if TG_OP <> 'INSERT' then
    prior := jsonb_build_object('card',old.payload,'details',old.details_json,
      'comments',old.comments_json,'present',old.present);
    bid := old.board_id; cid := old.card_id;
  end if;
  if TG_OP <> 'DELETE' then
    following := jsonb_build_object('card',new.payload,'details',new.details_json,
      'comments',new.comments_json,'present',new.present);
    bid := new.board_id; cid := new.card_id;
  end if;
  if TG_OP='UPDATE' and prior is not distinct from following then return new; end if;
  insert into public.hub_card_observations(board_id,card_id,kind,
      reader_workspace,required_departments,before_data,after_data)
    select bid,cid,case TG_OP when 'INSERT' then 'baseline'
      when 'DELETE' then 'source_removed' else 'changed' end,
      s.reader_workspace,s.required_departments,prior,following
    from public.hub_trello_sync_sources s where s.board_id=bid;
  if TG_OP='DELETE' then return old; end if;
  return new;
end;
$$;
revoke all on function public.hub_retain_card_observation() from public,anon,authenticated;
grant execute on function public.hub_retain_card_observation() to service_role;
create trigger hub_retain_card_observation
after insert or update or delete on public.hub_trello_mirror_cards
for each row execute function public.hub_retain_card_observation();

-- Preserve the existing saved baseline, including cards no longer present.
-- This starts retention; it does not backdate their arrival or imply completeness.
insert into public.hub_card_observations(board_id,card_id,kind,
    reader_workspace,required_departments,after_data)
select c.board_id,c.card_id,'baseline',s.reader_workspace,s.required_departments,
  jsonb_build_object('card',c.payload,'details',c.details_json,
                    'comments',c.comments_json,'present',c.present)
from public.hub_trello_mirror_cards c
join public.hub_trello_sync_sources s using(board_id);
commit;
