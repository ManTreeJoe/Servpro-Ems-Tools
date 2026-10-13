-- Card membership is a projection of the existing mirror, not a new polling job.
-- Explicit local choices override Trello; legacy manual memberships remain intact.
begin;
create table oneloss_notifications.card_member_choices (
 card_id text not null check(card_id ~ '^[0-9a-f]{24}$'),
 user_id uuid not null references auth.users(id) on delete cascade,
 member boolean not null, changed_by uuid not null references auth.users(id),
 changed_at timestamptz not null default now(), primary key(card_id,user_id)
);
create index card_member_choices_user on oneloss_notifications.card_member_choices(user_id);
create index card_member_choices_actor on oneloss_notifications.card_member_choices(changed_by);
create table oneloss_notifications.card_preferences (
 card_id text not null, user_id uuid not null references auth.users(id) on delete cascade,
 muted boolean not null, primary key(card_id,user_id)
);
create index card_preferences_user on oneloss_notifications.card_preferences(user_id);
alter table oneloss_notifications.card_member_choices enable row level security;
alter table oneloss_notifications.card_preferences enable row level security;
revoke all on oneloss_notifications.card_member_choices,oneloss_notifications.card_preferences from public,anon,authenticated;
-- Old history keeps its job key. New, not-yet-indexed cards can also notify.
alter table oneloss_notifications.inbox alter column canon_key drop not null;

create function oneloss_notifications.card_snapshot(p_card text)
returns setof public.hub_trello_mirror_cards language sql stable set search_path='' as $$
 select c.* from public.hub_trello_mirror_cards c where c.card_id=p_card
 order by (c.board_id=(select p.board_id from public.app_card_placements p where p.card_id=p_card)) desc nulls last,
 c.present desc,c.last_seen_at desc,c.board_id limit 1
$$;
create function oneloss_notifications.card_job(p_card text) returns text
language sql stable set search_path='' as $$
 select case when count(distinct l.canon_key)=1 then min(l.canon_key) end
 from oneloss_notifications.card_snapshot(p_card) c join public.job_links l
 on l.link_value in(c.card_id,c.payload->>'shortLink')
 where l.link_type in('trello_card','trello_card_contents','trello_card_recon')
$$;
create function oneloss_notifications.card_access(p_user uuid,p_card text) returns boolean
language sql stable set search_path='' as $$
 select p_user is not null
 and exists(select 1 from auth.users u where u.id=p_user and u.deleted_at is null
  and (u.banned_until is null or u.banned_until<now()))
 and case when exists(select 1 from public.app_card_placements where card_id=p_card) then
 exists(select 1 from public.app_card_placements p join public.app_job_boards b using(board_id)
  where p.card_id=p_card and p.state in('active','archived') and b.enabled and p.workspace=b.workspace
  and cardinality(p.required_departments)>0 and cardinality(b.required_departments)>0
  and p.required_departments <@ array(select d.department from public.app_user_departments d where d.user_id=p_user)
  and b.required_departments <@ array(select d.department from public.app_user_departments d where d.user_id=p_user))
 else exists(select 1 from oneloss_notifications.card_snapshot(p_card) c
  join public.hub_trello_sync_sources s using(board_id)
  where c.present and s.enabled and s.reader_workspace is not null
  and cardinality(s.required_departments)>0 and s.reader_department=any(s.required_departments)
  and s.required_departments <@ array(select d.department from public.app_user_departments d where d.user_id=p_user)) end
 and not exists(select 1 from oneloss_notifications.card_snapshot(p_card) c
  join public.job_links l on l.link_value in(c.card_id,c.payload->>'shortLink')
  join public.jobs j using(canon_key)
  where l.link_type in('trello_card','trello_card_contents','trello_card_recon') and j.department is not null
  and not exists(select 1 from public.app_user_departments d where d.user_id=p_user and d.department=j.department))
$$;
create function oneloss_notifications.card_members(p_card text)
returns table(user_id uuid,source text) language sql stable set search_path='' as $$
 with inherited as (
  select m.user_id,'OneLoss'::text source from oneloss_notifications.members m
   where m.canon_key=oneloss_notifications.card_job(p_card)
  union all
  select a.user_id,'Trello' from oneloss_notifications.card_snapshot(p_card) c
   join oneloss_notifications.trello_accounts a on coalesce(c.payload->'idMembers','[]'::jsonb) ? a.trello_member_id
 ), candidates as (
  select i.user_id,string_agg(distinct i.source,' + ' order by i.source) source from inherited i
   where not exists(select 1 from oneloss_notifications.card_member_choices o where o.card_id=p_card and o.user_id=i.user_id)
   group by i.user_id
  union all
  select o.user_id,'OneLoss' from oneloss_notifications.card_member_choices o where o.card_id=p_card and o.member
 ) select c.user_id,c.source from candidates c where oneloss_notifications.card_access(c.user_id,p_card)
