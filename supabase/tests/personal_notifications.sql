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
set local role authenticated;
do $$
declare f record; r jsonb; handle text; notice_id text;
begin
  select * into f from notification_fixture;
  perform set_config('request.jwt.claim.sub',f.actor::text,true);
  r:=public.oneloss_notifications('members',jsonb_build_object('card_id',f.card));
  if not (r->>'ok')::boolean then raise exception 'members failed'; end if;
  select x->>'username' into handle from jsonb_array_elements(r->'people') x where x->>'id'=f.recipient::text;
  if handle is null then raise exception 'recipient missing'; end if;
  perform public.oneloss_notifications('set_member',jsonb_build_object('card_id',f.card,'user_id',f.recipient,'member',true));
  perform public.oneloss_notifications('set_member',jsonb_build_object('card_id',f.card,'user_id',f.recipient,'member',true));
  perform public.oneloss_notifications('emit',jsonb_build_object('card_id',f.card,'actor_id',f.actor,'event_key','fixture-comment-1','body','Hi @'||handle||' review this'));
  perform public.oneloss_notifications('emit',jsonb_build_object('card_id',f.card,'actor_id',f.actor,'event_key','fixture-comment-1','body','Hi @'||handle||' review this'));
  begin
    perform public.oneloss_notifications('set_member',jsonb_build_object('card_id',f.card,'user_id',f.outsider,'member',true));
    raise exception 'unauthorized member accepted';
  exception when insufficient_privilege then null; end;
  begin
    perform public.oneloss_notifications('emit',jsonb_build_object('card_id',f.card,'actor_id',f.recipient,'event_key','fixture-spoof','body','spoof'));
    raise exception 'spoofed actor accepted';
  exception when insufficient_privilege then null; end;
  begin
    perform 1 from oneloss_notifications.inbox;
    raise exception 'private table readable';
  exception when insufficient_privilege then null; end;
  perform set_config('request.jwt.claim.sub',f.recipient::text,true);
  r:=public.oneloss_notifications('inbox');
  if jsonb_array_length(r->'items')<>2 then raise exception 'expected assignment + single mention: %',r; end if;
  r:=public.oneloss_notifications('inbox','{"filter":"mentions"}');
  if jsonb_array_length(r->'items')<>1 then raise exception 'mention filter failed'; end if;
  notice_id:=r->'items'->0->>'id';
  perform public.oneloss_notifications('read',jsonb_build_object('id',notice_id,'read',true));
  r:=public.oneloss_notifications('inbox','{"filter":"mentions","unread":true}');
  if jsonb_array_length(r->'items')<>0 then raise exception 'read failed'; end if;
  perform public.oneloss_notifications('read',jsonb_build_object('id',notice_id,'read',false));
  perform public.oneloss_notifications('mute',jsonb_build_object('card_id',f.card,'muted',true));
  perform set_config('request.jwt.claim.sub',f.actor::text,true);
  r:=public.oneloss_notifications('read',jsonb_build_object('id',notice_id,'read',true));
  if (r->>'ok')::boolean then raise exception 'could mark someone else read'; end if;
  perform public.oneloss_notifications('emit',jsonb_build_object('card_id',f.card,'actor_id',f.actor,'event_key','fixture-comment-muted','body','Hi @'||handle));
  r:=public.oneloss_notifications('inbox');
  if jsonb_array_length(r->'items')<>0 then raise exception 'self notified'; end if;
  perform set_config('request.jwt.claim.sub',f.recipient::text,true);
  r:=public.oneloss_notifications('inbox');
  if jsonb_array_length(r->'items')<>2 then raise exception 'mute failed'; end if;
  perform set_config('request.jwt.claim.sub',f.outsider::text,true);
  r:=public.oneloss_notifications('inbox');
  if jsonb_array_length(r->'items')<>0 then raise exception 'outsider saw inbox'; end if;
  begin
    perform public.oneloss_notifications('members',jsonb_build_object('card_id',f.card));
    raise exception 'outsider saw directory';
  exception when insufficient_privilege then null; end;
end;
$$;
reset role;
delete from public.app_user_departments where user_id=(select recipient from notification_fixture);
set local role authenticated;
do $$ declare r jsonb; begin
  perform set_config('request.jwt.claim.sub',(select recipient::text from notification_fixture),true);
  r:=public.oneloss_notifications('inbox');
  if jsonb_array_length(r->'items')<>0 then raise exception 'revoked user still sees job'; end if;
end $$;
reset role;
select 'PASS: membership, mentions, deduplication, mute, read ownership, access revocation and private table protection' as result;
rollback;
