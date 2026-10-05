begin;
alter table public.schedule_visits add column confirmed_revision bigint not null default 0;
alter table public.schedule_visits add column confirmed_at timestamptz;
alter table public.schedule_visits add constraint schedule_confirmation_revision
 check(confirmed_revision>=0 and confirmed_revision<=revision);

create table public.schedule_confirmations (
 operation_id uuid primary key,
 department text not null,
 run_date date not null,
 actor uuid not null references auth.users(id),
 confirmed_at timestamptz not null default now(),
 command jsonb not null,
 snapshot jsonb not null,
 result jsonb not null
);
create index schedule_confirmations_day on public.schedule_confirmations(department,run_date,confirmed_at desc);
create index schedule_confirmations_actor on public.schedule_confirmations(actor);
alter table public.schedule_confirmations enable row level security;
revoke all on public.schedule_confirmations from public,anon,authenticated;
grant select on public.schedule_confirmations to authenticated;
create policy schedule_confirmation_read on public.schedule_confirmations for select to authenticated
 using(department in(select public.my_departments()));

-- Definer is needed only to write immutable receipts/confirmation markers.
-- Explicit office, job, board, origin-board, link and placement checks precede
-- the existing invoker placement RPC (which runs with this function's owner).
create function private.confirm_schedule_day(c jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare who uuid:=auth.uid(); dept text:=c->>'department'; day_text text:=c->>'date';
 op uuid:=(c->>'operation_id')::uuid; item jsonb; v public.schedule_visits;
 receipt public.schedule_confirmations; b public.app_job_boards; origin public.app_job_boards;
 p public.app_card_placements; mirror public.hub_trello_mirror_cards;
 allowed text[]; current_board text; current_lane text; current_version int;
 moved int:=0; total int; snapshots jsonb:='[]'; result jsonb; placed jsonb;
begin
 if who is null or dept is null or not exists(select 1 from public.app_user_departments
  where user_id=who and department=dept) then raise exception 'Office access required' using errcode='42501'; end if;
 if c->'contract_version' is distinct from '1'::jsonb or op is null or
  day_text is null or day_text !~ '^\d{4}-\d{2}-\d{2}$' or day_text::date::text<>day_text or
  jsonb_typeof(c->'entries') is distinct from 'array' or
  jsonb_array_length(c->'entries') not between 1 and 500 or octet_length(c::text)>1000000 then
  raise exception 'Invalid day confirmation'; end if;
 perform pg_advisory_xact_lock(hashtextextended('schedule:'||dept,0));
 select * into receipt from public.schedule_confirmations where operation_id=op;
 if found then
  if receipt.actor<>who or receipt.command<>c then raise exception 'Operation ID reused'; end if;
  return receipt.result;
 end if;
 select array_agg(d) into allowed from public.my_departments() d;
 select count(*) into total from public.schedule_visits where department=dept
  and payload->>'status'='active' and payload->>'queue'='scheduled' and payload->>'date'=day_text;
 if total<>jsonb_array_length(c->'entries') or
  (select count(distinct x->>'id') from jsonb_array_elements(c->'entries') x)<>total then
  raise exception 'Day changed; review again' using errcode='40001'; end if;
 if (select count(*) from jsonb_array_elements(c->'entries') x where x->>'action'='move')<>
  (select count(distinct x->>'card_id') from jsonb_array_elements(c->'entries') x where x->>'action'='move') then
  raise exception 'A card cannot be moved twice in one day'; end if;
 -- Stable order also makes card locking deterministic.
 for item in select value from jsonb_array_elements(c->'entries') order by value->>'card_id',value->>'id' loop
  if item->>'action' is null or item->>'action' not in ('keep','move') then raise exception 'Choose keep or move for each visit'; end if;
  select * into v from public.schedule_visits where id=(item->>'id')::uuid for update;
  if not found or v.department<>dept or v.payload->>'status'<>'active' or
   v.payload->>'queue'<>'scheduled' or v.payload->>'date' is distinct from day_text or
   v.revision is distinct from (item->>'revision')::bigint then
   raise exception 'Day changed; review again' using errcode='40001'; end if;
  if v.job_id is not null and not exists(select 1 from public.jobs where job_id=v.job_id and department=dept) then
   raise exception 'Job unavailable in office' using errcode='42501'; end if;
  placed:=null;
  if item->>'action'='move' then
   -- Require exactly one canonical job for the selected saved link, not a title match.
   if v.job_id is null or not exists(select 1 from public.jobs j join public.job_links l using(canon_key)
    where j.job_id=v.job_id and j.department=dept and l.link_type='trello_card' and l.link_value=item->>'card_id') or
    (select count(distinct j.job_id) from public.jobs j join public.job_links l using(canon_key)
     where j.department=dept and l.link_type='trello_card' and l.link_value=item->>'card_id')<>1 then
    raise exception 'Card link needs review' using errcode='42501'; end if;
   select * into p from public.app_card_placements where card_id=item->>'card_id' for update;
   if found then
    select * into origin from public.app_job_boards where board_id=p.origin_board_id;
    if p.state<>'active' or origin.board_id is null or not origin.enabled or
     not coalesce(origin.required_departments<@allowed,false) or
     not coalesce(p.required_departments<@allowed,false) then
     raise exception 'Card unavailable' using errcode='42501'; end if;
    current_board:=p.board_id; current_lane:=p.list_id; current_version:=p.version;
   else
    select * into mirror from public.hub_trello_mirror_cards where card_id=item->>'card_id' and present for share;
    if not found or coalesce((mirror.payload->>'closed')::boolean,false) then
     raise exception 'Card unavailable' using errcode='42501'; end if;
    current_board:=mirror.board_id; current_lane:=mirror.payload->>'idList'; current_version:=0;
   end if;
   select * into b from public.app_job_boards where board_id=current_board for share;
   if b.board_id is null or not b.enabled or b.department<>dept or
    not coalesce(b.required_departments<@allowed,false) or
    upper(btrim(b.name)) not in ('WORK IN PROGRESS','CONTENTS') then
    raise exception 'Only accessible WIP or Contents cards can move here' using errcode='42501'; end if;
   if current_board is distinct from item->>'board_id' or current_lane is distinct from item->>'from_list' or
    current_version is distinct from (item->>'version')::int then
    raise exception 'Card changed; review again' using errcode='40001'; end if;
   if not exists(select 1 from jsonb_array_elements(b.lists) lane where lane->>'id'=item->>'list_id'
     and not coalesce((lane->>'closed')::boolean,false) and lane->>'name' !~* 'recon') or
    exists(select 1 from jsonb_array_elements(b.lists) lane where lane->>'id'=current_lane and lane->>'name' ~* 'recon') then
    raise exception 'Choose an active non-Recon lane'; end if;
   if current_lane<>item->>'list_id' then
    placed:=public.app_placement_change(item->>'card_id','move',current_version,current_board,item->>'list_id');
    -- Never duplicate provider descriptions/card_json into office-wide receipts.
    placed:=jsonb_build_object('card_id',placed->'card_id','board_id',placed->'board_id',
      'list_id',placed->'list_id','version',placed->'version');
    moved:=moved+1;
   end if;
  end if;
  snapshots:=snapshots||jsonb_build_array(jsonb_build_object('visit',to_jsonb(v),'review',item,'placement',placed));
  update public.schedule_visits set confirmed_revision=revision,confirmed_at=now() where id=v.id;
 end loop;
 result:=jsonb_build_object('operation_id',op,'date',day_text,'confirmed',total,'moved',moved,'confirmed_at',now());
 insert into public.schedule_confirmations(operation_id,department,run_date,actor,command,snapshot,result)
 values(op,dept,day_text::date,who,c,snapshots,result);
 return result;
end $$;
revoke all on function private.confirm_schedule_day(jsonb) from public,anon,authenticated;
grant execute on function private.confirm_schedule_day(jsonb) to authenticated;
create function public.confirm_schedule_day(p_command jsonb) returns jsonb
language sql security invoker set search_path='' as $$select private.confirm_schedule_day(p_command)$$;
revoke all on function public.confirm_schedule_day(jsonb) from public,anon,authenticated;
grant execute on function public.confirm_schedule_day(jsonb) to authenticated;
commit;
