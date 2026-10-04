-- Additive only: no changes to jobs, files, client/claim tables or schema_version.
create table public.app_job_boards (
  board_id text primary key, name text not null, workspace text not null,
  department text not null, required_departments text[] not null,
  lists jsonb not null default '[]', enabled boolean not null default true
);
insert into public.app_job_boards
select board_id,label,reader_workspace,reader_department,required_departments,lists_json,enabled
from public.hub_trello_sync_sources
where reader_workspace is not null and reader_department is not null
  and cardinality(required_departments)>0;
alter table public.app_job_boards enable row level security;
revoke all on public.app_job_boards from anon,authenticated;
grant select on public.app_job_boards to authenticated;
create policy app_board_read on public.app_job_boards for select to authenticated
using (enabled and required_departments <@ array(select public.my_departments()));

create table public.app_card_placements (
  placement_id uuid primary key default gen_random_uuid(),
  card_id text not null unique, origin_board_id text not null references public.app_job_boards,
  board_id text not null references public.app_job_boards, list_id text not null,
  title text not null, card_json jsonb not null, workspace text not null,
  required_departments text[] not null,
  state text not null default 'active' check(state in ('active','archived','deleted')),
  version integer not null default 0, synced_version integer not null default 0,
  sync_error text, lease_token uuid, lease_until timestamptz,
  events jsonb not null default '[]', updated_at timestamptz not null default now()
);
alter table public.app_card_placements enable row level security;
revoke all on public.app_card_placements from anon,authenticated;
grant select on public.app_card_placements to authenticated;
grant insert(card_id) on public.app_card_placements to authenticated;
grant update(board_id,list_id,state,synced_version,sync_error,lease_token,lease_until)
on public.app_card_placements to authenticated;
create policy app_placement_read on public.app_card_placements for select to authenticated
using (required_departments <@ array(select public.my_departments()));
create policy app_placement_insert on public.app_card_placements for insert to authenticated
with check (required_departments <@ array(select public.my_departments()));
create policy app_placement_update on public.app_card_placements for update to authenticated
using (required_departments <@ array(select public.my_departments()))
with check (required_departments <@ array(select public.my_departments()));

-- Invoker trigger: respects the caller's board and mirror RLS. Direct REST
-- updates must obey the same lifecycle invariants as the RPC.
create function public.app_placement_guard() returns trigger language plpgsql
set search_path='' as $$
declare source public.app_job_boards; target public.app_job_boards; payload jsonb;
begin
  if auth.uid() is null then raise exception 'Sign in required'; end if;
  if TG_OP='INSERT' then
    select c.payload into payload from public.hub_trello_mirror_cards c
      where c.card_id=new.card_id and c.present;
    select b.* into source from public.app_job_boards b
      join public.hub_trello_mirror_cards c on b.board_id=c.board_id
      where c.card_id=new.card_id and c.present;
    if source.board_id is null then raise exception 'Card is not in accessible saved board data yet'; end if;
    new.origin_board_id:=source.board_id; new.board_id:=source.board_id;
    new.list_id:=payload->>'idList'; new.title:=coalesce(payload->>'name','Job');
    new.card_json:=payload; new.workspace:=source.workspace;
    new.required_departments:=source.required_departments;
    return new;
  end if;
  if (new.board_id,new.list_id,new.state) is distinct from (old.board_id,old.list_id,old.state) then
    if old.state='deleted' then raise exception 'Deleted placements cannot be restored'; end if;
    if old.lease_until>now() then raise exception 'Trello sync is finishing. Try again shortly'; end if;
    if new.state='deleted' and (old.state<>'archived' or not public.is_app_admin()) then
      raise exception 'Only an administrator can delete an archived placement'; end if;
    if old.state='archived' and new.state='archived' then raise exception 'Restore before moving'; end if;
    select * into target from public.app_job_boards where board_id=new.board_id and enabled;
    if target.board_id is null or target.workspace<>old.workspace then raise exception 'Destination is not accessible in this workplace'; end if;
    if new.state='active' and not exists(select 1 from jsonb_array_elements(target.lists) x
       where x->>'id'=new.list_id and coalesce((x->>'closed')::boolean,false)=false) then
      raise exception 'Choose an active destination section'; end if;
    new.required_departments:=array(select distinct unnest(old.required_departments||target.required_departments));
    new.version:=old.version+1; new.updated_at:=now(); new.sync_error:=null;
    new.lease_token:=null; new.lease_until:=null;
    new.events:=old.events||jsonb_build_array(jsonb_build_object('actor',auth.uid(),'at',now(),
      'from_board',old.board_id,'from_list',old.list_id,'from_state',old.state,
      'board',new.board_id,'list',new.list_id,'state',new.state,'version',new.version));
  end if;
  if new.synced_version>new.version or new.synced_version<old.synced_version then
    raise exception 'Invalid sync version'; end if;
  return new;
