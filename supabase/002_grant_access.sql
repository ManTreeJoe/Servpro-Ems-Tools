-- Linguar Hub — grant a user access to a franchise.
--
-- Until a person has a row here they can sign in successfully and see
-- NOTHING. That's the RLS policy working, not a bug.
--
-- Run in the Supabase SQL editor. Idempotent — safe to re-run.

-- ── 1. Who exists? ─────────────────────────────────────────────────────
-- Run this on its own first if you want to eyeball the list.

select id, email, created_at, last_sign_in_at
from auth.users
order by created_at;


-- ── 2. Grant access ────────────────────────────────────────────────────
-- No editing needed: this gives EVERY existing user both franchises,
-- which is correct while you're the only account. IE staff run OC's
-- recon, so a person legitimately holds both rows.

insert into app_user_departments (user_id, department)
select u.id, d.dept
from auth.users u
cross join (values ('IE'), ('OC')) as d (dept)
on conflict do nothing;


-- ── 3. Verify ──────────────────────────────────────────────────────────

select u.email, a.department
from app_user_departments a
join auth.users u on u.id = a.user_id
order by u.email, a.department;


-- ── Later: one franchise only ──────────────────────────────────────────
-- When you add office staff who should see just one side, use the
-- email-scoped form instead of the blanket grant above:
--
--   insert into app_user_departments (user_id, department)
--   select id, 'OC' from auth.users where email = 'person@company.com'
--   on conflict do nothing;
--
-- To revoke:
--
--   delete from app_user_departments
--   where department = 'OC'
--     and user_id = (select id from auth.users where email = 'person@company.com');
