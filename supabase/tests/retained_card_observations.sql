-- All fixtures are rolled back. No customer rows are touched.
begin;
set local role service_role;
do $$
declare bid text := encode(gen_random_bytes(12),'hex');
        cid text := encode(gen_random_bytes(12),'hex'); n bigint;
begin
  insert into public.hub_trello_sync_sources(board_id,label)
    values(bid,'Retention transaction test');
  insert into public.hub_trello_mirror_cards(board_id,card_id,payload,revision)
    values(bid,cid,jsonb_build_object('id',cid,'idList','first'),'one');
  update public.hub_trello_mirror_cards set last_seen_at=clock_timestamp()
    where board_id=bid and card_id=cid;
  select count(*) into n from public.hub_card_observations where card_id=cid;
  if n<>1 then raise exception 'unchanged observation duplicated'; end if;
  update public.hub_trello_mirror_cards set payload=payload||'{"idList":"second"}'::jsonb
    where board_id=bid and card_id=cid;
  update public.hub_trello_mirror_cards set details_json='{"checklists":[{"name":"Saved details"}]}'
    where board_id=bid and card_id=cid;
  update public.hub_trello_mirror_cards set present=false
    where board_id=bid and card_id=cid;
  delete from public.hub_trello_mirror_cards where board_id=bid and card_id=cid;
  select count(*) into n from public.hub_card_observations where card_id=cid;
  if n<>5 then raise exception 'detail/movement/removal history not retained: %',n; end if;
  if not exists(select 1 from public.hub_card_observations where card_id=cid
    and before_data#>>'{card,idList}'='first' and after_data#>>'{card,idList}'='second')
    then raise exception 'before and after missing'; end if;
  if has_table_privilege('authenticated','public.hub_card_observations','SELECT')
     or has_table_privilege('anon','public.hub_card_observations','SELECT')
     or has_table_privilege('service_role','public.hub_card_observations','DELETE')
     then raise exception 'history permissions too broad'; end if;
end $$;
reset role;
rollback;
