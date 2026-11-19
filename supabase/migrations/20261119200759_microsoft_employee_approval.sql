-- Microsoft employee access. Apply to verified Main only, before client rollout.
-- Microsoft-only enforcement is activated separately after recovery verification.
begin;

create schema oneloss_access;
revoke all on schema oneloss_access from public, anon;
grant usage on schema oneloss_access to authenticated, service_role, supabase_auth_admin;

create table oneloss_access.controls (
 singleton boolean primary key default true check(singleton),
 microsoft_only boolean not null default false
);
insert into oneloss_access.controls(singleton) values(true);

create table oneloss_access.accounts (
 user_id uuid primary key references auth.users(id) on delete cascade,
 status text not null default 'pending' check(status in ('pending','approved','rejected','suspended')),
 role text check(role in ('viewer','editor','admin')),
 revision bigint not null default 0 check(revision>=0),
 requested_at timestamptz not null default now(),
 reviewed_at timestamptz,
 reviewed_by uuid references auth.users(id),
 check(status<>'approved' or role is not null)
);
create index accounts_pending on oneloss_access.accounts(status,requested_at);
create table oneloss_access.emergency_accounts (
 user_id uuid primary key references auth.users(id) on delete cascade
);
create table oneloss_access.franchises (
 code text primary key check(code=upper(btrim(code)) and length(code) between 1 and 32),
 label text not null,
 active boolean not null default true
);
create table oneloss_access.audit (
 id bigint generated always as identity primary key,
 actor uuid not null references auth.users(id),
 target uuid not null references auth.users(id),
 action text not null,
 previous jsonb not null,
 current jsonb not null,
 occurred_at timestamptz not null default now()
);
alter table oneloss_access.controls enable row level security;
alter table oneloss_access.accounts enable row level security;
alter table oneloss_access.emergency_accounts enable row level security;
alter table oneloss_access.franchises enable row level security;
alter table oneloss_access.audit enable row level security;
revoke all on all tables in schema oneloss_access from public,anon,authenticated;

-- Preserve current assigned employees/admins. Never infer approval from email.
insert into oneloss_access.accounts(user_id,status,role)
select u.id,
 case when a.user_id is not null or exists(select 1 from public.app_user_departments d where d.user_id=u.id)
      then 'approved' else 'pending' end,
 case when a.user_id is not null then 'admin'
      when exists(select 1 from public.app_user_departments d where d.user_id=u.id) then 'editor' end
from auth.users u left join public.app_admins a on a.user_id=u.id
where u.deleted_at is null;

-- Requested exception: Nathan's existing password recovery account only.
insert into oneloss_access.emergency_accounts(user_id)
select u.id from auth.users u join public.app_admins a on a.user_id=u.id
where lower(u.email)='nathan@servpro10100.com' and u.deleted_at is null;
do $$begin
 if (select count(*) from oneloss_access.emergency_accounts)<>1 then
  raise exception 'Exactly one existing Nathan administrator is required';
 end if;
end$$;
insert into oneloss_access.franchises(code,label)
select distinct upper(btrim(department)),
 case when upper(btrim(department))='IE' then 'Woodcrest / El Cerrito / Lake Mathews'
      else upper(btrim(department)) end
from public.app_user_departments where nullif(btrim(department),'') is not null;

create function oneloss_access.new_account() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 insert into oneloss_access.accounts(user_id) values(new.id) on conflict do nothing;
 return new;
end$$;
revoke all on function oneloss_access.new_account() from public,anon,authenticated;
create trigger oneloss_employee_pending after insert on auth.users
 for each row execute function oneloss_access.new_account();

create function oneloss_access.session_kind() returns text
language sql stable security definer set search_path='' as $$
 select case
 when auth.uid() is null then 'none'
 when exists(select 1 from jsonb_array_elements(case when jsonb_typeof(auth.jwt()->'amr')='array'
                    then auth.jwt()->'amr' else '[]'::jsonb end) x where x->>'method'='oauth')
      and exists(select 1 from auth.identities i where i.user_id=auth.uid() and i.provider='azure')
      then 'microsoft'
 when exists(select 1 from oneloss_access.emergency_accounts e where e.user_id=auth.uid())
      and exists(select 1 from jsonb_array_elements(case when jsonb_typeof(auth.jwt()->'amr')='array'
                    then auth.jwt()->'amr' else '[]'::jsonb end) x where x->>'method'='password')
      then 'emergency'
 when not (select microsoft_only from oneloss_access.controls where singleton) then 'legacy'
 else 'none' end
