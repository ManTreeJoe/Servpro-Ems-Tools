-- Personal OneLoss notifications. Membership never grants job/board access.
-- Private tables are reachable only through the checked RPC below.
create schema if not exists oneloss_notifications;
revoke all on schema oneloss_notifications from public, anon;
grant usage on schema oneloss_notifications to authenticated;

create table oneloss_notifications.people (
  user_id uuid primary key references auth.users(id) on delete cascade,
  handle text not null unique
);
create table oneloss_notifications.members (
  canon_key text not null references public.jobs(canon_key) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  added_by uuid not null references auth.users(id),
  added_at timestamptz not null default now(),
  primary key(canon_key,user_id)
);
create index notification_members_user on oneloss_notifications.members(user_id,canon_key);
create table oneloss_notifications.preferences (
  user_id uuid not null references auth.users(id) on delete cascade,
  canon_key text not null references public.jobs(canon_key) on delete cascade,
  muted boolean not null default false,
  primary key(user_id,canon_key)
);
create table oneloss_notifications.inbox (
  id uuid primary key default gen_random_uuid(),
  recipient uuid not null references auth.users(id) on delete cascade,
  canon_key text not null references public.jobs(canon_key) on delete cascade,
  card_id text not null,
  actor uuid not null references auth.users(id),
  event_key text not null,
  kind text not null check(kind in ('mention','comment','membership')),
  body text not null,
  created_at timestamptz not null default now(),
  read_at timestamptz,
  unique(recipient,actor,event_key)
);
create index notification_inbox_recent on oneloss_notifications.inbox(recipient,created_at desc,id);
create index notification_inbox_job on oneloss_notifications.inbox(canon_key);
create index notification_inbox_actor on oneloss_notifications.inbox(actor);
create index notification_preferences_job on oneloss_notifications.preferences(canon_key);
create index notification_members_actor on oneloss_notifications.members(added_by);
create table oneloss_notifications.events (
  actor uuid not null references auth.users(id) on delete cascade,
  event_key text not null,
  created_at timestamptz not null default now(),
  primary key(actor,event_key)
);
alter table oneloss_notifications.events enable row level security;
alter table oneloss_notifications.people enable row level security;
alter table oneloss_notifications.members enable row level security;
alter table oneloss_notifications.preferences enable row level security;
alter table oneloss_notifications.inbox enable row level security;
revoke all on all tables in schema oneloss_notifications from public,anon,authenticated;

-- Internal helper, not callable by clients. Checks current department grants,
-- not user-editable metadata or a stale JWT department claim.
create function oneloss_notifications.can_access(p_user uuid,p_job text,p_card text)
returns boolean language sql stable set search_path='' as $$
  select auth.uid() is not null and exists (
    select 1 from public.jobs j
    join public.job_links l on l.canon_key=j.canon_key
    join public.hub_trello_mirror_cards c on l.link_value in (c.card_id,c.payload->>'shortLink')
    join public.app_job_boards b on b.board_id=c.board_id
    where j.canon_key=p_job and p_card in (c.card_id,c.payload->>'shortLink')
      and l.link_type in ('trello_card','trello_card_contents','trello_card_recon')
      and b.enabled and c.present
      and exists(select 1 from public.app_user_departments d where d.user_id=p_user)
      and (j.department is null or exists(select 1 from public.app_user_departments d
           where d.user_id=p_user and d.department=j.department))
      and b.required_departments <@ array(select d.department from public.app_user_departments d where d.user_id=p_user)
      and exists(select 1 from auth.users u where u.id=p_user and u.deleted_at is null
           and (u.banned_until is null or u.banned_until < now()))
  );
$$;
revoke all on function oneloss_notifications.can_access(uuid,text,text) from public,anon,authenticated;

