-- Linguar Hub — schema v8: the levels between a client and a claim.
--
-- job_children models ONE level: client → child. Live data needs more.
-- Every one of these is a real row, and each crams its structure into a
-- single name string:
--
--   Aperto Property Management- (Tres Lagos - Unit 6204)   mgmt → property → unit
--   Greystar - Avana Springs (Unit 585G)                   mgmt → property → unit
--   Avila Apartments (Unit 623) - (6/29/26)                property → unit → claim date
--   Mission Trail Apartment (Unit 311C) - 5/19/26          property → unit → claim date
--
-- The cost of encoding it in the name is not theoretical. Aperto's key
-- canonicalised to 'aperto property management- (tres lagos' — truncated
-- mid-phrase — while BOTH of its unit folders canonicalise to plain
-- 'tres lagos'. Two units, filed 8/13 and 8/17, landed on one row with
-- two Trello cards and one CompanyCam project between them.
--
-- Columns, not recursion. The domain has four known levels and will not
-- grow a fifth, so a self-referencing parent_child_id would buy
-- flexibility nothing needs and cost recursive queries in a codebase
-- that has none — and would break the RLS policy below, which reads
-- `parent_canon = jobs.canon_key` and stops working the moment a child's
-- parent is another child. Here parent_canon still points at the client,
-- so 003's policy and children_of() are untouched.
--
-- TEXT throughout, dates included — same rule as 005. The office types
-- what the office types ('8.13.26', '6/29/26', '7/20'); a DATE column
-- would reject the row rather than store what we were told. `unit` is
-- text because live units are '585G', '1416B', '311C', not integers.
--
-- Depth varies and that is fine: `property` is null when the client IS
-- the property (Avila Apartments has no management company above it).
--
-- Run in the Supabase SQL editor. Idempotent — safe to re-run.

alter table job_children add column if not exists property   text;
alter table job_children add column if not exists unit       text;
alter table job_children add column if not exists claim_date text;

-- Grouping a complex's units is the query the audit runs constantly
-- ("show me every unit of Tres Lagos"), so it gets the composite index
-- rather than property alone.
create index if not exists idx_children_property
    on job_children (parent_canon, property) where property is not null;
create index if not exists idx_children_unit
    on job_children (parent_canon, unit) where unit is not null;

update meta set value = '8' where key = 'schema_version';
insert into meta (key, value) values ('schema_version', '8')
    on conflict (key) do update set value = excluded.value;

-- ── Verify ─────────────────────────────────────────────────────────────
-- Expect property / unit / claim_date at the end of the column list.

select column_name, data_type
from information_schema.columns
where table_name = 'job_children'
order by ordinal_position;
