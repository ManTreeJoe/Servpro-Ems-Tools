-- Per-user product capabilities. Staged for review; apply before enabling the
-- corresponding Settings controls in a release.

begin;

create table if not exists public.app_user_capabilities (
  user_id uuid not null references auth.users(id) on delete cascade,
  capability text not null check (capability ~ '^[a-z][a-z0-9_]{1,63}$'),
  enabled boolean not null default true,
  updated_at timestamptz not null default now(),
  updated_by uuid references auth.users(id) on delete set null,
  primary key (user_id, capability)
);

alter table public.app_user_capabilities enable row level security;
revoke all on public.app_user_capabilities from public, anon;
grant select on public.app_user_capabilities to authenticated;

drop policy if exists own_capabilities on public.app_user_capabilities;
create policy own_capabilities on public.app_user_capabilities
  for select to authenticated
  using (user_id = (select auth.uid()));

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
    ), '[]'::jsonb),
    'capabilities', coalesce((
      select jsonb_object_agg(capability, enabled order by capability)
      from public.app_user_capabilities
      where user_id = (select auth.uid())
    ), '{}'::jsonb)
  )
$$;

create or replace function public.admin_list_user_access_v2()
returns table(user_id uuid, email text, departments text[], is_admin boolean,
              capabilities jsonb)
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
  if not public.is_app_admin() then
    raise exception 'administrator access required' using errcode = '42501';
  end if;
  return query
  select u.id, u.email::text,
         coalesce((select array_agg(d.department order by d.department)
                   from public.app_user_departments d
                   where d.user_id = u.id), '{}'::text[]),
         exists(select 1 from public.app_admins a where a.user_id = u.id),
         coalesce((select jsonb_object_agg(c.capability, c.enabled order by c.capability)
                   from public.app_user_capabilities c
                   where c.user_id = u.id), '{}'::jsonb)
  from auth.users u
  order by lower(u.email);
end
$$;

create or replace function public.admin_set_user_capabilities(
    p_user_id uuid, p_capabilities jsonb)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare result jsonb;
begin
  if not public.is_app_admin() then
    raise exception 'administrator access required' using errcode = '42501';
  end if;
  if not exists(select 1 from auth.users where id = p_user_id) then
    raise exception 'unknown user' using errcode = '22023';
  end if;
  if jsonb_typeof(coalesce(p_capabilities, '{}'::jsonb)) <> 'object' then
    raise exception 'capabilities must be an object' using errcode = '22023';
  end if;

  delete from public.app_user_capabilities where user_id = p_user_id;
  insert into public.app_user_capabilities
      (user_id, capability, enabled, updated_by)
  select p_user_id, item.key, (item.value)::boolean, (select auth.uid())
  from jsonb_each_text(coalesce(p_capabilities, '{}'::jsonb)) item
  where item.key in ('docusketch');

  select coalesce(jsonb_object_agg(capability, enabled order by capability),
                  '{}'::jsonb)
    into result
  from public.app_user_capabilities where user_id = p_user_id;
  return result;
end
$$;

revoke execute on function public.admin_list_user_access_v2() from public, anon;
revoke execute on function public.admin_set_user_capabilities(uuid, jsonb) from public, anon;
grant execute on function public.admin_list_user_access_v2() to authenticated;
grant execute on function public.admin_set_user_capabilities(uuid, jsonb) to authenticated;

commit;