$$;
revoke all on function oneloss_access.session_kind() from public,anon;
grant execute on function oneloss_access.session_kind() to authenticated;

create function oneloss_access.can_read() returns boolean
language sql stable security definer set search_path='' as $$
 select coalesce(exists(select 1 from oneloss_access.accounts a
  where a.user_id=auth.uid() and a.status='approved' and oneloss_access.session_kind()<>'none'
    and ((a.role='admin' and exists(select 1 from public.app_admins x where x.user_id=a.user_id))
      or (a.role in ('viewer','editor') and exists(select 1 from public.app_user_departments d where d.user_id=a.user_id)))),false)
$$;
create function oneloss_access.can_write() returns boolean
language sql stable security definer set search_path='' as $$
 select oneloss_access.can_read() and exists(select 1 from oneloss_access.accounts
   where user_id=auth.uid() and role in ('admin','editor'))
$$;
create function oneloss_access.is_admin() returns boolean
language sql stable security definer set search_path='' as $$
 select oneloss_access.can_read() and exists(select 1 from oneloss_access.accounts a
   join public.app_admins x using(user_id) where a.user_id=auth.uid() and a.role='admin')
$$;
revoke all on function oneloss_access.can_read(),oneloss_access.can_write(),oneloss_access.is_admin() from public,anon;
grant execute on function oneloss_access.can_read(),oneloss_access.can_write(),oneloss_access.is_admin() to authenticated;

create function oneloss_access.snapshot() returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare a oneloss_access.accounts; kind text; allowed boolean; depts jsonb;
begin
 if auth.uid() is null then return jsonb_build_object('access_state','signed_out','is_admin',false,'departments','[]'::jsonb); end if;
 select * into a from oneloss_access.accounts where user_id=auth.uid();
 kind:=oneloss_access.session_kind(); allowed:=oneloss_access.can_read();
 select coalesce(jsonb_agg(department order by department),'[]'::jsonb) into depts
 from public.app_user_departments where user_id=auth.uid() and allowed;
 return jsonb_build_object('approval_enabled',true,'approval_status',coalesce(a.status,'pending'),
  'access_state',case when coalesce(a.status,'pending')<>'approved' then coalesce(a.status,'pending')
                     when kind='none' then 'microsoft_required'
                     when not allowed then 'unassigned' else 'approved' end,
  'auth_mode',kind,'role',case when allowed then a.role end,
  'can_edit',oneloss_access.can_write(),'is_admin',oneloss_access.is_admin(),
  'departments',depts);
end$$;
revoke all on function oneloss_access.snapshot() from public,anon;
grant execute on function oneloss_access.snapshot() to authenticated;

create or replace function public.my_app_access() returns jsonb
language sql stable security invoker set search_path='' as $$select oneloss_access.snapshot()$$;
create or replace function public.is_app_admin() returns boolean
language sql stable security invoker set search_path='' as $$select oneloss_access.is_admin()$$;
create or replace function public.my_departments() returns setof text
language sql stable security invoker set search_path='' as $$
 select department from public.app_user_departments
 where user_id=auth.uid() and (select oneloss_access.can_read())
$$;
revoke all on function public.my_app_access(),public.is_app_admin(),public.my_departments() from public,anon;
grant execute on function public.my_app_access(),public.is_app_admin(),public.my_departments() to authenticated;

create function oneloss_access.admin_snapshot() returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare result jsonb;
begin
 if not oneloss_access.is_admin() then raise exception 'Administrator access required' using errcode='42501'; end if;
 select jsonb_build_object(
  'users',coalesce((select jsonb_agg(jsonb_build_object('user_id',u.id,'email',u.email,
    'name',coalesce(u.raw_user_meta_data->>'display_name',''),
    'status',coalesce(a.status,'pending'),'role',a.role,'revision',coalesce(a.revision,0),
    'requested_at',coalesce(a.requested_at,u.created_at),
    'emergency',exists(select 1 from oneloss_access.emergency_accounts e where e.user_id=u.id),
    'departments',coalesce((select jsonb_agg(d.department order by d.department)
      from public.app_user_departments d where d.user_id=u.id),'[]'::jsonb))
    order by case when coalesce(a.status,'pending')='pending' then 0 else 1 end,lower(u.email))
    from auth.users u left join oneloss_access.accounts a on a.user_id=u.id where u.deleted_at is null),'[]'::jsonb),
  'franchises',coalesce((select jsonb_agg(jsonb_build_object('code',code,'label',label) order by label)
    from oneloss_access.franchises where active),'[]'::jsonb)) into result;
 return result;
