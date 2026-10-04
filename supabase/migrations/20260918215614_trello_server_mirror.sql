-- Inbound-only shadow mirror. No client access, canonical job changes, credentials,
-- or scheduled work are enabled by this migration. Deliberately independent of 011.
begin;

create table public.hub_trello_sync_control (
  singleton boolean primary key default true check (singleton),
  enabled boolean not null default false,
  lease_id uuid,
  lease_until timestamptz,
  not_before timestamptz not null default now(),
  last_started_at timestamptz,
  last_finished_at timestamptz,
  last_error_code text
);
insert into public.hub_trello_sync_control(singleton) values (true);

create table public.hub_trello_sync_sources (
  board_id text primary key check (board_id ~ '^[0-9a-f]{24}$'),
  enabled boolean not null default false,
  -- A source is NOT a franchise. Mixed IE/OC boards must be mapped before client cutover.
  label text not null,
  next_poll_at timestamptz not null default now(),
  last_attempt_at timestamptz,
  last_metadata_at timestamptz,
  consecutive_failures integer not null default 0,
  last_error_code text,
  board_json jsonb,
  lists_json jsonb not null default '[]'::jsonb
);
create index hub_trello_sync_due_idx
  on public.hub_trello_sync_sources(next_poll_at) where enabled;

create table public.hub_trello_mirror_cards (
  board_id text not null references public.hub_trello_sync_sources(board_id),
  card_id text not null check (card_id ~ '^[0-9a-f]{24}$'),
  payload jsonb not null,
  revision text not null,
  present boolean not null default true,
  last_seen_at timestamptz not null default now(),
  comments_json jsonb not null default '[]'::jsonb,
  comments_revision text,
  comments_completed_at timestamptz,
  comment_attempt_at timestamptz,
  comment_error_code text,
  -- Incomplete pages are never substituted for the last complete conversation.
  scan_revision text,
  scan_before text,
  scan_json jsonb not null default '[]'::jsonb,
  primary key (board_id, card_id)
);
create index hub_trello_mirror_comment_queue_idx
  on public.hub_trello_mirror_cards(board_id, comment_attempt_at nulls first)
  where present;

alter table public.hub_trello_sync_control enable row level security;
alter table public.hub_trello_sync_sources enable row level security;
alter table public.hub_trello_mirror_cards enable row level security;
revoke all on public.hub_trello_sync_control, public.hub_trello_sync_sources,
  public.hub_trello_mirror_cards from public, anon, authenticated;
grant select, insert, update, delete on public.hub_trello_sync_control,
  public.hub_trello_sync_sources, public.hub_trello_mirror_cards to service_role;

-- All RPCs are SECURITY INVOKER and service-only. The lease lock fences every
-- checkpoint: an expired worker cannot overwrite data saved by its successor.
create function public.hub_trello_claim() returns uuid
language plpgsql security invoker set search_path = '' as $$
declare claimed uuid;
begin
  update public.hub_trello_sync_control
     set lease_id = gen_random_uuid(), lease_until = clock_timestamp() + interval '3 minutes',
         last_started_at = clock_timestamp()
   where singleton and enabled and not_before <= clock_timestamp()
     and (lease_until is null or lease_until < clock_timestamp())
  returning lease_id into claimed;
  return claimed;
end;
$$;

create function public.hub_trello_assert_lease(p_lease uuid) returns void
language plpgsql security invoker set search_path = '' as $$
begin
  perform 1 from public.hub_trello_sync_control
   where singleton and enabled and lease_id = p_lease and lease_until > clock_timestamp()
   for update;
  if not found then raise exception 'sync_lease_expired'; end if;
end;
$$;

