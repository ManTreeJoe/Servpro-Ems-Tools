-- Run within a transaction; fixture data must never be committed.
insert into public.app_job_boards(board_id,name,workspace,department,required_departments,lists)
select 'drop-position-test-board','Drop TEST',workspace,department,required_departments,
 '[{"id":"drop-test-lane","name":"Test"}]'::jsonb
from public.app_job_boards where name='WORK IN PROGRESS' limit 1;
insert into public.hub_trello_mirror_cards(board_id,card_id,payload,revision,present,last_seen_at)
select board_id,'ffffffffffffffffffffdd01',jsonb_build_object('name','Drop TEST',
 'idList',(select x->>'id' from jsonb_array_elements(lists_json) x where coalesce((x->>'closed')::boolean,false)=false limit 1),'pos',100),
 'test',true,now() from public.hub_trello_sync_sources where label='WORK IN PROGRESS' limit 1;
select set_config('request.jwt.claim.sub',(select user_id::text from public.app_admins limit 1),true);
set local role authenticated;
do $$ declare r jsonb; v integer; denied boolean:=false; begin
 r:=public.app_placement_drop('ffffffffffffffffffffdd01',0,'drop-position-test-board','drop-test-lane',150);
 if (r->>'position')::float8<>150 or r->>'list_id'<>'drop-test-lane' then raise exception 'FAIL cross-lane rank'; end if;
 v:=(r->>'version')::integer;
 r:=public.app_placement_drop('ffffffffffffffffffffdd01',v,'drop-position-test-board','drop-test-lane',50);
 if (r->>'position')::float8<>50 or (r->>'version')::integer<=v then raise exception 'FAIL same-lane revision'; end if;
 begin perform public.app_placement_drop('ffffffffffffffffffffdd01',v,'drop-position-test-board','drop-test-lane',200);
 exception when others then denied:=true; end;
 if not denied then raise exception 'FAIL stale version accepted'; end if;
 v:=(r->>'version')::integer; denied:=false;
 begin perform public.app_placement_drop('ffffffffffffffffffffdd01',v,'drop-position-test-board','drop-test-lane','NaN'::float8);
 exception when others then denied:=true; end;
 if not denied then raise exception 'FAIL NaN accepted'; end if;
 r:=public.app_placement_claim('ffffffffffffffffffffdd01',v,'00000000-0000-0000-0000-00000000dd01');
 if r is null or (r->>'position')::float8<>50 then raise exception 'FAIL sync position'; end if;
 denied:=false;
 begin perform public.app_placement_drop('ffffffffffffffffffffdd01',v,'drop-position-test-board','drop-test-lane',200);
 exception when others then denied:=true; end;
 if not denied then raise exception 'FAIL active lease reorder'; end if;
end $$;
reset role;
