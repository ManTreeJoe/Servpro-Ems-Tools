-- Additive demo file library. Installer must assert the oneloss-demo project.
begin;
create schema demo_files_private;
revoke all on schema demo_files_private from public, anon, authenticated;
grant usage on schema demo_files_private to authenticated;

create function demo_files_private.allowed(f uuid, editing boolean default false, library boolean default false)
returns boolean language sql stable security definer set search_path='' as $$
 select auth.uid() is not null and exists(
   select 1 from public.foundation_franchises x where x.id=f and (
     exists(select 1 from public.platform_admins a where a.company_id=x.company_id and a.user_id=auth.uid())
     or (not library and exists(select 1 from public.foundation_memberships m
       where m.franchise_id=f and m.user_id=auth.uid() and (not editing or m.role='editor')))))
$$;
revoke all on function demo_files_private.allowed(uuid,boolean,boolean) from public,anon;
grant execute on function demo_files_private.allowed(uuid,boolean,boolean) to authenticated;

create table public.demo_form_templates (
 id uuid primary key default gen_random_uuid(),
 franchise_id uuid not null references public.foundation_franchises(id),
 title text not null check(length(trim(title)) between 1 and 160),
 description text not null default '' check(length(description)<=2000),
 archived boolean not null default false,
 created_by uuid not null default auth.uid() references auth.users(id),
 created_at timestamptz not null default now(),
 unique(id,franchise_id)
);
create table public.demo_file_profiles (
 id uuid primary key default gen_random_uuid(),
 franchise_id uuid not null references public.foundation_franchises(id),
 profile_key text not null check(profile_key ~ '^[a-z0-9][a-z0-9_-]{0,79}$'),
 title text not null check(length(trim(title)) between 1 and 160),
 division text not null check(division in ('EMS','Contents','Recon')),
 property_label text check(length(property_label)<=250),
 revision integer not null default 1 check(revision>0),
 active boolean not null default true,
 unique(franchise_id,profile_key), unique(id,franchise_id)
);
create table public.demo_profile_slots (
 profile_id uuid not null,
 franchise_id uuid not null,
 code text not null check(code ~ '^[a-z0-9][a-z0-9_-]{0,79}$'),
 label text not null check(length(trim(label)) between 1 and 160),
 required boolean not null default true,
 sort_order integer not null default 0,
 template_id uuid,
 primary key(profile_id,code),
 foreign key(profile_id,franchise_id) references public.demo_file_profiles(id,franchise_id),
 foreign key(template_id,franchise_id) references public.demo_form_templates(id,franchise_id)
);
-- A profile application is a snapshot, never a live link to editable defaults.
create table public.demo_job_profiles (
 id uuid primary key default gen_random_uuid(),
 loss_id uuid not null references public.platform_losses(id),
 franchise_id uuid not null references public.foundation_franchises(id),
 division text not null check(division in ('EMS','Contents','Recon')),
 source_profile_id uuid not null,
 source_revision integer not null,
 title text not null,
 applied_by uuid not null default auth.uid() references auth.users(id),
 applied_at timestamptz not null default now(),
 unique(loss_id,division), unique(id,loss_id,franchise_id),
 foreign key(source_profile_id,franchise_id) references public.demo_file_profiles(id,franchise_id)
);
create table public.demo_job_form_slots (
 id uuid primary key default gen_random_uuid(),
 application_id uuid not null,
 loss_id uuid not null,
 franchise_id uuid not null,
 code text not null,
 label text not null,
 required boolean not null,
 sort_order integer not null,
 template_id uuid,
 template_upload_id uuid,
 status text not null default 'missing' check(status in ('missing','received','accepted','not_applicable')),
 status_note text not null default '' check(length(status_note)<=2000),
 revision integer not null default 1,
 unique(application_id,code), unique(id,loss_id,franchise_id),
 foreign key(application_id,loss_id,franchise_id) references public.demo_job_profiles(id,loss_id,franchise_id),
 foreign key(template_id,franchise_id) references public.demo_form_templates(id,franchise_id)
);
create table public.demo_job_files (
 id uuid primary key default gen_random_uuid(),
 loss_id uuid not null references public.platform_losses(id),
 franchise_id uuid not null references public.foundation_franchises(id),
 kind text not null check(kind in ('document','photo','video')),
 title text not null check(length(trim(title)) between 1 and 250),
 division text check(division in ('EMS','Contents','Recon')),
 category text not null default '' check(length(category)<=100),
 tags text[] not null default '{}' check(cardinality(tags)<=30 and array_position(tags,null) is null and length(array_to_string(tags,','))<=2000),
 captured_at timestamptz,
 revision integer not null default 1,
 archived boolean not null default false,
 created_by uuid not null default auth.uid() references auth.users(id),
 created_at timestamptz not null default now(),
 unique(id,franchise_id), unique(id,loss_id,franchise_id)
);
-- One append-only revision for either a reusable blank or a job attachment.
create table public.demo_file_uploads (
 id uuid primary key default gen_random_uuid(),
 franchise_id uuid not null references public.foundation_franchises(id),
 template_id uuid,
 file_id uuid,
 revision integer not null check(revision>0),
 original_name text not null check(length(original_name) between 1 and 255 and original_name !~ '[[:cntrl:]]'),
 content_type text not null check(content_type in ('application/pdf','image/jpeg','image/png','image/webp','image/heic','image/heif',
   'video/mp4','video/quicktime','application/msword','application/vnd.openxmlformats-officedocument.wordprocessingml.document',
   'application/vnd.ms-excel','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','text/plain','text/csv')),
 byte_size bigint not null check(byte_size between 1 and 52428800),
 client_sha256 text check(client_sha256 ~ '^[a-f0-9]{64}$'),
 mapping jsonb not null default '[]'::jsonb check(jsonb_typeof(mapping)='array' and jsonb_array_length(mapping)<=100),
 mapping_format text not null default 'form-builder-v1' check(mapping_format='form-builder-v1'),
 state text not null default 'reserved' check(state in ('reserved','available')),
 bucket_id text generated always as(case when template_id is not null then 'form-templates' else 'job-files' end) stored,
 object_key text generated always as(franchise_id::text||'/'||id::text) stored,
 created_by uuid not null default auth.uid() references auth.users(id),
 created_at timestamptz not null default now(),
 available_at timestamptz,
 check((template_id is not null) <> (file_id is not null)),
 check(template_id is null or content_type='application/pdf'),
 check(template_id is not null or mapping='[]'::jsonb),
 check((state='available')=(available_at is not null)),
 unique(template_id,revision), unique(file_id,revision), unique(bucket_id,object_key),
 unique(id,template_id,franchise_id),
 foreign key(template_id,franchise_id) references public.demo_form_templates(id,franchise_id),
 foreign key(file_id,franchise_id) references public.demo_job_files(id,franchise_id)
);
alter table public.demo_job_form_slots add foreign key(template_upload_id,template_id,franchise_id)
 references public.demo_file_uploads(id,template_id,franchise_id);