create function public.hub_trello_commit_board(
  p_lease uuid, p_board_id text, p_board jsonb, p_lists jsonb, p_cards jsonb
) returns void language plpgsql security invoker set search_path = '' as $$
begin
  perform public.hub_trello_assert_lease(p_lease);
  perform 1 from public.hub_trello_sync_sources where board_id = p_board_id and enabled for update;
  if not found then raise exception 'source_not_enabled'; end if;
  if p_board is null or p_lists is null or p_cards is null
     or jsonb_typeof(p_board) <> 'object' or p_board->>'id' is distinct from p_board_id
     or jsonb_typeof(p_lists) <> 'array' or jsonb_typeof(p_cards) <> 'array' then
    raise exception 'invalid_board_snapshot';
  end if;
  if exists (select 1 from jsonb_array_elements(p_cards) c
    where c->>'idBoard' is distinct from p_board_id
       or coalesce(c->>'id','') !~ '^[0-9a-f]{24}$'
       or not exists(select 1 from jsonb_array_elements(p_lists) l where l->>'id' = c->>'idList'))
    or (select count(*) <> count(distinct c->>'id') from jsonb_array_elements(p_cards) c) then
    raise exception 'invalid_card_snapshot';
  end if;

  -- One transaction, after a complete successful provider fetch. No pre-emptive
  -- clearing and no deletion of cards/comments when a card leaves this board.
  update public.hub_trello_mirror_cards set present = false
   where board_id = p_board_id and present
     and card_id not in (select c->>'id' from jsonb_array_elements(p_cards) c);
  insert into public.hub_trello_mirror_cards(board_id, card_id, payload, revision)
  select p_board_id, c->>'id', c, md5(c::text) from jsonb_array_elements(p_cards) c
  on conflict (board_id, card_id) do update
     set payload = excluded.payload, revision = excluded.revision,
         present = true, last_seen_at = clock_timestamp();
  update public.hub_trello_sync_sources
     set board_json = p_board, lists_json = p_lists, last_metadata_at = clock_timestamp()
   where board_id = p_board_id;
end;
$$;

create function public.hub_trello_comment_work(p_lease uuid, p_board_id text, p_limit integer default 20)
returns table(card_id text, revision text, before_cursor text)
language plpgsql security invoker set search_path = '' as $$
begin
  perform public.hub_trello_assert_lease(p_lease);
  return query
    select c.card_id, c.revision,
           case when c.scan_revision = c.revision then c.scan_before else null end
      from public.hub_trello_mirror_cards c
      join public.hub_trello_sync_sources s using(board_id)
     where c.board_id = p_board_id and s.enabled and c.present
       and (c.comments_revision is distinct from c.revision
         or c.comments_completed_at < clock_timestamp() - interval '1 day'
         or c.scan_revision is not null)
     order by c.comment_attempt_at nulls first, c.card_id
     limit greatest(1, least(coalesce(p_limit,20),100));
end;
$$;

