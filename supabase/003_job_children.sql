-- Linguar Hub — schema v4: job_children.
--
-- `year → client → child`. A child is a CLAIM, a UNIT, or a commercial
-- SUB-JOB — one shape, only `kind` differs. Each has its own folder and
-- its own Trello card, which is the whole point: a client with several
-- claims or units has several cards (live data has clients with 7, 8 and
-- 12), and a flat link list cannot say which card belongs to which child.
--
-- Replaces jobs.parent_canon / jobs.unit_number, which inferred the
-- hierarchy from NAME STRINGS. On live data every one of the 21 rows that
-- inference had populated named a parent that does not exist ('store',
-- 'stater bros', 'monterey apartments ga'). Rows here exist because a
-- child FOLDER exists — disk is the authority, same rule as
-- jobs.department.
--
-- Run once in the Supabase SQL editor. Idempotent — safe to re-run.

create table if not exists job_children (
    id            bigint generated always as identity primary key,
    parent_canon  text not null references jobs (canon_key) on delete cascade,
    name          text not null,          -- folder name: '2nd Claim', 'Unit 182'
    kind          text not null,          -- claim | unit | subjob
    ordinal       integer,                -- claim number, when kind = 'claim'
    folder_path   text,
    trello_card   text,
    companycam    text,
    department    text,
    created_at    text,
    updated_at    text,
    unique (parent_canon, name)
);

create index if not exists idx_children_parent on job_children (parent_canon);
create index if not exists idx_children_folder on job_children (folder_path);
create index if not exists idx_children_card   on job_children (trello_card);

update meta set value = '4' where key = 'schema_version';
insert into meta (key, value) values ('schema_version', '4')
    on conflict (key) do update set value = excluded.value;

-- ── Row-Level Security ─────────────────────────────────────────────────
-- A child is visible exactly when its parent client is. Inheriting the
-- parent's policy rather than repeating the department test means a child
-- can never become visible to a franchise that cannot see its client.

alter table job_children enable row level security;

drop policy if exists children_rw on job_children;
create policy children_rw on job_children
    for all to authenticated
    using      (exists (select 1 from jobs j
                        where j.canon_key = job_children.parent_canon))
    with check (exists (select 1 from jobs j
                        where j.canon_key = job_children.parent_canon));

-- ── Verify ─────────────────────────────────────────────────────────────

select column_name, data_type
from information_schema.columns
where table_name = 'job_children'
order by ordinal_position;