create table public.demo_slot_files (
 slot_id uuid not null,
 file_id uuid not null,
 loss_id uuid not null,
 franchise_id uuid not null,
 primary key(slot_id,file_id),
 foreign key(slot_id,loss_id,franchise_id) references public.demo_job_form_slots(id,loss_id,franchise_id),
 foreign key(file_id,loss_id,franchise_id) references public.demo_job_files(id,loss_id,franchise_id)
);
create table public.demo_file_events (
 id bigint generated always as identity primary key,
 franchise_id uuid not null references public.foundation_franchises(id),
 actor_id uuid not null references auth.users(id),
 entity_id uuid not null,
 event text not null,
 created_at timestamptz not null default now()
);

create index demo_job_files_list on public.demo_job_files(loss_id,kind,created_at desc,id);
create index demo_uploads_file on public.demo_file_uploads(file_id,revision desc);
create index demo_uploads_template on public.demo_file_uploads(template_id,revision desc);
create index demo_uploads_scope on public.demo_file_uploads(franchise_id,created_at desc);
create index demo_files_scope on public.demo_job_files(franchise_id,loss_id);
create index demo_slots_job on public.demo_job_form_slots(loss_id,sort_order);
create index demo_templates_scope on public.demo_form_templates(franchise_id,title);
create index demo_profiles_scope on public.demo_file_profiles(franchise_id,division);
create index demo_events_scope on public.demo_file_events(franchise_id,created_at desc);
create index demo_slot_files_file on public.demo_slot_files(file_id);

