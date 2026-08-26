-- Linguar Hub: server-enforced admins and per-user franchise assignments.
-- Initial administrator requested by the owner: nathan@servpro10100.com

create table if not exists app_admins (
    user_id uuid primary key references auth.users(id) on delete cascade,
    created_at timestamptz not null default now()
);

insert into app_admins (user_id)
select id from auth.users
where lower(email) = 'nathan@servpro10100.com'
on conflict do nothing;

alter table app_admins enable row level security;

create or replace function is_app_admin()
returns boolean
language sql stable security definer
set search_path = public, auth
as $$
  select exists(select 1 from public.app_admins where user_id = auth.uid())
$$;

create or replace function my_app_access()
returns jsonb
language sql stable security definer
set search_path = public, auth
as $$
  select jsonb_build_object(
    'is_admin', public.is_app_admin(),
    'departments', coalesce((
      select jsonb_agg(department order by department)
      from public.app_user_departments where user_id = auth.uid()
    ), '[]'::jsonb)
  )
$$;

create or replace function admin_list_user_access()
returns table(user_id uuid, email text, departments text[], is_admin boolean)
language plpgsql stable security definer
set search_path = public, auth
as $$
begin
  if not public.is_app_admin() then
    raise exception 'administrator access required' using errcode = '42501';
  end if;
  return query
  select u.id, u.email::text,
         coalesce(array_agg(d.department order by d.department)
           filter (where d.department is not null), '{}'::text[]),
         exists(select 1 from public.app_admins a where a.user_id = u.id)
  from auth.users u
  left join public.app_user_departments d on d.user_id = u.id
  group by u.id, u.email
  order by lower(u.email);
end
$$;

create or replace function admin_set_user_departments(
    p_user_id uuid, p_departments text[])
returns text[]
language plpgsql security definer
set search_path = public, auth
as $$
declare cleaned text[];
begin
  if not public.is_app_admin() then
    raise exception 'administrator access required' using errcode = '42501';
  end if;
  if not exists(select 1 from auth.users where id = p_user_id) then
    raise exception 'unknown user' using errcode = '22023';
  end if;
  select coalesce(array_agg(distinct upper(trim(v))), '{}'::text[])
    into cleaned from unnest(coalesce(p_departments, '{}'::text[])) v
    where trim(v) <> '';
  delete from public.app_user_departments where user_id = p_user_id;
  insert into public.app_user_departments(user_id, department)
    select p_user_id, v from unnest(cleaned) v on conflict do nothing;
  return cleaned;
end
$$;

revoke all on function is_app_admin() from public;
revoke all on function my_app_access() from public;
revoke all on function admin_list_user_access() from public;
revoke all on function admin_set_user_departments(uuid, text[]) from public;
grant execute on function is_app_admin() to authenticated;
grant execute on function my_app_access() to authenticated;
grant execute on function admin_list_user_access() to authenticated;
grant execute on function admin_set_user_departments(uuid, text[]) to authenticated;

drop policy if exists own_admin_status on app_admins;
create policy own_admin_status on app_admins for select to authenticated
using (user_id = auth.uid());
