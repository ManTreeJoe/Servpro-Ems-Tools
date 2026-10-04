-- The current hosted project intentionally does not install legacy schema 011.
-- Keep the always-on mirror healthy there; project into the old application
-- tables only on transitional installs that already own those tables.
begin;

create or replace function public.hub_trello_project_card(
  p_lease uuid, p_board_id text, p_card_id text, p_revision text
) returns boolean
language plpgsql security invoker set search_path = '' as $$
declare
  c public.hub_trello_mirror_cards%rowtype;
  v_card_key text;
  v_now text := clock_timestamp()::text;
  v_lists jsonb;
  v_done integer;
  v_total integer;
begin
  perform public.hub_trello_assert_lease(p_lease);
  select * into c from public.hub_trello_mirror_cards
   where board_id = p_board_id and card_id = p_card_id and present
   for update;
  if not found or c.revision <> p_revision
    or c.details_revision is distinct from p_revision
    or c.comments_revision is distinct from p_revision then
    return false;
  end if;

  -- The secure hub_trello_mirror_cards row is already the durable DB-first
  -- source. Schema 011 is optional and must never be installed implicitly.
  if to_regclass('public.crm_pipeline_cards') is null
    or to_regclass('public.crm_pipeline_activity') is null then
    return false;
  end if;

  select card_key into v_card_key from public.crm_pipeline_cards
   where external_id = p_card_id limit 1;
  if v_card_key is null then return false; end if;

  select coalesce(jsonb_agg(jsonb_build_object(
      'id', cl->>'id', 'name', coalesce(cl->>'name','Checklist'),
      'items', coalesce((select jsonb_agg(jsonb_build_object(
        'id', i->>'id', 'name', coalesce(i->>'name',''),
        'complete', i->>'state' = 'complete') order by coalesce((i->>'pos')::numeric,0))
        from jsonb_array_elements(coalesce(cl->'checkItems','[]'::jsonb)) i), '[]'::jsonb)
    ) order by coalesce((cl->>'pos')::numeric,0)), '[]'::jsonb)
    into v_lists
    from jsonb_array_elements(coalesce(c.details_json->'checklists','[]'::jsonb)) cl;
  select count(*), count(*) filter (where i->>'state' = 'complete')
    into v_total, v_done
    from jsonb_array_elements(coalesce(c.details_json->'checklists','[]'::jsonb)) cl,
         jsonb_array_elements(coalesce(cl->'checkItems','[]'::jsonb)) i;

  update public.crm_pipeline_cards set
    title = coalesce(nullif(c.details_json->>'name',''), title),
    description = c.details_json->>'desc',
    external_url = coalesce(c.details_json->>'shortUrl', external_url),
    labels_json = coalesce(c.details_json->'labels','[]'::jsonb),
    checklist_json = jsonb_build_object(
      'version',1,'lists',v_lists,'source','trello','updated_at',v_now,
      'summary',jsonb_build_object('done',v_done,'total',v_total)),
    due_at = c.details_json->>'due',
    due_complete = coalesce((c.details_json->>'dueComplete')::boolean,false),
    last_activity_at = c.details_json->>'dateLastActivity',
    sync_status = case when sync_status = 'pending' then sync_status else 'synced' end,
    sync_error = case when sync_status = 'pending' then sync_error else null end,
    synced_at = v_now, updated_at = v_now
   where card_key = v_card_key;

  insert into public.crm_pipeline_activity(
    activity_key, card_key, action_type, body, actor_name, happened_at,
    source, external_id, metadata_json, created_at)
  select 'trello:' || a->>'id', v_card_key, 'comment', a#>>'{data,text}',
    coalesce(a#>>'{memberCreator,fullName}',a#>>'{memberCreator,username}','Trello'),
    a->>'date', 'trello', a->>'id',
    jsonb_build_object('actor_id',coalesce(a#>>'{memberCreator,id}','')),
    v_now
  from jsonb_array_elements(c.comments_json) a
  where nullif(btrim(a#>>'{data,text}'),'') is not null
  on conflict (activity_key) do update set
    body=excluded.body, actor_name=excluded.actor_name,
    happened_at=excluded.happened_at, metadata_json=excluded.metadata_json;

  delete from public.crm_pipeline_activity a
   where a.card_key = v_card_key and a.source = 'trello'
     and not exists (select 1 from jsonb_array_elements(c.comments_json) x
                     where x->>'id' = a.external_id);
  return true;
end;
$$;

revoke all on function public.hub_trello_project_card(uuid,text,text,text)
  from public, anon, authenticated;
grant execute on function public.hub_trello_project_card(uuid,text,text,text)
  to service_role;

commit;