-- Clients read tables, but perform all writes through bounded, checked RPCs.
do $$declare t text;begin
 foreach t in array array['demo_form_templates','demo_file_profiles','demo_profile_slots','demo_job_profiles',
   'demo_job_form_slots','demo_job_files','demo_file_uploads','demo_slot_files','demo_file_events'] loop
   execute format('alter table public.%I enable row level security',t);
   execute format('revoke all on public.%I from public,anon,authenticated',t);
   execute format('grant select on public.%I to authenticated',t);
   execute format('create policy scoped_read on public.%I for select to authenticated using (demo_files_private.allowed(franchise_id))',t);
 end loop;
end$$;

create function public.demo_create_template(p_franchise uuid,p_title text) returns uuid
language plpgsql security definer set search_path='' as $$declare result uuid;begin
 if not demo_files_private.allowed(p_franchise,true,true) then raise exception 'Library administrator required' using errcode='42501';end if;
 insert into public.demo_form_templates(franchise_id,title) values(p_franchise,p_title) returning id into result;
 insert into public.demo_file_events(franchise_id,actor_id,entity_id,event) values(p_franchise,auth.uid(),result,'template.created');
 return result;
end$$;

create function public.demo_save_profile(p_franchise uuid,p_key text,p_title text,p_division text,
 p_property text,p_expected_revision integer,p_slots jsonb) returns uuid
language plpgsql security definer set search_path='' as $$
declare result uuid; prior integer; item jsonb; begin
 if not demo_files_private.allowed(p_franchise,true,true) then raise exception 'Library administrator required' using errcode='42501';end if;
 if p_slots is null or jsonb_typeof(p_slots)<>'array' or jsonb_array_length(p_slots)>100 then raise exception 'Invalid slots';end if;
 perform pg_advisory_xact_lock(hashtextextended(p_franchise::text||p_key,0));
 select id,revision into result,prior from public.demo_file_profiles where franchise_id=p_franchise and profile_key=p_key for update;
 if result is null then
   if p_expected_revision<>0 or p_expected_revision is null then raise exception 'Profile revision conflict' using errcode='40001';end if;
   insert into public.demo_file_profiles(franchise_id,profile_key,title,division,property_label)
    values(p_franchise,p_key,p_title,p_division,p_property) returning id into result;
 else
   if prior is distinct from p_expected_revision then raise exception 'Profile revision conflict' using errcode='40001';end if;
   update public.demo_file_profiles set title=p_title,division=p_division,property_label=p_property,revision=revision+1 where id=result;
   delete from public.demo_profile_slots where profile_id=result;
 end if;
 for item in select value from jsonb_array_elements(p_slots) loop
   if jsonb_typeof(item)<>'object' or not(item ? 'code' and item ? 'label' and item ? 'required')
      or jsonb_typeof(item->'required')<>'boolean' then raise exception 'Invalid slot definition';end if;
   insert into public.demo_profile_slots(profile_id,franchise_id,code,label,required,sort_order,template_id)
    values(result,p_franchise,item->>'code',item->>'label',(item->>'required')::boolean,
      coalesce((item->>'sort_order')::integer,0),nullif(item->>'template_id','')::uuid);
 end loop;
 insert into public.demo_file_events(franchise_id,actor_id,entity_id,event) values(p_franchise,auth.uid(),result,'profile.saved');
 return result;
end$$;