end$$;
revoke all on function oneloss_access.admin_snapshot() from public,anon;
grant execute on function oneloss_access.admin_snapshot() to authenticated;
create function public.employee_admin_snapshot() returns jsonb
language sql stable security invoker set search_path='' as $$select oneloss_access.admin_snapshot()$$;
revoke all on function public.employee_admin_snapshot() from public,anon;
grant execute on function public.employee_admin_snapshot() to authenticated;

create function oneloss_access.decide(p_user_id uuid,p_action text,p_role text,p_departments text[],p_revision bigint)
returns jsonb language plpgsql security definer set search_path='' as $$
declare a oneloss_access.accounts; previous jsonb; cleaned text[]; state text; next_role text;
begin
 -- Serialize administrative changes, including concurrent last-admin decisions.
 perform pg_advisory_xact_lock(19632026,19112026);
 if not oneloss_access.is_admin() then raise exception 'Administrator access required' using errcode='42501'; end if;
 if p_action not in ('approve','reject','suspend') or p_action is null then raise exception 'Invalid decision' using errcode='22023'; end if;
 if not exists(select 1 from auth.users where id=p_user_id and deleted_at is null
    and email_confirmed_at is not null and coalesce(banned_until<now(),true)) then
  raise exception 'User is unavailable or unverified' using errcode='22023';
 end if;
 insert into oneloss_access.accounts(user_id) values(p_user_id) on conflict do nothing;
 select * into a from oneloss_access.accounts where user_id=p_user_id for update;
 if p_revision is null or a.revision<>p_revision then raise exception 'Account changed; reload before saving' using errcode='40001'; end if;
 previous:=jsonb_build_object('status',a.status,'role',a.role,'departments',
  (select coalesce(jsonb_agg(department order by department),'[]'::jsonb) from public.app_user_departments where user_id=p_user_id));
 state:=case p_action when 'approve' then 'approved' when 'reject' then 'rejected' else 'suspended' end;
 if p_action='approve' then
  if p_role is null or p_role not in ('viewer','editor','admin') then raise exception 'Choose a role' using errcode='22023'; end if;
  select coalesce(array_agg(distinct upper(btrim(x)) order by upper(btrim(x))),'{}'::text[])
    into cleaned from unnest(coalesce(p_departments,'{}'::text[])) x where nullif(btrim(x),'') is not null;
  if cardinality(cleaned)=0 or exists(select 1 from unnest(cleaned) x
     where not exists(select 1 from oneloss_access.franchises f where f.code=x and f.active)) then
   raise exception 'Choose at least one available franchise' using errcode='22023';
  end if;
  if a.status<>'approved' and not exists(select 1 from auth.identities where user_id=p_user_id and provider='azure') then
   raise exception 'User must sign in with Microsoft first' using errcode='22023';
  end if;
  next_role:=p_role;
 else cleaned:='{}'::text[]; next_role:=null;
 end if;
 if p_user_id=auth.uid() and (state<>'approved' or next_role<>'admin') then
  raise exception 'You cannot remove your own administrator access' using errcode='42501';
 end if;
 if exists(select 1 from oneloss_access.emergency_accounts where user_id=p_user_id)
    and (state<>'approved' or next_role<>'admin') then
  raise exception 'Recovery administrator access must be preserved' using errcode='42501';
 end if;
 if a.status='approved' and a.role='admin' and (state<>'approved' or next_role<>'admin')
    and (select count(*) from oneloss_access.accounts where status='approved' and role='admin')<=1 then
  raise exception 'The last administrator cannot be removed' using errcode='42501';
 end if;
 delete from public.app_user_departments where user_id=p_user_id;
 insert into public.app_user_departments(user_id,department) select p_user_id,x from unnest(cleaned) x;
 if state='approved' and next_role='admin' then
  insert into public.app_admins(user_id) values(p_user_id) on conflict do nothing;
 else delete from public.app_admins where user_id=p_user_id; end if;
 update oneloss_access.accounts set status=state,role=next_role,revision=revision+1,
   reviewed_at=now(),reviewed_by=auth.uid() where user_id=p_user_id;
 insert into oneloss_access.audit(actor,target,action,previous,current)
 values(auth.uid(),p_user_id,p_action,previous,jsonb_build_object('status',state,'role',next_role,'departments',to_jsonb(cleaned)));
 return jsonb_build_object('ok',true,'revision',a.revision+1);
