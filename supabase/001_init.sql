-- Linguar Hub — shared job index, schema v3.
--
-- Faithful port of ems_db.py's SQLite schema. Deliberately NOT a redesign:
-- the CRM property→claim→job model is a later, separate migration. Changing
-- the shape and the backend at the same time would make the conformance
-- tests (same suite, both backends) prove nothing.
--
-- Run once in the Supabase SQL editor. Idempotent — safe to re-run.
--
-- Dates stay TEXT (ISO-8601), matching SQLite, so rows round-trip byte-for-
-- byte between backends during the dual-write comparison. Converting to
-- timestamptz is a follow-up once the two backends are proven equivalent.

-- ── Core job graph ─────────────────────────────────────────────────────

create table if not exists jobs (
    canon_key       text primary key,
    display_name    text not null,
    claim_number    text,
    carrier         text,
    loss_type       text,
    year            integer,
    status          text,
    date_received   text,
    first_seen_at   text,
    last_seen_at    text,
    metadata_json   text,
    parent_canon    text,
    unit_number     text,
    department      text          -- NULL = unknown, and unknown is permissive
);
create index if not exists idx_jobs_parent on jobs (parent_canon);
create index if not exists idx_jobs_department on jobs (department);

create table if not exists job_aliases (
    canon_key   text not null references jobs (canon_key) on delete cascade,
    alias       text not null,
    alias_canon text not null,
    source      text,
    added_at    text,
    primary key (canon_key, alias_canon)
);
create index if not exists idx_aliases_canon on job_aliases (alias_canon);

create table if not exists job_links (
    canon_key     text not null references jobs (canon_key) on delete cascade,
    link_type     text not null,
    link_value    text not null,
    added_at      text,
    added_by      text,
    metadata_json text,
    primary key (canon_key, link_type, link_value)
);
create index if not exists idx_links_key on job_links (canon_key);
-- Reverse lookup (find_job_by_link) is a hot path on the remote backend:
-- it is how a folder/card proves identity. Indexed here, unlike SQLite,
-- where the table is small enough that a scan was free.
create index if not exists idx_links_value on job_links (link_type, link_value);

create table if not exists job_events (
    id           bigint generated always as identity primary key,
    canon_key    text not null references jobs (canon_key) on delete cascade,
    event_type   text not null,
    event_at     text not null,
    payload_json text,
    actor        text          -- new: multi-user needs to know who
);
create index if not exists idx_events_key on job_events (canon_key);

-- ── Pipeline / lifecycle (projection of Trello) ────────────────────────

create table if not exists job_lifecycle (
    card_id            text primary key,
    client_canon       text,
    client_display     text,
    board_id           text,
    board_name         text,
    list_id            text,
    list_name          text,
    current_stage      text,
    stage_entered_at   text,
    created_at         text,
    last_activity_at   text,
    billed_at          text,
    paid_at            text,
    card_url           text,
    owner              text,
    updated_at         text,
    actions_synced_at  text
);
create index if not exists idx_lifecycle_stage on job_lifecycle (current_stage);
create index if not exists idx_lifecycle_client on job_lifecycle (client_canon);

create table if not exists job_stage_transitions (
    id                 bigint generated always as identity primary key,
    card_id            text not null,
    client_canon       text,
    from_stage         text,
    to_stage           text not null,
    transitioned_at    text not null,
    days_in_from_stage integer
);
create index if not exists idx_transitions_card on job_stage_transitions (card_id);
create index if not exists idx_transitions_from on job_stage_transitions (from_stage);

create table if not exists meta (
    key   text primary key,
    value text
);
insert into meta (key, value) values ('schema_version', '3')
    on conflict (key) do update set value = excluded.value;

-- ── Who may see which franchise ────────────────────────────────────────
--
-- Membership, NOT a single column on the user: IE staff currently run recon
-- for BOTH franchises, so one person legitimately needs access to OC jobs
-- while belonging to IE. One row per (user, department) they may see.

create table if not exists app_user_departments (
    user_id    uuid not null references auth.users (id) on delete cascade,
    department text not null,
    primary key (user_id, department)
);

create or replace function my_departments()
returns setof text
language sql
stable
security definer
set search_path = public
as $$
    select department from app_user_departments where user_id = auth.uid()
$$;

-- ── Row-Level Security ─────────────────────────────────────────────────
--
-- THIS is what separates IE from OC — not application code. The guards in
-- ems_db.py stay as a backstop, but from here the database refuses.
--
-- NULL department stays permissive, matching the SQLite rule: a job with no
-- folder pin yet has no known owner and must remain findable by everyone,
-- or pre-backfill jobs would vanish.

alter table jobs                  enable row level security;
alter table job_aliases           enable row level security;
alter table job_links             enable row level security;
alter table job_events            enable row level security;
alter table job_lifecycle         enable row level security;
alter table job_stage_transitions enable row level security;
alter table meta                  enable row level security;
alter table app_user_departments  enable row level security;

drop policy if exists jobs_rw on jobs;
create policy jobs_rw on jobs
    for all to authenticated
    using      (department is null or department in (select my_departments()))
    with check (department is null or department in (select my_departments()));

-- Child tables inherit their parent job's visibility.
drop policy if exists aliases_rw on job_aliases;
create policy aliases_rw on job_aliases
    for all to authenticated
    using      (exists (select 1 from jobs j where j.canon_key = job_aliases.canon_key))
    with check (exists (select 1 from jobs j where j.canon_key = job_aliases.canon_key));

drop policy if exists links_rw on job_links;
create policy links_rw on job_links
    for all to authenticated
    using      (exists (select 1 from jobs j where j.canon_key = job_links.canon_key))
    with check (exists (select 1 from jobs j where j.canon_key = job_links.canon_key));

drop policy if exists events_rw on job_events;
create policy events_rw on job_events
    for all to authenticated
    using      (exists (select 1 from jobs j where j.canon_key = job_events.canon_key))
    with check (exists (select 1 from jobs j where j.canon_key = job_events.canon_key));

-- Lifecycle/transitions are a Trello projection with no department column
-- of their own; Trello boards carry no franchise information (IE boards
-- hold OC recon jobs), so any signed-in user sees them.
drop policy if exists lifecycle_rw on job_lifecycle;
create policy lifecycle_rw on job_lifecycle
    for all to authenticated using (true) with check (true);

drop policy if exists transitions_rw on job_stage_transitions;
create policy transitions_rw on job_stage_transitions
    for all to authenticated using (true) with check (true);

drop policy if exists meta_read on meta;
create policy meta_read on meta for select to authenticated using (true);

-- Users may read their own memberships, never grant themselves more.
drop policy if exists own_departments on app_user_departments;
create policy own_departments on app_user_departments
    for select to authenticated using (user_id = auth.uid());

-- ── Notes ──────────────────────────────────────────────────────────────
-- No policy grants the `anon` role anything: an unauthenticated client sees
-- nothing, which is why shipping the publishable key in the .exe is safe.
--
-- After creating each user in Authentication → Users, grant access with:
--     insert into app_user_departments (user_id, department)
--     values ('<uuid>', 'IE');
-- Add a second row for anyone who also works the other franchise.
