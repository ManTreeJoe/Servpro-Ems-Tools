# Create linked EMS WIP / Estimating copy

The EMS work-type section now has **Copy to board…** beside the existing **Link WIP / Estimating copy** action. The selected EMS card stays in place. The other main office board is chosen automatically; the user must choose an open section and explicitly confirm creation.

Scope: title and description copied to a new Trello-backed card, linked to the same OneLoss EMS job using the established `ems_card_copies.link_copy` validations. No second job is created. Checklists, attachments, members, labels, old comments and Job Logs are not cloned. Existing comment-sharing policy remains unchanged; live server mirroring was not exercised in these tests. Contents, Recon and other-office boards are excluded.

## Safety and recovery

- Source must be open and already linked as EMS; conflicting Contents/Recon identity is refused.
- Existing linked target opens instead of creating another card. Destination section is checked again on submit.
- A new shared `ems_copy_reservations` table is keyed by job and destination board. An authenticated insert (no offline fallback) happens before the Trello POST. Unique insertion chooses one caller across PCs.
- The reservation never expires automatically: a timeout/crash must not cause a second POST. The operation UUID in the copied description allows **Check / finish copy** to find the exact card and finish linking it.
- If no unique matching card is found, the workflow stops for review. Use **Link existing copy** if a person has already created the correct card. There is deliberately no automatic reset/re-create after an uncertain or definitively rejected POST; an administrator must investigate before clearing a reservation.
- Source card, job records and files are not moved/deleted. The UI refinement skills were used to keep the action within the existing job controls and inspect its dialog.

## Database verification

Applied additive migration `ems_copy_reservations` to the configured Linguar Hub project. No unrelated pending migrations were applied. RLS uses existing accessible jobs, saved source-card links/mirror and board permissions; anonymous reads and client UPDATE/DELETE are denied. No security-definer functions added.

Authenticated transaction tests verified allowed insertion, duplicate exclusion, and denial for an unlinked source; all test rows rolled back. Security advisor reported no findings for the new table. Existing unrelated notices remain: [admin security-definer functions](https://supabase.com/docs/guides/database/database-linter?lint=0029_authenticated_security_definer_function_executable), [leaked-password protection](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection), and two intentionally restricted server tables with [RLS/no client policies](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy). These were not changed by this feature.

## Tests / rollout

16 Python tests covering linking, duplicate requests, timeout recovery, failed-link recovery, unavailable DB, wrong lane and division isolation. Browser test covers explicit section choice, error recovery and existing-copy controls. No customer Trello writes performed. Source is ready for DEV testing; app has not been restarted or published.
