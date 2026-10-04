-- Admin-managed requirement defaults for payer, carrier/client, loss type,
-- and division. Jobs store an applied snapshot; these rows remain reusable
-- definitions and never rewrite work already underway.
begin;

create table if not exists public.job_profiles (
  profile_id uuid primary key default gen_random_uuid(),
  department text not null,
  name text not null,
  payer_type text not null default 'any'
    check (payer_type in ('any', 'insurance', 'self_pay', 'commercial', 'management')),
  carrier_or_client text,
  loss_type text,
  division text not null default 'Any'
    check (division in ('Any', 'EMS', 'Contents', 'Recon')),
  required_items jsonb not null default '[]'::jsonb
    check (jsonb_typeof(required_items) = 'array'),
  active boolean not null default true,
  source_profile_id uuid references public.job_profiles(profile_id) on delete set null,
  created_by uuid default auth.uid() references auth.users(id) on delete set null,
  updated_by uuid default auth.uid() references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (length(btrim(department)) between 1 and 32),
  check (length(btrim(name)) between 1 and 120)
);

create unique index if not exists job_profiles_department_name_uq
  on public.job_profiles (upper(department), lower(name));
create index if not exists job_profiles_match_idx
  on public.job_profiles (upper(department), active, payer_type, division);

alter table public.job_profiles enable row level security;

drop policy if exists job_profiles_read on public.job_profiles;
create policy job_profiles_read on public.job_profiles
  for select to authenticated
  using (
    public.is_app_admin()
    or upper(department) in (select upper(d) from public.my_departments() d)
  );

drop policy if exists job_profiles_admin_insert on public.job_profiles;
create policy job_profiles_admin_insert on public.job_profiles
  for insert to authenticated
  with check (public.is_app_admin());

drop policy if exists job_profiles_admin_update on public.job_profiles;
create policy job_profiles_admin_update on public.job_profiles
  for update to authenticated
  using (public.is_app_admin())
  with check (public.is_app_admin());

drop policy if exists job_profiles_admin_delete on public.job_profiles;
create policy job_profiles_admin_delete on public.job_profiles
  for delete to authenticated
  using (public.is_app_admin());

revoke all on table public.job_profiles from public, anon;
grant select, insert, update, delete on table public.job_profiles to authenticated;

commit;
