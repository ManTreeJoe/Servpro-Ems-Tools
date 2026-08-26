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
-- Replace both placeholders. Franchise codes come from Linguar Hub
-- Settings and are not fixed by this database.

insert into app_user_departments (user_id, department)
select id, '<FRANCHISE_CODE>'
from auth.users
where lower(email) = lower('<EMPLOYEE_EMAIL>')
on conflict do nothing;


-- ── 3. Verify ──────────────────────────────────────────────────────────

select u.email, a.department
from app_user_departments a
join auth.users u on u.id = a.user_id
order by u.email, a.department;


-- ── Later: add or remove any configured franchise ─────────────────────
-- Run the grant above again with another configured franchise code.
--
--   insert into app_user_departments (user_id, department)
--   select id, '<FRANCHISE_CODE>' from auth.users
--   where email = '<EMPLOYEE_EMAIL>'
--   on conflict do nothing;
--
-- To revoke:
--
--   delete from app_user_departments
--   where department = '<FRANCHISE_CODE>'
--     and user_id = (select id from auth.users
--                    where email = '<EMPLOYEE_EMAIL>');
