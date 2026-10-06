begin;
-- Internal delivery boundary. Recipients come from saved membership/thread
-- identities, never caller-supplied recipient IDs. Membership grants no access.
create function oneloss_notifications.deliver_activity(
 p_actor uuid,p_card text,p_event text,p_body text,p_root text default null
) returns void language plpgsql set search_path='' as $$
declare job_key text; links integer;
begin
 if p_actor is null then return; end if;
 select count(distinct l.canon_key),min(l.canon_key) into links,job_key
 from public.job_links l join public.hub_trello_mirror_cards c
 on l.link_value in(c.card_id,c.payload->>'shortLink')
 where c.card_id=p_card and l.link_type in('trello_card','trello_card_contents','trello_card_recon');
 if links<>1 or not oneloss_notifications.can_access(p_actor,job_key,p_card) then return; end if;
 insert into oneloss_notifications.events(actor,event_key) values(p_actor,p_event) on conflict do nothing;
 insert into oneloss_notifications.inbox(recipient,canon_key,card_id,actor,event_key,kind,body)
 select candidates.user_id,job_key,p_card,p_actor,p_event,
  case when exists(select 1 from oneloss_notifications.people person,
   regexp_matches(p_body,'(?:^|[^a-zA-Z0-9_.@-])@([a-zA-Z0-9_.-]+)','g') token
   where person.user_id=candidates.user_id and lower(token[1])=person.handle)
  then 'mention' else 'comment' end,left(p_body,2000)
 from (
  select m.user_id from oneloss_notifications.members m where m.canon_key=job_key
  union
  select t.author_id from public.job_comment_threads t
   where p_root is not null and t.card_id=p_card and t.root_id=p_root and t.author_id is not null
  union
  select person.user_id from oneloss_notifications.people person,
   regexp_matches(p_body,'(?:^|[^a-zA-Z0-9_.@-])@([a-zA-Z0-9_.-]+)','g') token
   where lower(token[1])=person.handle
 ) candidates
 where candidates.user_id<>p_actor
  and oneloss_notifications.can_access(candidates.user_id,job_key,p_card)
  and not exists(select 1 from oneloss_notifications.preferences pref
   where pref.user_id=candidates.user_id and pref.canon_key=job_key and pref.muted)
 on conflict(recipient,actor,event_key) do nothing;
end $$;
revoke all on function oneloss_notifications.deliver_activity(uuid,text,text,text,text) from public,anon,authenticated;

create function private.notify_thread_reply() returns trigger
language plpgsql security definer set search_path='' as $$
begin
 if new.native and new.parent_id is not null then
  perform oneloss_notifications.deliver_activity(new.author_id,new.card_id,
   new.card_id||':'||new.id,new.body,new.root_id);
 end if;
 return new;
end $$;
revoke all on function private.notify_thread_reply() from public,anon,authenticated;
create trigger comment_reply_notifications after insert on public.job_comment_threads
 for each row execute function private.notify_thread_reply();

create function private.notify_card_placement() returns trigger
language plpgsql security definer set search_path='' as $$
declare event jsonb; message text;
begin
 if tg_op='UPDATE' and new.version=old.version then return new; end if;
 event:=new.events->-1;
 if event->>'actor' is null then return new; end if;
 message:=case when new.state='archived' then 'Archived this card'
  when new.state='deleted' then 'Retired this card'
  when event->>'from_state'='archived' then 'Restored this card'
  when event ? 'position' and not(event ? 'from_board') then 'Changed card order'
  else 'Moved this card' end;
 perform oneloss_notifications.deliver_activity((event->>'actor')::uuid,new.card_id,
  new.card_id||':placement:'||new.version,message);
 return new;
end $$;
revoke all on function private.notify_card_placement() from public,anon,authenticated;
create trigger card_placement_notifications after insert or update on public.app_card_placements
 for each row execute function private.notify_card_placement();
commit;
