-- Linguar Hub — RLS security baseline.
-- Safe for Main: this closes unauthenticated privilege paths without changing
-- which signed-in franchise users can currently see legacy unclassified jobs.

begin;

-- Supabase grants schema objects to API roles by default. RLS already denies
-- anon rows, but removing the table grant makes the signed-out boundary
-- explicit and defense-in-depth.
revoke all privileges on all tables in schema public from anon;
alter default privileges in schema public revoke all on tables from anon;
alter default privileges in schema public revoke execute on functions from public;
alter default privileges in schema public revoke execute on functions from anon;

-- Read-only identity helpers do not need owner privileges. Qualifying every
-- object lets them use an empty search_path and avoids object-shadowing.
create or replace function public.my_departments()
returns setof text
language sql
stable
security invoker
set search_path = ''
as $$
  select department
  from public.app_user_departments
  where user_id = (select auth.uid())
$$;

create or replace function public.is_app_admin()
returns boolean
language sql
stable
security invoker
set search_path = ''
as $$
  select exists(
    select 1
    from public.app_admins
    where user_id = (select auth.uid())
  )
$$;

create or replace function public.my_app_access()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
  select jsonb_build_object(
    'is_admin', public.is_app_admin(),
    'departments', coalesce((
      select jsonb_agg(department order by department)
      from public.app_user_departments
      where user_id = (select auth.uid())
    ), '[]'::jsonb)
  )
$$;

-- These two RPCs intentionally remain SECURITY DEFINER: their bodies verify
-- is_app_admin() before reading auth.users or changing another user's access.
-- They are available only after sign-in.
alter function public.admin_list_user_access() set search_path = '';
alter function public.admin_set_user_departments(uuid, text[]) set search_path = '';

revoke execute on function public.admin_list_user_access() from public, anon;
revoke execute on function public.admin_set_user_departments(uuid, text[]) from public, anon;
revoke execute on function public.is_app_admin() from public, anon;
revoke execute on function public.my_app_access() from public, anon;
revoke execute on function public.my_departments() from public, anon;
revoke execute on function public.rls_auto_enable() from public, anon;

grant execute on function public.admin_list_user_access() to authenticated;
grant execute on function public.admin_set_user_departments(uuid, text[]) to authenticated;
grant execute on function public.is_app_admin() to authenticated;
grant execute on function public.my_app_access() to authenticated;
grant execute on function public.my_departments() to authenticated;
revoke execute on function public.rls_auto_enable() from authenticated;

-- Cache auth.uid() once per statement rather than recalculating it per row.
drop policy if exists own_departments on public.app_user_departments;
create policy own_departments on public.app_user_departments
  for select to authenticated
  using (user_id = (select auth.uid()));

drop policy if exists own_admin_status on public.app_admins;
create policy own_admin_status on public.app_admins
  for select to authenticated
  using (user_id = (select auth.uid()));

-- Cover the second side of the job relationship graph.
create index if not exists idx_crm_job_relationships_related_job
  on public.crm_job_relationships (related_job_id);

commit;
