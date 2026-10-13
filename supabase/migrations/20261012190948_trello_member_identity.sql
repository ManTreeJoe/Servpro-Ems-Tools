-- Explicitly confirmed identities only. No membership or notification side effects.
create table oneloss_notifications.trello_accounts (
  trello_member_id text primary key check (trello_member_id ~ '^[0-9a-f]{24}$'),
  user_id uuid not null unique references auth.users(id) on delete cascade,
  trello_username text not null,
  confirmed_at timestamptz not null default now(),
  confirmation_note text not null
);
alter table oneloss_notifications.trello_accounts enable row level security;
revoke all on oneloss_notifications.trello_accounts from public, anon, authenticated;
comment on table oneloss_notifications.trello_accounts is
  'Admin-confirmed Trello identity mappings. Not an access grant. No client writes; no membership sync trigger.';
