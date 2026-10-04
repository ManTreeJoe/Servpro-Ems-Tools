-- Re-evaluate catalog access after a board's workplace permissions change.
alter policy app_placement_read on public.app_card_placements
using (required_departments <@ array(select public.my_departments())
  and exists(select 1 from public.app_job_boards b where b.board_id=origin_board_id)
  and exists(select 1 from public.app_job_boards b where b.board_id=app_card_placements.board_id));
alter policy app_placement_update on public.app_card_placements
using (required_departments <@ array(select public.my_departments())
  and exists(select 1 from public.app_job_boards b where b.board_id=origin_board_id)
  and exists(select 1 from public.app_job_boards b where b.board_id=app_card_placements.board_id))
with check (required_departments <@ array(select public.my_departments())
  and exists(select 1 from public.app_job_boards b where b.board_id=origin_board_id)
  and exists(select 1 from public.app_job_boards b where b.board_id=app_card_placements.board_id));
