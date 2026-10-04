begin;

create table if not exists public.job_note_templates (
  template_id uuid primary key default gen_random_uuid(),
  department text not null,
  name text not null,
  division text not null default 'Any'
    check (division in ('Any', 'EMS', 'Contents', 'Recon')),
  body text not null,
  active boolean not null default true,
  sort_order integer not null default 100,
  created_by uuid default auth.uid() references auth.users(id) on delete set null,
  updated_by uuid default auth.uid() references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (length(btrim(department)) between 1 and 32),
  check (length(btrim(name)) between 1 and 120),
  check (length(btrim(body)) between 1 and 10000)
);

create unique index if not exists job_note_templates_department_name_uq
  on public.job_note_templates (upper(department), lower(name));

alter table public.job_note_templates enable row level security;

create policy job_note_templates_read on public.job_note_templates
  for select to authenticated
  using (public.is_app_admin() or upper(department) in
    (select upper(d) from public.my_departments() d));

create policy job_note_templates_admin_insert on public.job_note_templates
  for insert to authenticated with check (public.is_app_admin());
create policy job_note_templates_admin_update on public.job_note_templates
  for update to authenticated using (public.is_app_admin())
  with check (public.is_app_admin());
create policy job_note_templates_admin_delete on public.job_note_templates
  for delete to authenticated using (public.is_app_admin());

revoke all on table public.job_note_templates from public, anon;
grant select, insert, update, delete on table public.job_note_templates to authenticated;

commit;