create function public.hub_trello_comment_page(
  p_lease uuid, p_board_id text, p_card_id text, p_revision text,
  p_before text, p_page jsonb, p_next text
) returns boolean language plpgsql security invoker set search_path = '' as $$
declare c public.hub_trello_mirror_cards%rowtype; combined jsonb;
begin
  perform public.hub_trello_assert_lease(p_lease);
  select * into c from public.hub_trello_mirror_cards
   where board_id = p_board_id and card_id = p_card_id and present for update;
  if not found or c.revision <> p_revision then return false; end if;
  if p_before is distinct from (case when c.scan_revision = p_revision then c.scan_before else null end) then
    return false; -- replay or stale page; don't append it twice
  end if;
  if p_page is null or jsonb_typeof(p_page) <> 'array'
    or (p_next is not null and (p_next = p_before or p_next !~ '^[0-9a-f]{24}$')) then
    raise exception 'invalid_comment_page';
  end if;
  if exists(select 1 from jsonb_array_elements(p_page) a
    where coalesce(a->>'id','') !~ '^[0-9a-f]{24}$' or a->>'type' is distinct from 'commentCard'
       or a#>>'{data,card,id}' is distinct from p_card_id) then
    raise exception 'invalid_comment_action';
  end if;
  select coalesce(jsonb_agg(a order by a->>'date' desc, a->>'id' desc), '[]'::jsonb) into combined
    from (select distinct on (a->>'id') a
      from jsonb_array_elements(p_page || case when c.scan_revision = p_revision then c.scan_json else '[]'::jsonb end) a
      order by a->>'id') deduped;
  update public.hub_trello_mirror_cards
     set comment_attempt_at = clock_timestamp(), comment_error_code = null,
         scan_revision = case when p_next is null then null else p_revision end,
         scan_before = p_next, scan_json = case when p_next is null then '[]'::jsonb else combined end,
         comments_json = case when p_next is null then combined else comments_json end,
         comments_revision = case when p_next is null then p_revision else comments_revision end,
         comments_completed_at = case when p_next is null then clock_timestamp() else comments_completed_at end
   where board_id = p_board_id and card_id = p_card_id;
  return true;
end;
$$;

create function public.hub_trello_record_error(
  p_lease uuid, p_board_id text, p_code text, p_card_id text default null
) returns void language plpgsql security invoker set search_path = '' as $$
begin
  perform public.hub_trello_assert_lease(p_lease);
  -- Store codes only, never provider bodies, tokens or request URLs.
  if p_code !~ '^[a-z_0-9]{1,80}$' then raise exception 'invalid_error_code'; end if;
  if p_card_id is not null then
    update public.hub_trello_mirror_cards
       set comment_error_code = p_code, comment_attempt_at = clock_timestamp()
     where board_id = p_board_id and card_id = p_card_id;
  end if;
  if p_card_id is null then
    update public.hub_trello_sync_sources
       set last_error_code = p_code where board_id = p_board_id;
  end if;
end;
$$;

create function public.hub_trello_finish_source(p_lease uuid, p_board_id text, p_ok boolean)
returns void language plpgsql security invoker set search_path = '' as $$
begin
  perform public.hub_trello_assert_lease(p_lease);
  update public.hub_trello_sync_sources
     set last_attempt_at = clock_timestamp(),
         consecutive_failures = case when p_ok then 0 else least(consecutive_failures+1,10) end,
         last_error_code = case when p_ok then null else coalesce(last_error_code,'sync_failed') end,
         next_poll_at = case when p_ok then
           (select last_started_at + interval '120 seconds' from public.hub_trello_sync_control where singleton)
           else clock_timestamp() + make_interval(secs => least(1800,120 * (2^least(consecutive_failures+1,4))::integer)) end
   where board_id = p_board_id;
end;
$$;

create function public.hub_trello_release(p_lease uuid, p_cooldown integer default 0, p_error text default null)
returns void language plpgsql security invoker set search_path = '' as $$
begin
  if p_error is not null and p_error !~ '^[a-z_0-9]{1,80}$' then raise exception 'invalid_error_code'; end if;
  update public.hub_trello_sync_control
     set lease_id = null, lease_until = null, last_finished_at = clock_timestamp(),
         last_error_code = p_error,
         not_before = clock_timestamp() + make_interval(secs => greatest(0,least(p_cooldown,3600)))
   where singleton and lease_id = p_lease and lease_until > clock_timestamp();
end;
$$;

revoke all on function public.hub_trello_claim(), public.hub_trello_assert_lease(uuid),
  public.hub_trello_commit_board(uuid,text,jsonb,jsonb,jsonb),
  public.hub_trello_comment_work(uuid,text,integer),
  public.hub_trello_comment_page(uuid,text,text,text,text,jsonb,text),
  public.hub_trello_record_error(uuid,text,text,text),
  public.hub_trello_finish_source(uuid,text,boolean), public.hub_trello_release(uuid,integer,text)
  from public, anon, authenticated;
grant execute on function public.hub_trello_claim(), public.hub_trello_assert_lease(uuid),
  public.hub_trello_commit_board(uuid,text,jsonb,jsonb,jsonb),
  public.hub_trello_comment_work(uuid,text,integer),
  public.hub_trello_comment_page(uuid,text,text,text,text,jsonb,text),
  public.hub_trello_record_error(uuid,text,text,text),
  public.hub_trello_finish_source(uuid,text,boolean), public.hub_trello_release(uuid,integer,text)
  to service_role;

commit;