end$$;
revoke all on function oneloss_access.decide(uuid,text,text,text[],bigint) from public,anon;
grant execute on function oneloss_access.decide(uuid,text,text,text[],bigint) to authenticated;
create function public.employee_decide_user(p_user_id uuid,p_action text,p_role text,p_departments text[],p_revision bigint)
returns jsonb language sql security invoker set search_path='' as $$
 select oneloss_access.decide(p_user_id,p_action,p_role,p_departments,p_revision)
$$;
revoke all on function public.employee_decide_user(uuid,text,text,text[],bigint) from public,anon;
grant execute on function public.employee_decide_user(uuid,text,text,text[],bigint) to authenticated;

-- Add restrictive boundaries; existing franchise/object policies still apply.
do $$declare t record; begin
 for t in select n.nspname,c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace
   where n.nspname in ('public','storage','realtime') and c.relkind in ('r','p')
 loop
  execute format('alter table %I.%I enable row level security',t.nspname,t.relname);
  execute format('create policy employee_read_boundary on %I.%I as restrictive for select to authenticated using ((select oneloss_access.can_read()))',t.nspname,t.relname);
  execute format('create policy employee_insert_boundary on %I.%I as restrictive for insert to authenticated with check ((select oneloss_access.can_write()))',t.nspname,t.relname);
  execute format('create policy employee_update_boundary on %I.%I as restrictive for update to authenticated using ((select oneloss_access.can_write())) with check ((select oneloss_access.can_write()))',t.nspname,t.relname);
  execute format('create policy employee_delete_boundary on %I.%I as restrictive for delete to authenticated using ((select oneloss_access.can_write()))',t.nspname,t.relname);
 end loop;
end$$;

-- This guard also covers views and SECURITY DEFINER RPCs that bypass table RLS.
create function oneloss_access.pre_request() returns void
language plpgsql security definer set search_path='' as $$
declare path text:=coalesce(current_setting('request.path',true),'');
 method text:=coalesce(current_setting('request.method',true),''); name text;
begin
 if auth.jwt()->>'role'='service_role' then return; end if;
 if auth.uid() is not null and path='/rpc/my_app_access' then return; end if;
 if not oneloss_access.can_read() then raise exception 'OneLoss approval or Microsoft sign-in required' using errcode='42501'; end if;
 if not oneloss_access.can_write() and method not in ('GET','HEAD') then
  if path like '/rpc/%' then
   name:=substr(path,6);
   -- STABLE/IMMUTABLE RPCs execute in a READ ONLY PostgREST transaction.
   if exists(select 1 from pg_proc p join pg_namespace n on n.oid=p.pronamespace
        where n.nspname='public' and p.proname=name and p.prokind='f')
      and not exists(select 1 from pg_proc p join pg_namespace n on n.oid=p.pronamespace
        where n.nspname='public' and p.proname=name and p.prokind='f' and p.provolatile='v') then return; end if;
  end if;
  raise exception 'This account has read-only access' using errcode='42501';
 end if;
end$$;
revoke all on function oneloss_access.pre_request() from public;
grant usage on schema oneloss_access to anon;
grant execute on function oneloss_access.pre_request() to authenticated,anon,service_role;
alter role authenticator set pgrst.db_pre_request='oneloss_access.pre_request';

create function oneloss_access.before_user_created(event jsonb) returns jsonb
language sql security invoker set search_path='' as $$
 select case when event->'user'->'app_metadata'->>'provider'='azure'
 then '{}'::jsonb else jsonb_build_object('error',jsonb_build_object('http_code',403,
 'message','Use your company Microsoft account to join OneLoss.')) end
$$;
create function oneloss_access.password_verification(event jsonb) returns jsonb
language sql security invoker set search_path='' as $$
 select case when coalesce((event->>'valid')::boolean,false)=false
   or exists(select 1 from oneloss_access.emergency_accounts e where e.user_id=(event->>'user_id')::uuid)
 then jsonb_build_object('decision','continue')
 else jsonb_build_object('decision','reject','message','Use Microsoft to sign in to OneLoss.','should_logout_user',false) end
$$;
revoke all on function oneloss_access.before_user_created(jsonb),oneloss_access.password_verification(jsonb) from public,anon,authenticated;
grant execute on function oneloss_access.before_user_created(jsonb),oneloss_access.password_verification(jsonb) to supabase_auth_admin;
grant select on oneloss_access.emergency_accounts to supabase_auth_admin;
create policy auth_recovery_lookup on oneloss_access.emergency_accounts for select to supabase_auth_admin using(true);

notify pgrst,'reload schema';
notify pgrst,'reload config';
commit;
