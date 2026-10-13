-- Durable client identity; folders remain independent locators. No job merging.
create table public.crm_clients (
 client_id uuid primary key default gen_random_uuid(), display_name text not null check(length(trim(display_name)) between 1 and 300),
 department text not null, email text, phone text, address_json jsonb not null default '{}',
 active boolean not null default true, created_at text not null default now()::text, updated_at text not null default now()::text
);
create index crm_clients_department_name on public.crm_clients(department,display_name);
alter table public.crm_clients enable row level security;
revoke all on public.crm_clients from public,anon,authenticated;
grant select on public.crm_clients to authenticated;
create policy clients_read on public.crm_clients for select to authenticated
 using(department in (select public.my_departments()));
alter table public.jobs add column client_id uuid references public.crm_clients(client_id) on delete restrict;
alter table public.jobs add column client_revision bigint not null default 0;
create index jobs_client_owner on public.jobs(client_id);
create table public.job_client_history (
 event_id bigint generated always as identity primary key,
 job_id uuid not null references public.jobs(job_id) on delete restrict,
 from_client uuid references public.crm_clients(client_id), to_client uuid references public.crm_clients(client_id),
 changed_by uuid not null, changed_at timestamptz not null default now(), revision bigint not null,
 unique(job_id,revision)
);
create index job_client_history_from on public.job_client_history(from_client);
create index job_client_history_to on public.job_client_history(to_client);
alter table public.job_client_history enable row level security;
revoke all on public.job_client_history from public,anon,authenticated;
grant select on public.job_client_history to authenticated;
create policy client_history_read on public.job_client_history for select to authenticated
 using(exists(select 1 from public.jobs j where j.job_id=job_client_history.job_id));

-- Triggers also guard ordinary job updates; background sync never owns this column.
create function private.guard_client_owner() returns trigger language plpgsql security definer set search_path='' as $$
declare target_dept text; old_dept text;
begin
 if tg_op='INSERT' then
  if new.client_id is not null then raise exception 'Save the job before linking a client'; end if;
  new.client_revision:=0; return new;
 end if;
 if new.department is distinct from old.department and new.client_id is not null then
  select department into target_dept from public.crm_clients where client_id=new.client_id;
  if new.department is distinct from target_dept then raise exception 'Unlink client before changing job office'; end if;
 end if;
 if new.client_id is distinct from old.client_id then
  if auth.uid() is null then raise exception 'Sign in to change client'; end if;
  if new.department is not null and new.department not in(select public.my_departments()) then raise exception 'Job access required'; end if;
  if old.client_id is not null then
   select department into old_dept from public.crm_clients where client_id=old.client_id;
   if old_dept not in(select public.my_departments()) then raise exception 'Current client access required'; end if;
  end if;
  if new.client_id is not null then
   select department into target_dept from public.crm_clients where client_id=new.client_id and active;
   if target_dept is null or target_dept not in(select public.my_departments())
    or (new.department is not null and target_dept<>new.department) then raise exception 'Choose a client in the job office'; end if;
  end if;
  new.client_revision:=old.client_revision+1;
  insert into public.job_client_history(job_id,from_client,to_client,changed_by,revision)
   values(new.job_id,old.client_id,new.client_id,auth.uid(),new.client_revision);
 else new.client_revision:=old.client_revision;
 end if;
 return new;
end $$;
revoke all on function private.guard_client_owner() from public,anon,authenticated;
create trigger guard_client_owner before insert or update on public.jobs for each row execute function private.guard_client_owner();

create function private.change_job_client(p_job uuid,p_client uuid,p_revision bigint) returns jsonb
language plpgsql security definer set search_path='' as $$
declare j public.jobs;
begin
 if auth.uid() is null then raise exception 'Sign in'; end if;
 select * into j from public.jobs where job_id=p_job for update;
 if not found or (j.department is not null and j.department not in(select public.my_departments())) then raise exception 'Job access required'; end if;
 if j.client_revision<>p_revision then raise exception 'Client changed elsewhere. Reopen and review before transferring.'; end if;
 update public.jobs set client_id=p_client where job_id=p_job returning * into j;
 return jsonb_build_object('ok',true,'job_id',j.job_id,'client_id',j.client_id,'revision',j.client_revision);
end $$;
revoke all on function private.change_job_client(uuid,uuid,bigint) from public,anon,authenticated;
grant execute on function private.change_job_client(uuid,uuid,bigint) to authenticated;
create function public.change_job_client(p_job uuid,p_client uuid,p_revision bigint) returns jsonb
language sql security invoker set search_path='' as $$select private.change_job_client(p_job,p_client,p_revision)$$;
revoke all on function public.change_job_client(uuid,uuid,bigint) from public,anon;
grant execute on function public.change_job_client(uuid,uuid,bigint) to authenticated;

create function private.create_client_account(p_name text,p_department text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare c public.crm_clients;
begin
 if auth.uid() is null or p_department not in(select public.my_departments()) then raise exception 'Office access required'; end if;
 perform pg_advisory_xact_lock(hashtextextended(p_department||':'||lower(trim(p_name)),0));
 select * into c from public.crm_clients where department=p_department and lower(display_name)=lower(trim(p_name)) and active;
 if not found then insert into public.crm_clients(display_name,department) values(trim(p_name),p_department) returning * into c; end if;
 return to_jsonb(c);
end $$;
revoke all on function private.create_client_account(text,text) from public,anon,authenticated;
grant execute on function private.create_client_account(text,text) to authenticated;
create function public.create_client_account(p_name text,p_department text) returns jsonb
language sql security invoker set search_path='' as $$select private.create_client_account(p_name,p_department)$$;
revoke all on function public.create_client_account(text,text) from public,anon;
grant execute on function public.create_client_account(text,text) to authenticated;
notify pgrst,'reload schema';
