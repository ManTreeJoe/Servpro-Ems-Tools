create or replace function private.job_comment_threads(p_action text,p_card text,p_data jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare who uuid:=auth.uid(); allowed text[]; r public.job_comment_threads;
 parent public.job_comment_threads; a jsonb; k text:=p_data->>'id';
 op uuid; author_name text; rows jsonb; cursor_id text;
begin
 select array_agg(d) into allowed from public.my_departments() d;
 if who is null or not exists(select 1 from public.hub_trello_mirror_cards c
  join public.hub_trello_sync_sources s using(board_id) where c.card_id=p_card and c.present
  and s.enabled and s.reader_workspace is not null and s.reader_department=any(s.required_departments)
  and cardinality(s.required_departments)>0 and s.required_departments<@allowed) then
  raise exception 'Card access required' using errcode='42501'; end if;
 if octet_length(p_data::text)>30000 then raise exception 'Request too large'; end if;
 if p_action='read' then
  -- Recover an accepted Trello POST whose desktop response was lost. Never
  -- repost uncertain deliveries. Only one exact marker/body match qualifies.
  update public.job_comment_threads saved_reply set provider_id=matches.action_id,delivery='sent'
   from (select t.id,min(provider_action->>'id') action_id from public.job_comment_threads t
    join public.hub_trello_mirror_cards c on c.card_id=t.card_id,
    lateral jsonb_array_elements(coalesce(c.comments_json,'[]')) provider_action
    where t.card_id=p_card and t.native and t.delivery in('sending','uncertain')
     and provider_action->>'type'='commentCard'
     and right(provider_action#>>'{data,text}',length('[OneLoss reply '||t.operation_id||']'))='[OneLoss reply '||t.operation_id||']'
     and left(provider_action#>>'{data,text}',length(t.body))=t.body
    group by t.id having count(distinct provider_action->>'id')=1) matches
   where saved_reply.card_id=p_card and saved_reply.id=matches.id;
  select coalesce(jsonb_agg(to_jsonb(t) order by t.id),'[]') into rows from
   (select * from public.job_comment_threads where card_id=p_card and id>coalesce(p_data->>'after','') order by id limit 200) t;
  if jsonb_array_length(rows)=200 then cursor_id:=rows->199->>'id'; end if;
  return jsonb_build_object('ok',true,'comments',rows,'next',cursor_id);
 end if;
 -- Serializes retries, pins and parent creation only within this card.
 perform pg_advisory_xact_lock(hashtextextended('comment-thread:'||p_card,0));
 if p_action in('pin','reply') then
  k:=case when p_action='reply' then p_data->>'parent' else k end;
  select * into r from public.job_comment_threads where card_id=p_card and (id=k or provider_id=k);
  if not found then
   select item into a from public.hub_trello_mirror_cards c,
    lateral jsonb_array_elements(coalesce(c.comments_json,'[]')) item
    where c.card_id=p_card and c.present and item->>'id'=k and item->>'type'='commentCard' limit 1;
   if a is null then raise exception 'Comment is not in the shared snapshot yet. Refresh and retry.'; end if;
   insert into public.job_comment_threads(card_id,id,root_id,body,actor,created_at,provider_id)
    values(p_card,k,k,coalesce(a#>>'{data,text}',''),coalesce(a#>>'{memberCreator,fullName}','Trello member'),
     (a->>'date')::timestamptz,k) returning * into r;
  end if;
 end if;
 if p_action='pin' then
  if jsonb_typeof(p_data->'pinned') is distinct from 'boolean' or
   jsonb_typeof(p_data->'expected') is distinct from 'boolean' then raise exception 'Invalid pin'; end if;
  if r.pinned is distinct from (p_data->>'expected')::boolean and r.pinned is distinct from (p_data->>'pinned')::boolean then
   raise exception 'Pin changed. Refresh and retry.' using errcode='40001'; end if;
  update public.job_comment_threads set pinned=(p_data->>'pinned')::boolean,pinned_by=who
   where card_id=p_card and id=r.id returning * into r;
 elsif p_action='reply' then
  parent:=r; op:=(p_data->>'operation_id')::uuid;
  if op is null or length(btrim(coalesce(p_data->>'body',''))) not between 1 and 20000 then raise exception 'Invalid reply'; end if;
  select * into r from public.job_comment_threads where operation_id=op;
  if found then
   if r.author_id<>who or r.card_id<>p_card or r.parent_id<>parent.id or r.body<>p_data->>'body' then
    raise exception 'Operation ID reused'; end if;
  else
   select coalesce(nullif(raw_user_meta_data->>'display_name',''),nullif(raw_user_meta_data->>'full_name',''),'OneLoss member')
    into author_name from auth.users where id=who;
   insert into public.job_comment_threads(card_id,id,parent_id,root_id,body,actor,author_id,native,delivery,operation_id)
    values(p_card,'oneloss:'||op,parent.id,parent.root_id,p_data->>'body',author_name,who,true,'queued',op) returning * into r;
  end if;
  return jsonb_build_object('ok',true,'comment',to_jsonb(r),'parent',to_jsonb(parent));
 elsif p_action in('claim','finish') then
  select * into r from public.job_comment_threads where card_id=p_card and id=k for update;
  if not found or r.author_id is distinct from who or not r.native then raise exception 'Author required' using errcode='42501'; end if;
  if p_action='claim' then
   if r.delivery<>'queued' then return jsonb_build_object('ok',true,'claimed',false); end if;
   update public.job_comment_threads set delivery='sending' where card_id=p_card and id=k;
   return jsonb_build_object('ok',true,'claimed',true);
  end if;
  if r.delivery='sent' then return jsonb_build_object('ok',true,'comment',to_jsonb(r)); end if;
  if r.delivery not in('sending','uncertain') then raise exception 'Delivery not claimed'; end if;
  if coalesce(p_data->>'provider_id','')<>'' and p_data->>'provider_id' !~ '^[a-f0-9]{24}$' then raise exception 'Invalid provider ID'; end if;
  update public.job_comment_threads set provider_id=nullif(p_data->>'provider_id',''),
   delivery=case when coalesce(p_data->>'provider_id','')='' then 'uncertain' else 'sent' end
   where card_id=p_card and id=k returning * into r;
 else raise exception 'Unknown action'; end if;
 return jsonb_build_object('ok',true,'comment',to_jsonb(r));
end $$;
