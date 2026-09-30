-- A non-expiring claim prevents a retry or another PC from issuing a second POST.
-- Failed/uncertain external writes require reconciliation, never lease expiry.
create table public.ems_copy_reservations (
  canon_key text not null references public.jobs(canon_key),
  target_board text not null references public.app_job_boards(board_id),
  source_card text not null check (source_card ~ '^[0-9a-f]{24}$'),
  operation_id uuid not null default gen_random_uuid(),
  created_at timestamptz not null default now(),
  primary key(canon_key,target_board),
  check(target_board in ('5d8b8f4621038a7a93d6b27d','5d8b8fec49d37b1456a3f63b'))
);
alter table public.ems_copy_reservations enable row level security;
revoke all on public.ems_copy_reservations from public,anon,authenticated;
grant select on public.ems_copy_reservations to authenticated;
grant insert(canon_key,target_board,source_card) on public.ems_copy_reservations to authenticated;
create policy ems_copy_read on public.ems_copy_reservations for select to authenticated
using(exists(select 1 from public.jobs j where j.canon_key=ems_copy_reservations.canon_key)
  and exists(select 1 from public.app_job_boards b where b.board_id=target_board)
  and exists(select 1 from public.hub_trello_mirror_cards c where c.card_id=source_card));
create policy ems_copy_insert on public.ems_copy_reservations for insert to authenticated
with check((select auth.uid()) is not null
  and exists(select 1 from public.app_job_boards b where b.board_id=target_board and b.enabled)
  and exists(select 1 from public.hub_trello_mirror_cards c
    join public.app_job_boards b on b.board_id=c.board_id
    join public.job_links l on l.link_type='trello_card'
      and (l.link_value=c.card_id or l.link_value=c.payload->>'shortLink')
    where l.canon_key=ems_copy_reservations.canon_key and c.card_id=source_card
      and c.present and b.enabled and c.board_id<>target_board
      and c.board_id in ('5d8b8f4621038a7a93d6b27d','5d8b8fec49d37b1456a3f63b')));
