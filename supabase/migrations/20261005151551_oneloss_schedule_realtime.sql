-- Stream only canonical visit changes; RLS continues to authorize subscribers.
do $$ begin
 if not exists(select 1 from pg_publication_tables where pubname='supabase_realtime'
   and schemaname='public' and tablename='schedule_visits') then
   alter publication supabase_realtime add table public.schedule_visits;
 end if;
end $$;
