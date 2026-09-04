-- Per-user external account connections. OAuth credentials are encrypted by
-- the Edge Function before they reach Postgres; clients can only read their
-- non-secret connection status.
create table if not exists public.external_oauth_credentials (
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null check (provider in ('companycam')),
  department text not null check (department ~ '^[A-Z0-9_-]{1,20}$'),
  access_token_cipher text not null,
  access_token_iv text not null,
  refresh_token_cipher text not null default '',
  refresh_token_iv text not null default '',
  expires_at timestamptz,
  scopes text[] not null default '{}'::text[],
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, provider, department)
);

alter table public.external_oauth_credentials enable row level security;
revoke all on table public.external_oauth_credentials from public, anon, authenticated;
grant select, insert, update, delete on table public.external_oauth_credentials to service_role;

create table if not exists public.external_connection_status (
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null check (provider in ('companycam')),
  department text not null check (department ~ '^[A-Z0-9_-]{1,20}$'),
  status text not null default 'connected' check (status in ('connected', 'expired', 'revoked', 'error')),
  external_account_id text not null default '',
  external_email text not null default '',
  display_name text not null default '',
  scopes text[] not null default '{}'::text[],
  connected_at timestamptz not null default now(),
  last_used_at timestamptz,
  updated_at timestamptz not null default now(),
  primary key (user_id, provider, department)
);

alter table public.external_connection_status enable row level security;
revoke all on table public.external_connection_status from public, anon;
grant select on table public.external_connection_status to authenticated;
grant select, insert, update, delete on table public.external_connection_status to service_role;

drop policy if exists "Users read their own external connection status"
  on public.external_connection_status;
create policy "Users read their own external connection status"
  on public.external_connection_status
  for select
  to authenticated
  using ((select auth.uid()) = user_id);

create index if not exists external_connection_status_user_provider_idx
  on public.external_connection_status (user_id, provider, department);

comment on table public.external_oauth_credentials is
  'Server-only AES-GCM encrypted OAuth credentials. No client role has access.';
comment on table public.external_connection_status is
  'Non-secret per-user connection metadata readable only by its owner through RLS.';
