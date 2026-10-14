begin;
-- Narrow author-only mutation; table UPDATE remains unavailable to clients.
create function private.edit_job_reply(p_card text,p_id text,p_body text,p_expected text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare r public.job_comment_threads;
begin
 if auth.uid() is null or not private.comment_card_access(p_card) then
  raise exception 'Card access required' using errcode='42501';
 end if;
 if p_body is null or length(btrim(p_body)) not between 1 and 20000 then
  raise exception 'Invalid reply';
 end if;
 perform pg_advisory_xact_lock(hashtextextended('comment-thread:'||p_card,0));
 select * into r from public.job_comment_threads where card_id=p_card and id=p_id for update;
 if not found or not r.native or r.author_id is distinct from auth.uid() then
  raise exception 'Author required' using errcode='42501';
 end if;
 if r.delivery <> 'sent' or nullif(r.provider_id,'') is null then
  return jsonb_build_object('ok',false,'error','Wait until Trello delivery is confirmed before editing this reply.');
 end if;
 if r.body is distinct from p_expected and r.body is distinct from p_body then
  return jsonb_build_object('ok',false,'error','This reply changed on another screen. Reopen it before editing.');
 end if;
 update public.job_comment_threads set body=p_body where card_id=p_card and id=p_id returning * into r;
 return jsonb_build_object('ok',true,'comment',to_jsonb(r));
end $$;
revoke all on function private.edit_job_reply(text,text,text,text) from public,anon;
grant execute on function private.edit_job_reply(text,text,text,text) to authenticated;
create function public.edit_job_reply(p_card text,p_id text,p_body text,p_expected text)
returns jsonb language sql security invoker set search_path='' as $$
 select private.edit_job_reply(p_card,p_id,p_body,p_expected);
$$;
revoke all on function public.edit_job_reply(text,text,text,text) from public,anon;
grant execute on function public.edit_job_reply(text,text,text,text) to authenticated;
commit;
