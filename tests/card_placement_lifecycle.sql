-- Transactional fixtures: never touch real cards; always rolled back.
begin;
insert into public.app_job_boards(board_id,name,workspace,department,required_departments,lists)
values ('placement-test-a','Test A','test','IE',array['IE','OC'],'[{"id":"test-a","name":"Active"}]'),
       ('placement-test-b','Test B','test','IE',array['IE','OC'],'[{"id":"test-b","name":"Estimating"}]');
update public.app_job_boards set workspace=(select reader_workspace from public.hub_trello_sync_sources
 where label='WORK IN PROGRESS' limit 1) where board_id='placement-test-b';
-- Use an existing source board to satisfy mirror FK; fake cards are rollback-only.
insert into public.hub_trello_mirror_cards(board_id,card_id,payload,revision,present,last_seen_at)
select board_id,'ffffffffffffffffffffff01',jsonb_build_object('name','Placement TEST','idList',(select x->>'id' from jsonb_array_elements(lists_json) x where coalesce((x->>'closed')::boolean,false)=false limit 1)),
       'test',true,now() from public.hub_trello_sync_sources where label='WORK IN PROGRESS' limit 1;
insert into public.hub_trello_mirror_cards(board_id,card_id,payload,revision,present,last_seen_at)
select board_id,'ffffffffffffffffffffff02',payload,'test',true,now()
from public.hub_trello_mirror_cards where card_id='ffffffffffffffffffffff01';
select set_config('request.jwt.claim.sub', (select user_id::text from public.app_admins limit 1), true);
set local role authenticated;
do $$
declare r jsonb; denied boolean:=false;
begin
  r:=public.app_placement_change('ffffffffffffffffffffff02','move',0,'placement-test-b','test-b');
  if r->>'board_id'<>'placement-test-b' then raise exception 'FAIL: cross-board move'; end if;
  begin
    perform public.app_placement_change('ffffffffffffffffffffff01','delete',0);
  exception when others then denied:=true; end;
  if not denied then raise exception 'FAIL: active delete allowed'; end if;
  r:=public.app_placement_change('ffffffffffffffffffffff01','archive',0);
  if r->>'state'<>'archived' or (r->>'version')::int<>1 then raise exception 'FAIL: archive'; end if;
  denied:=false;
  begin perform public.app_placement_change('ffffffffffffffffffffff01','restore',0,'placement-test-b','test-b');
  exception when others then denied:=true; end;
  if not denied then raise exception 'FAIL: stale version'; end if;
  -- The test catalog needs the same workspace as the source; checked below separately.
  denied:=false;
  begin perform public.app_placement_change('ffffffffffffffffffffff01','restore',1,'placement-test-a','test-a');
  exception when others then denied:=true; end;
  if not denied then raise exception 'FAIL: cross-workspace restore'; end if;
  r:=public.app_placement_change('ffffffffffffffffffffff01','restore',1);
  if r->>'state'<>'active' then raise exception 'FAIL: restore'; end if;
  r:=public.app_placement_claim('ffffffffffffffffffffff01',2,'00000000-0000-0000-0000-000000000001');
  if r is null then raise exception 'FAIL: no sync claim'; end if;
  if public.app_placement_claim('ffffffffffffffffffffff01',2,'00000000-0000-0000-0000-000000000002') is not null then
    raise exception 'FAIL: duplicate worker claim'; end if;
  denied:=false;
  begin perform public.app_placement_change('ffffffffffffffffffffff01','archive',2);
  exception when others then denied:=true; end;
  if not denied then raise exception 'FAIL: mutation raced an active sync'; end if;
  if public.app_placement_ack('ffffffffffffffffffffff01',2,'00000000-0000-0000-0000-000000000002') then
    raise exception 'FAIL: wrong worker acknowledgement'; end if;
  perform public.app_placement_ack('ffffffffffffffffffffff01',2,'00000000-0000-0000-0000-000000000001');
  r:=public.app_placement_change('ffffffffffffffffffffff01','archive',2);
end $$;
reset role;
select set_config('request.jwt.claim.sub',(select d.user_id::text from public.app_user_departments d
 where not exists(select 1 from public.app_admins a where a.user_id=d.user_id)
 group by d.user_id having array_agg(d.department) @> array['IE','OC'] limit 1),true);
set local role authenticated;
do $$ declare denied boolean:=false; begin
  begin perform public.app_placement_change('ffffffffffffffffffffff01','delete',3);
  exception when others then denied:=true; end;
  if not denied then raise exception 'FAIL: non-admin delete'; end if;
end $$;
reset role;
select set_config('request.jwt.claim.sub',(select user_id::text from public.app_admins limit 1),true);
set local role authenticated;
do $$ declare r jsonb; denied boolean:=false; begin
  r:=public.app_placement_change('ffffffffffffffffffffff01','delete',3);
  if r->>'state'<>'deleted' then raise exception 'FAIL: archived delete'; end if;
  begin perform public.app_placement_change('ffffffffffffffffffffff01','restore',4);
  exception when others then denied:=true; end;
  if not denied then raise exception 'FAIL: resurrected deletion'; end if;
  if not exists(select 1 from public.app_card_placements where card_id='ffffffffffffffffffffff02' and state='active') then
    raise exception 'FAIL: other placement was removed'; end if;
end $$;
reset role;
select set_config('request.jwt.claim.sub',(select user_id::text from public.app_user_departments
 group by user_id having array_agg(department)=array['IE'] limit 1),true);
set local role authenticated;
do $$ declare denied boolean:=false; begin
  if exists(select 1 from public.app_card_placements where card_id='ffffffffffffffffffffff01') then
    raise exception 'FAIL: wrong workplace read'; end if;
  begin perform public.app_placement_change('ffffffffffffffffffffff01','archive',4);
  exception when others then denied:=true; end;
  if not denied then raise exception 'FAIL: wrong workplace write'; end if;
end $$;
reset role;
rollback;
