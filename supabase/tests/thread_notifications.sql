-- Transaction-only fixtures: creates no lasting users, jobs or notifications.
begin;
create temporary table notification_fixture as select gen_random_uuid() actor,gen_random_uuid() recipient,gen_random_uuid() outsider,
  'notification-test-'||gen_random_uuid()::text job, left(replace(gen_random_uuid()::text,'-',''),24) card;
grant select on notification_fixture to authenticated;
insert into auth.users(id,email,raw_user_meta_data)
select actor,actor::text||'@test.invalid','{"display_name":"Test Author"}'::jsonb from notification_fixture union all
select recipient,recipient::text||'@test.invalid','{"display_name":"Test Recipient"}' from notification_fixture union all
select outsider,outsider::text||'@test.invalid','{"display_name":"Test Outsider"}' from notification_fixture;
insert into public.app_user_departments(user_id,department)
select u.id,d from notification_fixture f cross join lateral (values(f.actor),(f.recipient)) u(id)
cross join lateral (select unnest(b.required_departments) d from public.app_job_boards b where b.board_id='5d8b8f4621038a7a93d6b27d' union select 'EMS') dep;
insert into public.jobs(canon_key,display_name,department) select job,'Notification transaction fixture','EMS' from notification_fixture;
insert into public.hub_trello_mirror_cards(board_id,card_id,payload,revision,present)
select '5d8b8f4621038a7a93d6b27d',card,jsonb_build_object('id',card,'shortLink',left(card,8)),'fixture',true from notification_fixture;
insert into public.job_links(canon_key,link_type,link_value) select job,'trello_card',card from notification_fixture;

alter table notification_fixture add column member_user uuid default gen_random_uuid();
insert into auth.users(id,email,raw_user_meta_data) select member_user,member_user::text||'@test.invalid','{}' from notification_fixture;
insert into public.app_user_departments(user_id,department)
select f.member_user,d.department from notification_fixture f join public.app_user_departments d on d.user_id=f.recipient;
insert into oneloss_notifications.members(canon_key,user_id,added_by) select job,member_user,actor from notification_fixture;
insert into public.job_comment_threads(card_id,id,root_id,body,actor,author_id,native)
select card,'thread-root','thread-root','Original','Original author',recipient,true from notification_fixture;
set local role authenticated;
do $$ declare f record; result jsonb; op uuid:=gen_random_uuid(); begin
 select * into f from notification_fixture;
 perform set_config('request.jwt.claim.sub',f.actor::text,true);
 result:=public.job_comment_threads('reply',f.card,jsonb_build_object('parent','thread-root','body','Clean reply','operation_id',op));
 perform public.job_comment_threads('reply',f.card,jsonb_build_object('parent','thread-root','body','Clean reply','operation_id',op));
 perform set_config('request.jwt.claim.sub',f.recipient::text,true);
 result:=public.oneloss_notifications('inbox');
 if jsonb_array_length(result->'items')<>1 then raise exception 'Thread participant did not receive exactly one alert'; end if;
 perform set_config('request.jwt.claim.sub',f.member_user::text,true);
 result:=public.oneloss_notifications('inbox');
 if jsonb_array_length(result->'items')<>1 then raise exception 'Card member did not receive exactly one alert'; end if;
 perform public.oneloss_notifications('mute',jsonb_build_object('card_id',f.card,'muted',true));
 perform set_config('request.jwt.claim.sub',f.actor::text,true);
 perform public.job_comment_threads('reply',f.card,jsonb_build_object('parent','thread-root','body','Second reply','operation_id',gen_random_uuid()));
 result:=public.oneloss_notifications('inbox');
 if jsonb_array_length(result->'items')<>0 then raise exception 'Sender notified'; end if;
 perform set_config('request.jwt.claim.sub',f.member_user::text,true);
 result:=public.oneloss_notifications('inbox');
 if jsonb_array_length(result->'items')<>1 then raise exception 'Muted user notified'; end if;
 perform set_config('request.jwt.claim.sub',f.outsider::text,true);
 result:=public.oneloss_notifications('inbox');
 if jsonb_array_length(result->'items')<>0 then raise exception 'Outsider notified'; end if;
end $$;
reset role;
-- Exercise the real placement RPC/guards, including its sync acknowledgement.
update public.hub_trello_mirror_cards c set payload=c.payload||jsonb_build_object(
 'name','Notification fixture','idList',(select x->>'id' from public.app_job_boards b,
 jsonb_array_elements(b.lists) x where b.board_id=c.board_id
 and coalesce((x->>'closed')::boolean,false)=false limit 1))
where c.card_id=(select card from notification_fixture);
set local role authenticated;
do $$ declare f record; result jsonb; lease uuid:=gen_random_uuid(); begin
 select * into f from notification_fixture;
 perform set_config('request.jwt.claim.sub',f.member_user::text,true);
 perform public.oneloss_notifications('mute',jsonb_build_object('card_id',f.card,'muted',false));
 perform set_config('request.jwt.claim.sub',f.actor::text,true);
 perform public.app_placement_change(f.card,'archive',0);
 perform public.app_placement_claim(f.card,1,lease);
 if not public.app_placement_ack(f.card,1,lease) then raise exception 'Fixture sync acknowledgement failed'; end if;
 perform set_config('request.jwt.claim.sub',f.member_user::text,true);
 result:=public.oneloss_notifications('inbox');
 if jsonb_array_length(result->'items')<>2 then raise exception 'Archive missing or sync acknowledgement duplicated alert'; end if;
 perform set_config('request.jwt.claim.sub',f.actor::text,true);
 perform public.app_placement_change(f.card,'restore',1);
 perform set_config('request.jwt.claim.sub',f.member_user::text,true);
 result:=public.oneloss_notifications('inbox');
 if jsonb_array_length(result->'items')<>3 then raise exception 'Restore did not notify member exactly once'; end if;
 perform set_config('request.jwt.claim.sub',f.recipient::text,true);
 result:=public.oneloss_notifications('inbox');
 if jsonb_array_length(result->'items')<>2 then raise exception 'Thread-only participant received unrelated placement alert'; end if;
end $$;
reset role;
select 'PASS: replies, members, retry dedup, mute/access exclusions, archive/restore and sync acknowledgement' result;
rollback;