end $$;
create trigger app_placement_guard before insert or update on public.app_card_placements
for each row execute function public.app_placement_guard();

create function public.app_placement_change(p_card text,p_action text,p_version integer,
 p_board text default null,p_list text default null) returns jsonb language plpgsql
set search_path='' as $$
declare r public.app_card_placements;
begin
  if auth.uid() is null then raise exception 'Sign in required'; end if;
  if p_action not in ('move','archive','restore','delete') then raise exception 'Unknown card action'; end if;
  if not exists(select 1 from public.app_card_placements where card_id=p_card) then
    insert into public.app_card_placements(card_id) values(p_card) on conflict(card_id) do nothing;
  end if;
  select * into r from public.app_card_placements where card_id=p_card for update;
  if r.card_id is null then raise exception 'Placement is not accessible'; end if;
  if r.version<>p_version then raise exception 'Card changed on another screen. Refresh and try again'; end if;
  if p_action in ('move','archive') and r.state<>'active' then raise exception 'Card is not active'; end if;
  if p_action in ('restore','delete') and r.state<>'archived' then raise exception 'Archive the card first'; end if;
  update public.app_card_placements set
    board_id=case when p_action in ('move','restore') then coalesce(p_board,r.board_id) else r.board_id end,
    list_id=case when p_action in ('move','restore') then coalesce(p_list,r.list_id) else r.list_id end,
    state=case p_action when 'archive' then 'archived' when 'delete' then 'deleted' else 'active' end
    where card_id=p_card returning * into r;
  return to_jsonb(r);
end $$;

-- One lease per placement across all PCs; desired state and pending sync are
-- the same durable row. Replays are idempotent PUTs, never provider DELETEs.
create function public.app_placement_claim(p_card text,p_version integer,p_token uuid)
returns jsonb language plpgsql set search_path='' as $$
declare r public.app_card_placements;
begin
  update public.app_card_placements set lease_token=p_token,lease_until=now()+interval '2 minutes'
  where card_id=p_card and version=p_version and synced_version<version
    and (lease_until is null or lease_until<now()) returning * into r;
  return case when r.card_id is null then null else to_jsonb(r) end;
end $$;
create function public.app_placement_ack(p_card text,p_version integer,p_token uuid,p_error text default null)
returns boolean language plpgsql set search_path='' as $$
begin
  update public.app_card_placements set
    synced_version=case when p_error is null then p_version else synced_version end,
    sync_error=left(p_error,300),lease_token=null,lease_until=null
    where card_id=p_card and version=p_version and lease_token=p_token;
  return found;
end $$;
revoke all on function public.app_placement_guard() from public,anon;
revoke all on function public.app_placement_change(text,text,integer,text,text) from public,anon;
revoke all on function public.app_placement_claim(text,integer,uuid) from public,anon;
revoke all on function public.app_placement_ack(text,integer,uuid,text) from public,anon;
grant execute on function public.app_placement_change(text,text,integer,text,text),
 public.app_placement_claim(text,integer,uuid),public.app_placement_ack(text,integer,uuid,text)
to authenticated;

grant all on public.app_job_boards,public.app_card_placements to service_role;
create function public.app_board_catalog_refresh() returns trigger language plpgsql
set search_path='' as $$
begin
  if new.reader_workspace is not null and new.reader_department is not null
     and cardinality(new.required_departments)>0 then
    insert into public.app_job_boards values(new.board_id,new.label,new.reader_workspace,
      new.reader_department,new.required_departments,new.lists_json,new.enabled)
    on conflict(board_id) do update set name=excluded.name,lists=excluded.lists,
      enabled=excluded.enabled,required_departments=excluded.required_departments;
  end if;
  return new;
end $$;
revoke all on function public.app_board_catalog_refresh() from public,anon,authenticated;
create trigger app_board_catalog_refresh after insert or update on public.hub_trello_sync_sources
for each row execute function public.app_board_catalog_refresh();