$$;
create function oneloss_notifications.card_muted(p_user uuid,p_card text) returns boolean
language sql stable set search_path='' as $$
 select coalesce((select muted from oneloss_notifications.card_preferences where user_id=p_user and card_id=p_card),
 (select muted from oneloss_notifications.preferences where user_id=p_user and canon_key=oneloss_notifications.card_job(p_card)),false)
$$;

create or replace function oneloss_notifications.deliver_activity(
 p_actor uuid,p_card text,p_event text,p_body text,p_root text default null
) returns void language plpgsql set search_path='' as $$
begin
 if not oneloss_notifications.card_access(p_actor,p_card) then return; end if;
 insert into oneloss_notifications.people(user_id,handle)
 select u.id,'ol.'||left(regexp_replace(lower(split_part(u.email,'@',1)),'[^a-z0-9_.-]','','g'),32)||'.'||left(u.id::text,8)
 from auth.users u where oneloss_notifications.card_access(u.id,p_card) on conflict(user_id) do nothing;
 insert into oneloss_notifications.events(actor,event_key) values(p_actor,p_event) on conflict do nothing;
 insert into oneloss_notifications.inbox(recipient,canon_key,card_id,actor,event_key,kind,body)
 select c.user_id,oneloss_notifications.card_job(p_card),p_card,p_actor,p_event,
 case when exists(select 1 from oneloss_notifications.people person,
 regexp_matches(p_body,'(?:^|[^a-zA-Z0-9_.@-])@([a-zA-Z0-9_.-]+)','g') token
 where person.user_id=c.user_id and lower(token[1])=person.handle) then 'mention' else 'comment' end,left(p_body,2000)
 from (
  select m.user_id from oneloss_notifications.card_members(p_card) m
  union select t.author_id from public.job_comment_threads t
   where p_root is not null and t.card_id=p_card and t.root_id=p_root and t.author_id is not null
  union select person.user_id from oneloss_notifications.people person,
   regexp_matches(p_body,'(?:^|[^a-zA-Z0-9_.@-])@([a-zA-Z0-9_.-]+)','g') token where lower(token[1])=person.handle
 ) c where c.user_id<>p_actor and oneloss_notifications.card_access(c.user_id,p_card)
 and not oneloss_notifications.card_muted(c.user_id,p_card)
 on conflict(recipient,actor,event_key) do nothing;
end $$;