create function public.demo_apply_file_profile(p_loss uuid,p_profile uuid,p_expected_revision integer) returns uuid
language plpgsql security definer set search_path='' as $$
declare f uuid; profile public.demo_file_profiles; result uuid;begin
 select franchise_id into f from public.platform_losses where id=p_loss for update;
 if not demo_files_private.allowed(f,true) then raise exception 'Job editor required' using errcode='42501';end if;
 select * into profile from public.demo_file_profiles where id=p_profile and franchise_id=f and active for share;
 if profile.id is null or profile.revision is distinct from p_expected_revision then raise exception 'Profile revision conflict' using errcode='40001';end if;
 -- Existing applications are immutable; changing defaults cannot rewrite completed paperwork.
 insert into public.demo_job_profiles(loss_id,franchise_id,division,source_profile_id,source_revision,title)
  values(p_loss,f,profile.division,profile.id,profile.revision,profile.title) returning id into result;
 insert into public.demo_job_form_slots(application_id,loss_id,franchise_id,code,label,required,sort_order,template_id,template_upload_id)
 select result,p_loss,f,s.code,s.label,s.required,s.sort_order,s.template_id,
  (select u.id from public.demo_file_uploads u where u.template_id=s.template_id and u.state='available' order by revision desc limit 1)
 from public.demo_profile_slots s where s.profile_id=p_profile;
 insert into public.demo_file_events(franchise_id,actor_id,entity_id,event) values(f,auth.uid(),result,'profile.applied');
 return result;
end$$;

create function public.demo_create_job_file(p_loss uuid,p_kind text,p_title text,p_division text default null) returns uuid
language plpgsql security definer set search_path='' as $$declare f uuid; result uuid;begin
 select franchise_id into f from public.platform_losses where id=p_loss;
 if not demo_files_private.allowed(f,true) then raise exception 'Job editor required' using errcode='42501';end if;
 insert into public.demo_job_files(loss_id,franchise_id,kind,title,division) values(p_loss,f,p_kind,p_title,p_division) returning id into result;
 insert into public.demo_file_events(franchise_id,actor_id,entity_id,event) values(f,auth.uid(),result,'file.created');
 return result;
end$$;

create function public.demo_reserve_file_upload(p_target uuid,p_template boolean,p_expected_revision integer,
 p_name text,p_type text,p_bytes bigint,p_sha256 text default null,p_mapping jsonb default '[]') returns public.demo_file_uploads
language plpgsql security definer set search_path='' as $$
declare f uuid; prior integer; kind text; result public.demo_file_uploads;begin
 if p_template is null then raise exception 'Target type required';end if;
 if p_template then
   select franchise_id into f from public.demo_form_templates where id=p_target and not archived for update;
 else
   select franchise_id,public.demo_job_files.kind into f,kind from public.demo_job_files where id=p_target for update;
 end if;
 if not demo_files_private.allowed(f,true,p_template) then raise exception 'Upload access denied' using errcode='42501';end if;
 if not p_template and ((kind='photo' and p_type not like 'image/%') or (kind='video' and p_type not like 'video/%')
   or (kind='document' and (p_type like 'image/%' or p_type like 'video/%'))) then raise exception 'File category does not match content type';end if;
 select coalesce(max(revision),0) into prior from public.demo_file_uploads
  where (p_template and template_id=p_target) or (not p_template and file_id=p_target);
 if prior is distinct from p_expected_revision then raise exception 'Upload revision conflict' using errcode='40001';end if;
 insert into public.demo_file_uploads(franchise_id,template_id,file_id,revision,original_name,content_type,byte_size,client_sha256,mapping)
 values(f,case when p_template then p_target end,case when not p_template then p_target end,prior+1,p_name,p_type,p_bytes,p_sha256,p_mapping)
 returning * into result;
 return result;
end$$;

create function public.demo_set_file_info(p_file uuid,p_expected_revision integer,p_title text,p_category text,
 p_tags text[],p_captured_at timestamptz,p_archived boolean) returns integer
