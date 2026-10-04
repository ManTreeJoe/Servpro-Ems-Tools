-- Administrator/service-only diagnostics. No tokens or customer content.
select enabled, last_started_at, last_finished_at, lease_until, not_before, last_error_code
from public.hub_trello_sync_control;

select s.label, s.enabled, s.last_metadata_at, s.last_attempt_at, s.next_poll_at,
  s.consecutive_failures, s.last_error_code,
  count(c.card_id) filter (where c.present) as active_cards,
  count(c.card_id) filter (where c.present and c.details_revision is distinct from c.revision) as details_pending,
  count(c.card_id) filter (where c.present and c.comments_completed_at is not null) as histories_downloaded,
  count(c.card_id) filter (where c.present and
    (c.comments_revision is distinct from c.revision or c.scan_revision is not null
      or c.comments_completed_at < now()-interval '1 day')) as histories_pending,
  count(c.card_id) filter (where c.present and c.comment_error_code is not null) as comment_errors,
  case when not s.enabled then 'disabled'
       when s.last_error_code is not null then 'attention'
       when s.last_metadata_at is null then 'not_started'
       when s.last_metadata_at < now()-interval '6 minutes' then 'stale'
       else 'metadata_current' end as board_health
from public.hub_trello_sync_sources s
left join public.hub_trello_mirror_cards c using(board_id)
group by s.board_id order by s.label;