create or replace function oneloss_notifications.dispatch(p_action text,p_data jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare me uuid:=auth.uid(); card text:=p_data->>'card_id'; person uuid; result jsonb; external_people jsonb;
 n integer; event text; message text;
begin
 if me is null then raise exception 'Sign in to OneLoss first' using errcode='42501'; end if;
 if p_action='read' then
  update oneloss_notifications.inbox i set read_at=case when coalesce((p_data->>'read')::boolean,true) then now() else null end
  where i.recipient=me and i.id=(p_data->>'id')::uuid and oneloss_notifications.card_access(me,i.card_id);
  get diagnostics n=row_count; return jsonb_build_object('ok',n=1);
 elsif p_action='inbox' then
  select coalesce(jsonb_agg(to_jsonb(t) order by t.created_at desc,t.id),'[]') into result from (
   select i.id,i.kind,i.body,i.created_at,i.read_at,i.card_id,coalesce(c.payload->>'name',j.display_name,'Job') client,
    coalesce(nullif(u.raw_user_meta_data->>'display_name',''),'OneLoss teammate') actor,
    oneloss_notifications.card_muted(me,i.card_id) muted
   from oneloss_notifications.inbox i join auth.users u on u.id=i.actor
   left join public.jobs j on j.canon_key=i.canon_key
   left join lateral oneloss_notifications.card_snapshot(i.card_id) c on true
   where i.recipient=me and oneloss_notifications.card_access(me,i.card_id)
    and (not coalesce((p_data->>'unread')::boolean,false) or i.read_at is null)
    and (coalesce(p_data->>'filter','all')<>'mentions' or i.kind='mention')
    and (coalesce(p_data->>'filter','all')<>'my_jobs' or exists(select 1 from oneloss_notifications.card_members(i.card_id) m where m.user_id=me))
   order by i.created_at desc,i.id limit 100
  ) t;
  return jsonb_build_object('ok',true,'items',result);
 end if;
 -- Exact full IDs or exact mirrored short links only. Never match customer names.
 select count(distinct c.card_id),min(c.card_id) into n,card from public.hub_trello_mirror_cards c
 where (p_data->>'card_id') in(c.card_id,c.payload->>'shortLink');
 if n<>1 or not oneloss_notifications.card_access(me,card) then
  raise exception 'This card is unavailable to your OneLoss account' using errcode='42501'; end if;
 if p_action='members' then
  insert into oneloss_notifications.people(user_id,handle)
  select u.id,'ol.'||left(regexp_replace(lower(split_part(u.email,'@',1)),'[^a-z0-9_.-]','','g'),32)||'.'||left(u.id::text,8)
  from auth.users u where oneloss_notifications.card_access(u.id,card) on conflict(user_id) do nothing;
  select coalesce(jsonb_agg(jsonb_build_object('id',u.id,'username',p.handle,
   'name',coalesce(nullif(u.raw_user_meta_data->>'display_name',''),split_part(u.email,'@',1)),
   'member',m.user_id is not null,'source',coalesce(m.source,'OneLoss')) order by p.handle),'[]') into result
  from oneloss_notifications.people p join auth.users u on u.id=p.user_id
  left join oneloss_notifications.card_members(card) m on m.user_id=u.id
  where oneloss_notifications.card_access(u.id,card);
  select coalesce(jsonb_agg(jsonb_build_object('id',x.id,'name',coalesce(nullif(detail->>'fullName',''),'Trello member '||right(x.id,6)),
   'username',detail->>'username','source','Trello','needs_match',true) order by x.id),'[]') into external_people
  from oneloss_notifications.card_snapshot(card) c
  cross join lateral jsonb_array_elements_text(coalesce(c.payload->'idMembers','[]'::jsonb)) x(id)
  left join lateral (select m as detail from jsonb_array_elements(coalesce(c.details_json->'members','[]'::jsonb)) m where m->>'id'=x.id limit 1) d on true
  where not exists(select 1 from oneloss_notifications.trello_accounts a where a.trello_member_id=x.id);
  return jsonb_build_object('ok',true,'people',result,'unmatched',external_people,'me',me,'muted',oneloss_notifications.card_muted(me,card));
 elsif p_action='set_member' then
  person:=(p_data->>'user_id')::uuid;
  if not oneloss_notifications.card_access(person,card) then raise exception 'Person does not have access to this card' using errcode='42501'; end if;
  if p_data->>'member' is null then raise exception 'Membership choice required'; end if;
  insert into oneloss_notifications.card_member_choices(card_id,user_id,member,changed_by)
   values(card,person,(p_data->>'member')::boolean,me)
   on conflict(card_id,user_id) do update set member=excluded.member,changed_by=me,changed_at=now();
  return jsonb_build_object('ok',true);
 elsif p_action='mute' then
  insert into oneloss_notifications.card_preferences(card_id,user_id,muted) values(card,me,(p_data->>'muted')::boolean)
   on conflict(card_id,user_id) do update set muted=excluded.muted;
  return jsonb_build_object('ok',true);
 elsif p_action='emit' then
  if (p_data->>'actor_id')::uuid is distinct from me then raise exception 'Notification author no longer matches signed-in user' using errcode='42501'; end if;
  event:=p_data->>'event_key'; message:=p_data->>'body';
  if event is null or length(event)>160 or length(event)<8 or message is null or length(message)>65536 then raise exception 'Invalid comment notification'; end if;
  perform oneloss_notifications.deliver_activity(me,card,event,message);
  return jsonb_build_object('ok',true);
 end if;
 raise exception 'Unknown notification action';
end $$;
revoke all on function oneloss_notifications.card_snapshot(text),oneloss_notifications.card_job(text),
 oneloss_notifications.card_access(uuid,text),oneloss_notifications.card_members(text),
 oneloss_notifications.card_muted(uuid,text),oneloss_notifications.deliver_activity(uuid,text,text,text,text)
 from public,anon,authenticated;
-- No data backfill and no event emission: existing mirrored IDs become effective
-- immediately; each subsequent mirror update changes only the Trello contribution.
commit;