language plpgsql security definer set search_path='' as $$declare f public.demo_job_files;begin
 select * into f from public.demo_job_files where id=p_file for update;
 if not demo_files_private.allowed(f.franchise_id,true) then raise exception 'Job editor required' using errcode='42501';end if;
 if f.revision is distinct from p_expected_revision then raise exception 'File revision conflict' using errcode='40001';end if;
 update public.demo_job_files set title=p_title,category=p_category,tags=p_tags,captured_at=p_captured_at,
  archived=p_archived,revision=revision+1 where id=f.id;
 insert into public.demo_file_events(franchise_id,actor_id,entity_id,event) values(f.franchise_id,auth.uid(),f.id,'file.metadata_changed');
 return f.revision+1;
end$$;

create function public.demo_finish_file_upload(p_upload uuid) returns public.demo_file_uploads
language plpgsql security definer set search_path='' as $$declare u public.demo_file_uploads; meta jsonb;begin
 select * into u from public.demo_file_uploads where id=p_upload for update;
 if u.id is null or not demo_files_private.allowed(u.franchise_id,true,u.template_id is not null)
    or (u.created_by<>auth.uid() and not demo_files_private.allowed(u.franchise_id,true,true))
 then raise exception 'Upload access denied' using errcode='42501';end if;
 if u.state='available' then return u;end if;
 select metadata into meta from storage.objects where bucket_id=u.bucket_id and name=u.object_key;
 if meta is null or (meta->>'size')::bigint is distinct from u.byte_size
   or meta->>'mimetype' is distinct from u.content_type then raise exception 'Stored object size/type not confirmed';end if;
 update public.demo_file_uploads set state='available',available_at=now() where id=u.id returning * into u;
 insert into public.demo_file_events(franchise_id,actor_id,entity_id,event) values(u.franchise_id,auth.uid(),u.id,'upload.available');
 return u;
end$$;

create function public.demo_link_slot_file(p_slot uuid,p_file uuid) returns void
language plpgsql security definer set search_path='' as $$declare s public.demo_job_form_slots;begin
 select * into s from public.demo_job_form_slots where id=p_slot;
 if not demo_files_private.allowed(s.franchise_id,true) then raise exception 'Job editor required' using errcode='42501';end if;
 if not exists(select 1 from public.demo_file_uploads where file_id=p_file and state='available') then raise exception 'Upload is not available';end if;
 insert into public.demo_slot_files(slot_id,file_id,loss_id,franchise_id) values(s.id,p_file,s.loss_id,s.franchise_id) on conflict do nothing;
end$$;

create function public.demo_set_slot_status(p_slot uuid,p_expected_revision integer,p_status text,p_note text default '') returns integer
language plpgsql security definer set search_path='' as $$declare s public.demo_job_form_slots;begin
 select * into s from public.demo_job_form_slots where id=p_slot for update;
 if not demo_files_private.allowed(s.franchise_id,true) then raise exception 'Job editor required' using errcode='42501';end if;
 if s.revision is distinct from p_expected_revision then raise exception 'Slot revision conflict' using errcode='40001';end if;
 if p_status='not_applicable' and length(trim(coalesce(p_note,'')))=0 then raise exception 'Reason required';end if;
 if p_status in ('received','accepted') and not exists(select 1 from public.demo_slot_files where slot_id=s.id) then raise exception 'Attach an uploaded file first';end if;
 update public.demo_job_form_slots set status=p_status,status_note=p_note,revision=revision+1 where id=s.id;
 insert into public.demo_file_events(franchise_id,actor_id,entity_id,event) values(s.franchise_id,auth.uid(),s.id,'slot.'||p_status);
 return s.revision+1;
end$$;

-- Harden every new public RPC: authorization above is server-side, not metadata claims.
do $$declare r record;begin
 for r in select p.oid::regprocedure as signature from pg_proc p join pg_namespace n on n.oid=p.pronamespace
 where n.nspname='public' and p.proname in ('demo_create_template','demo_save_profile','demo_apply_file_profile',
 'demo_create_job_file','demo_reserve_file_upload','demo_finish_file_upload','demo_link_slot_file','demo_set_slot_status','demo_set_file_info') loop
 execute format('revoke all on function %s from public,anon',r.signature);
 execute format('grant execute on function %s to authenticated',r.signature);
 end loop;
