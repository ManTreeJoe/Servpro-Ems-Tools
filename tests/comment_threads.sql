-- Transaction-only integration checks against existing mirror/account scope.
-- No provider calls and no persistent user data mutations.
begin;
do $$
declare who uuid; card text; parent text; result jsonb; again jsonb; op uuid:=gen_random_uuid(); denied boolean;
begin
 select u.user_id,c.card_id,c.comments_json->0->>'id' into who,card,parent
 from public.hub_trello_mirror_cards c join public.hub_trello_sync_sources s using(board_id)
 cross join (select user_id,array_agg(department) departments from public.app_user_departments group by user_id) u
 where c.present and s.enabled and s.required_departments<@u.departments
 and cardinality(s.required_departments)>0 and s.reader_department=any(s.required_departments)
 and s.reader_workspace is not null and c.comments_json->0->>'type'='commentCard' limit 1;
 if who is null then raise exception 'No authorized fixture'; end if;
 perform set_config('request.jwt.claim.sub',who::text,true);
 result:=public.job_comment_threads('pin',card,jsonb_build_object('id',parent,'pinned',true,'expected',false));
 if not (result#>>'{comment,pinned}')::boolean then raise exception 'Pin failed'; end if;
 result:=public.job_comment_threads('reply',card,jsonb_build_object('parent',parent,'body','Thread integration test','operation_id',op));
 again:=public.job_comment_threads('reply',card,jsonb_build_object('parent',parent,'body','Thread integration test','operation_id',op));
 if result#>>'{comment,id}' is distinct from again#>>'{comment,id}' then raise exception 'Retry duplicated'; end if;
 if result#>>'{comment,author_id}'<>who::text or result#>>'{comment,parent_id}'<>parent then raise exception 'Identity failed'; end if;
 again:=public.job_comment_threads('read',card,'{}');
 if not (again->>'ok')::boolean or jsonb_array_length(again->'comments')<2 then raise exception 'Authenticated thread read failed'; end if;
 set constraints all immediate;
 execute 'set local role authenticated';
 if not exists(select 1 from public.job_comment_threads where card_id=card and id=result#>>'{comment,id}') then raise exception 'Authorized RLS read failed'; end if;
 execute 'reset role';
 denied:=false;
 begin
  perform public.job_comment_threads('reply',card,jsonb_build_object('parent',parent,'body','Changed retry','operation_id',op));
 exception when others then denied:=true; end;
 if not denied then raise exception 'Accepted operation reuse'; end if;
 denied:=false;
 begin
  perform public.job_comment_threads('reply',card,jsonb_build_object('parent','not-a-parent','body','Invalid','operation_id',gen_random_uuid()));
 exception when others then denied:=true; end;
 if not denied then raise exception 'Accepted forged parent'; end if;
 again:=public.job_comment_threads('claim',card,jsonb_build_object('id',result#>>'{comment,id}'));
 if not (again->>'claimed')::boolean then raise exception 'Claim failed'; end if;
 again:=public.job_comment_threads('claim',card,jsonb_build_object('id',result#>>'{comment,id}'));
 if (again->>'claimed')::boolean then raise exception 'Double delivery claim'; end if;
 perform set_config('request.jwt.claim.sub',gen_random_uuid()::text,true);
 denied:=false;
 begin perform public.job_comment_threads('read',card,'{}'); exception when insufficient_privilege then denied:=true; end;
 if not denied then raise exception 'Cross-account access allowed'; end if;
 execute 'set local role authenticated';
 if exists(select 1 from public.job_comment_threads where card_id=card) then raise exception 'Cross-account table read allowed'; end if;
 execute 'reset role';
 perform set_config('request.jwt.claim.sub','',true);
 denied:=false;
 begin perform public.job_comment_threads('read',card,'{}'); exception when insufficient_privilege then denied:=true; end;
 if not denied then raise exception 'Anonymous access allowed'; end if;
end $$;
select 'PASS: pin, immutable parent, idempotency, exclusive delivery claim, forged parent and unauthorized access checks' result;
rollback;
