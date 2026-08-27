-- Linguar Hub — schema v11: application-owned Pipeline.
--
-- Trello remains an external source during the transition, but these tables
-- are the durable board model used by Linguar Hub.  Imported rows retain the
-- Trello IDs needed for two-way synchronization.  Native cards can later use
-- source='linguar' with no external_id at all.

create extension if not exists pgcrypto;

-- Client is the permanent head of the restoration record.  Claims, jobs,
-- division work, cards and activity all hang beneath it.  This avoids the
-- Trello-era mistake of treating a card title as the identity of a person.
create table if not exists crm_clients (
  client_id        uuid primary key default gen_random_uuid(),
  display_name     text not null,
  client_type      text not null default 'individual',
  department       text,
  email            text,
  phone            text,
  address_json     jsonb not null default '{}'::jsonb,
  active           boolean not null default true,
  created_at       text not null,
  updated_at       text not null
);
create index if not exists idx_crm_clients_name on crm_clients(display_name);
create index if not exists idx_crm_clients_department on crm_clients(department);

create table if not exists crm_claims (
  claim_id         uuid primary key default gen_random_uuid(),
  client_id        uuid not null references crm_clients(client_id)
                   on delete cascade,
  claim_number     text,
  carrier          text,
  loss_type        text,
  loss_date        text,
  date_received    text,
  status           text not null default 'open',
  created_at       text not null,
  updated_at       text not null
);
create index if not exists idx_crm_claims_client on crm_claims(client_id);
create index if not exists idx_crm_claims_number on crm_claims(claim_number);

alter table jobs add column if not exists client_id uuid
  references crm_clients(client_id) on delete set null;
alter table jobs add column if not exists claim_id uuid
  references crm_claims(claim_id) on delete set null;
create index if not exists idx_jobs_client_id on jobs(client_id);
create index if not exists idx_jobs_claim_id on jobs(claim_id);

create table if not exists crm_pipeline_boards (
  board_key       text primary key,
  name            text not null,
  position        integer not null default 0,
  source          text not null default 'linguar',
  external_id     text,
  sync_status     text not null default 'local',
  sync_error      text,
  synced_at       text,
  updated_at      text not null
);
create unique index if not exists idx_pipeline_boards_external
  on crm_pipeline_boards(external_id) where external_id is not null;

create table if not exists crm_pipeline_lanes (
  lane_key        text primary key,
  board_key       text not null references crm_pipeline_boards(board_key)
                  on delete cascade,
  name            text not null,
  position        integer not null default 0,
  source          text not null default 'linguar',
  external_id     text,
  archived        boolean not null default false,
  updated_at      text not null
);
create index if not exists idx_pipeline_lanes_board
  on crm_pipeline_lanes(board_key, position);
create unique index if not exists idx_pipeline_lanes_external
  on crm_pipeline_lanes(external_id) where external_id is not null;

create table if not exists crm_pipeline_cards (
  card_key        text primary key,
  card_id         uuid not null default gen_random_uuid(),
  job_id          uuid references jobs(job_id) on delete set null,
  client_id       uuid references crm_clients(client_id) on delete set null,
  claim_id        uuid references crm_claims(claim_id) on delete set null,
  board_key       text not null references crm_pipeline_boards(board_key),
  lane_key        text not null references crm_pipeline_lanes(lane_key),
  title           text not null,
  description     text,
  position        numeric not null default 0,
  source          text not null default 'linguar',
  external_id     text,
  external_url    text,
  labels_json     jsonb not null default '[]'::jsonb,
  checklist_json  jsonb not null default '{}'::jsonb,
  due_at          text,
  due_complete    boolean not null default false,
  last_activity_at text,
  sync_status     text not null default 'local',
  sync_error      text,
  synced_at       text,
  archived        boolean not null default false,
  created_at      text not null,
  updated_at      text not null,
  unique(card_id)
);
create index if not exists idx_pipeline_cards_lane
  on crm_pipeline_cards(lane_key, position);
create index if not exists idx_pipeline_cards_job on crm_pipeline_cards(job_id);
create index if not exists idx_pipeline_cards_client on crm_pipeline_cards(client_id);
create index if not exists idx_pipeline_cards_claim on crm_pipeline_cards(claim_id);
create unique index if not exists idx_pipeline_cards_external
  on crm_pipeline_cards(external_id) where external_id is not null;

create table if not exists crm_pipeline_activity (
  activity_key    text primary key,
  card_key        text not null references crm_pipeline_cards(card_key)
                  on delete cascade,
  action_type     text not null,
  body            text,
  actor_name      text,
  happened_at     text not null,
  source          text not null default 'linguar',
  external_id     text,
  metadata_json   jsonb not null default '{}'::jsonb,
  created_at      text not null
);
create index if not exists idx_pipeline_activity_card
  on crm_pipeline_activity(card_key, happened_at desc);
create unique index if not exists idx_pipeline_activity_external
  on crm_pipeline_activity(external_id) where external_id is not null;

alter table crm_clients enable row level security;
alter table crm_claims enable row level security;
alter table crm_pipeline_boards enable row level security;
alter table crm_pipeline_lanes enable row level security;
alter table crm_pipeline_cards enable row level security;
alter table crm_pipeline_activity enable row level security;

drop policy if exists crm_clients_rw on crm_clients;
create policy crm_clients_rw on crm_clients
  for all to authenticated
  using (department is null or department in (select my_departments()))
  with check (department is null or department in (select my_departments()));
drop policy if exists crm_claims_rw on crm_claims;
create policy crm_claims_rw on crm_claims
  for all to authenticated
  using (exists (select 1 from crm_clients c where c.client_id = crm_claims.client_id))
  with check (exists (select 1 from crm_clients c where c.client_id = crm_claims.client_id));

drop policy if exists crm_pipeline_boards_rw on crm_pipeline_boards;
create policy crm_pipeline_boards_rw on crm_pipeline_boards
  for all to authenticated using (true) with check (true);
drop policy if exists crm_pipeline_lanes_rw on crm_pipeline_lanes;
create policy crm_pipeline_lanes_rw on crm_pipeline_lanes
  for all to authenticated using (true) with check (true);
drop policy if exists crm_pipeline_cards_rw on crm_pipeline_cards;
create policy crm_pipeline_cards_rw on crm_pipeline_cards
  for all to authenticated using (true) with check (true);
drop policy if exists crm_pipeline_activity_rw on crm_pipeline_activity;
create policy crm_pipeline_activity_rw on crm_pipeline_activity
  for all to authenticated using (true) with check (true);

update meta set value = '11' where key = 'schema_version';
insert into meta (key, value) values ('schema_version', '11')
  on conflict (key) do update set value = excluded.value;