-- A narrow service boundary: no client supplies actor/recipient for comments,
-- and every branch checks auth.uid() and current access before exposing data.
create function oneloss_notifications.dispatch(p_action text,p_data jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare
  me uuid := auth.uid(); job text; card text:=p_data->>'card_id'; person uuid;
  result jsonb; n integer; event text; message text;
begin
  if me is null then raise exception 'Sign in to OneLoss first' using errcode='42501'; end if;
  if p_action in ('inbox','read') then
    if p_action='read' then
      update oneloss_notifications.inbox i set read_at=case when coalesce((p_data->>'read')::boolean,true) then now() else null end
      where i.recipient=me and i.id=(p_data->>'id')::uuid
        and oneloss_notifications.can_access(me,i.canon_key,i.card_id);
      get diagnostics n=row_count;
      return jsonb_build_object('ok',n=1);
    end if;
    select coalesce(jsonb_agg(row_to_json(t) order by t.created_at desc,t.id),'[]') into result from (
      select i.id,i.kind,i.body,i.created_at,i.read_at,i.card_id,j.display_name as client,
        coalesce(nullif(u.raw_user_meta_data->>'display_name',''),'OneLoss teammate') as actor,
        coalesce(p.muted,false) as muted,
        case l.link_type when 'trello_card_contents' then 'Contents' when 'trello_card_recon' then 'Recon' else 'EMS' end as division
      from oneloss_notifications.inbox i
      join public.jobs j on j.canon_key=i.canon_key
      join auth.users u on u.id=i.actor
      left join oneloss_notifications.preferences p on p.user_id=me and p.canon_key=i.canon_key
      left join lateral (select x.link_type from public.job_links x join public.hub_trello_mirror_cards c
        on x.link_value in (c.card_id,c.payload->>'shortLink')
        where x.canon_key=i.canon_key and c.card_id=i.card_id and x.link_type in ('trello_card','trello_card_contents','trello_card_recon')
        order by x.link_type limit 1) l on true
      where i.recipient=me and oneloss_notifications.can_access(me,i.canon_key,i.card_id)
        and (not coalesce((p_data->>'unread')::boolean,false) or i.read_at is null)
        and (coalesce(p_data->>'filter','all')<>'mentions' or i.kind='mention')
        and (coalesce(p_data->>'filter','all')<>'my_jobs' or exists(select 1 from oneloss_notifications.members m where m.user_id=me and m.canon_key=i.canon_key))
      order by i.created_at desc,i.id limit 100
    ) t;
    return jsonb_build_object('ok',true,'items',result);
  end if;

  -- Resolve only an exact saved card link; ambiguous jobs fail closed.
  select count(distinct l.canon_key),min(l.canon_key),min(c.card_id) into n,job,card
  from public.job_links l join public.hub_trello_mirror_cards c
    on l.link_value in (c.card_id,c.payload->>'shortLink')
  where (p_data->>'card_id') in (c.card_id,c.payload->>'shortLink')
    and l.link_type in ('trello_card','trello_card_contents','trello_card_recon');
  if n<>1 or not oneloss_notifications.can_access(me,job,card) then
    raise exception 'This card needs one verified shared job link and job access' using errcode='42501';
  end if;

  if p_action in ('members','emit') then
    -- Stable, explicitly OneLoss handles; never guessed from Trello usernames.
    insert into oneloss_notifications.people(user_id,handle)
      select u.id,'ol.'||left(regexp_replace(lower(split_part(u.email,'@',1)),'[^a-z0-9_.-]','','g'),32)||'.'||left(u.id::text,8)
      from auth.users u where oneloss_notifications.can_access(u.id,job,card)
      on conflict(user_id) do nothing;
  end if;
  if p_action='members' then
    select coalesce(jsonb_agg(jsonb_build_object('id',u.id,'username',p.handle,
      'name',coalesce(nullif(u.raw_user_meta_data->>'display_name',''),split_part(u.email,'@',1)),
      'member',m.user_id is not null,'source','OneLoss') order by p.handle),'[]') into result
    from oneloss_notifications.people p join auth.users u on u.id=p.user_id
    left join oneloss_notifications.members m on m.user_id=u.id and m.canon_key=job
    where oneloss_notifications.can_access(u.id,job,card);
    return jsonb_build_object('ok',true,'people',result,'me',me,'muted',coalesce((select p.muted from oneloss_notifications.preferences p where p.user_id=me and p.canon_key=job),false));
  elsif p_action='set_member' then
    person:=(p_data->>'user_id')::uuid;
    if not oneloss_notifications.can_access(person,job,card) then
      raise exception 'Person does not have access to this job' using errcode='42501';
    end if;
    if (p_data->>'member')::boolean then
      insert into oneloss_notifications.members(canon_key,user_id,added_by) values(job,person,me) on conflict do nothing;
      get diagnostics n=row_count;
      if n=1 and person<>me and not coalesce((select p.muted from oneloss_notifications.preferences p where p.user_id=person and p.canon_key=job),false) then
        insert into oneloss_notifications.inbox(recipient,canon_key,card_id,actor,event_key,kind,body)
          values(person,job,card,me,'member:'||gen_random_uuid(),'membership','Added you to this job');
      end if;
    else
      delete from oneloss_notifications.members where canon_key=job and user_id=person;
    end if;
    return jsonb_build_object('ok',true);
  elsif p_action='mute' then
    insert into oneloss_notifications.preferences(user_id,canon_key,muted)
      values(me,job,(p_data->>'muted')::boolean)
      on conflict(user_id,canon_key) do update set muted=excluded.muted;
    return jsonb_build_object('ok',true);
  elsif p_action='emit' then
    if (p_data->>'actor_id')::uuid is distinct from me then
      raise exception 'Notification author no longer matches signed-in user' using errcode='42501';
    end if;
    event:=p_data->>'event_key'; message:=p_data->>'body';
    if event is null or length(event)>160 or length(event)<8 or message is null or length(message)>65536 then
      raise exception 'Invalid comment notification';
    end if;
    insert into oneloss_notifications.events(actor,event_key) values(me,event) on conflict do nothing;
    get diagnostics n=row_count;
    if n=0 then return jsonb_build_object('ok',true); end if;
    insert into oneloss_notifications.inbox(recipient,canon_key,card_id,actor,event_key,kind,body)
      select p.user_id,job,card,me,event,
        case when exists(select 1 from regexp_matches(message,'(?:^|[^a-zA-Z0-9_.@-])@([a-zA-Z0-9_.-]+)','g') tokens where lower(tokens[1])=p.handle) then 'mention' else 'comment' end,
        left(message,2000)
      from oneloss_notifications.people p
      left join oneloss_notifications.members m on m.user_id=p.user_id and m.canon_key=job
      left join oneloss_notifications.preferences pref on pref.user_id=p.user_id and pref.canon_key=job
      where p.user_id<>me and oneloss_notifications.can_access(p.user_id,job,card) and not coalesce(pref.muted,false)
        and (m.user_id is not null or exists(select 1 from regexp_matches(message,'(?:^|[^a-zA-Z0-9_.@-])@([a-zA-Z0-9_.-]+)','g') tokens where lower(tokens[1])=p.handle))
      on conflict(recipient,actor,event_key) do nothing;
    return jsonb_build_object('ok',true);
  end if;
  raise exception 'Unknown notification action';
end;
$$;
revoke all on function oneloss_notifications.dispatch(text,jsonb) from public,anon;
grant execute on function oneloss_notifications.dispatch(text,jsonb) to authenticated;
create function public.oneloss_notifications(p_action text,p_data jsonb default '{}')
returns jsonb language sql security invoker set search_path='' as $$
  select oneloss_notifications.dispatch(p_action,p_data);
$$;
revoke all on function public.oneloss_notifications(text,jsonb) from public,anon;
grant execute on function public.oneloss_notifications(text,jsonb) to authenticated;
