-- Follow-up for projects where 013 was already applied before PUBLIC was
-- included. PostgreSQL grants EXECUTE on new functions to PUBLIC by default;
-- authenticated-only RPCs should always opt in explicitly.

begin;

alter default privileges in schema public
  revoke execute on functions from public;

commit;
