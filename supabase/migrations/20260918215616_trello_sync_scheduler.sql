-- Infrastructure only. Scheduling/activation is separate and requires secrets,
-- a verified Trello identity and an explicit board allowlist.
create extension if not exists pg_cron with schema pg_catalog;
create extension if not exists pg_net with schema extensions;