end$$;

insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types) values
 ('form-templates','form-templates',false,52428800,array['application/pdf']),
 ('job-files','job-files',false,52428800,array['application/pdf','image/jpeg','image/png','image/webp','image/heic','image/heif',
 'video/mp4','video/quicktime','application/msword','application/vnd.openxmlformats-officedocument.wordprocessingml.document',
 'application/vnd.ms-excel','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','text/plain','text/csv']);

create function demo_files_private.object_allowed(bucket text,path text,writing boolean) returns boolean
language sql stable security definer set search_path='' as $$
 select exists(select 1 from public.demo_file_uploads u where u.bucket_id=bucket and u.object_key=path
 and demo_files_private.allowed(u.franchise_id,writing,writing and u.template_id is not null)
 and (case when writing then u.state='reserved' and u.created_by=auth.uid() and u.created_at>now()-interval '24 hours'
 else u.state='available' end))
$$;
revoke all on function demo_files_private.object_allowed(text,text,boolean) from public,anon;
grant execute on function demo_files_private.object_allowed(text,text,boolean) to authenticated;
create policy demo_files_read on storage.objects for select to authenticated using
 (bucket_id in ('form-templates','job-files') and demo_files_private.object_allowed(bucket_id,name,false));
create policy demo_files_insert on storage.objects for insert to authenticated with check
 (bucket_id in ('form-templates','job-files') and demo_files_private.object_allowed(bucket_id,name,true));
-- Restrictive boundaries prevent any other permissive policy opening these buckets.
create policy demo_files_read_boundary on storage.objects as restrictive for select to authenticated using
 (bucket_id not in ('form-templates','job-files') or demo_files_private.object_allowed(bucket_id,name,false));
create policy demo_files_insert_boundary on storage.objects as restrictive for insert to authenticated with check
 (bucket_id not in ('form-templates','job-files') or demo_files_private.object_allowed(bucket_id,name,true));
create policy demo_files_no_overwrite on storage.objects as restrictive for update to authenticated
 using(bucket_id not in ('form-templates','job-files')) with check(bucket_id not in ('form-templates','job-files'));
create policy demo_files_no_delete on storage.objects as restrictive for delete to authenticated
 using(bucket_id not in ('form-templates','job-files'));

-- Starter labels only: no fabricated PDF, signatures, mappings or job changes.
insert into public.demo_file_profiles(franchise_id,profile_key,title,division)
 select f.id,v.key,v.title,'EMS' from public.foundation_franchises f cross join(values
 ('ems-standard','Normal EMS'),('ems-state-farm','State Farm EMS'),
 ('commercial-base','Commercial — base'),('self-pay','Self-pay')) v(key,title);
insert into public.demo_profile_slots(profile_id,franchise_id,code,label,required,sort_order)
 select p.id,p.franchise_id,v.code,v.label,true,v.sort_order from public.demo_file_profiles p
 cross join(values('atp','ATP',10),('cer','CER',20),('cif','CIF',30),('cos','COS',40)) v(code,label,sort_order)
 where p.profile_key in ('ems-standard','ems-state-farm','commercial-base');
insert into public.demo_profile_slots(profile_id,franchise_id,code,label,required,sort_order)
 select p.id,p.franchise_id,v.code,v.label,true,v.sort_order from public.demo_file_profiles p
 cross join(values('sf-atr','SF ATR',50),('sf-atp','SF ATP',60)) v(code,label,sort_order) where p.profile_key='ems-state-farm';
insert into public.demo_profile_slots(profile_id,franchise_id,code,label,required,sort_order)
 select p.id,p.franchise_id,v.code,v.label,v.required,v.sort_order from public.demo_file_profiles p cross join(values
 ('long-form-contract','Long form contract',true,10),('cos','COS',true,20),
 ('credit-card-authorization','Credit card authorization',false,30)) v(code,label,required,sort_order) where p.profile_key='self-pay';
notify pgrst, 'reload schema';
commit;
