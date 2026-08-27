# Linguar Hub usage and interface audit — 2026-08-27

## Evidence reviewed

- 3,861 privacy-safe UI events over 21 active days.
- Current Trial Pipeline job card and shared Audit/Snapshot job card.
- Existing DocuSign request, reminder, signed-packet import, CompanyCam, and
  job-folder flows.

## What the usage shows

- Audit is the daily center of work (2,887 events), followed by Snapshot (770).
- CompanyCam pull, OD folder, Import, Trello, Copy name, Stage for XA, claim
  number, and folder path are frequent actions and must remain easy to reach.
- Pipeline has only just entered Trial, so its low historical count is not
  evidence that it should be removed.
- Settings, Run Doc Editor, Health, Cheat Sheet, and Exceptions are occasional
  tools. They should remain available but not compete with daily job work.

## Cleanup applied

1. Consolidated the repeated copy buttons under one visible `Copy…` menu.
2. Made the Pipeline card the single job workspace instead of adding another
   standalone signing tool.
3. Added one compact `Documents & Signatures` section for DocuSign state and
   the official X: OD job-folder files.
4. Collapsed run activity and miscellaneous Trello attachments by default.
5. Kept the heavily-used CompanyCam, OD folder, Import, Trello, and XA actions.
6. Kept signed files out of the database; the shared X: OD folder is the system
   of record.

## Next cleanup after Trial feedback

- Fold the old standalone DocuSign/Trello request controls into the new job
  section once direct DocuSign sending is live.
- Move occasional panels behind a single `More tools` navigation group for
  regular users; retain direct access for admins.
- Replace raw or duplicate close buttons in modals with one consistent close
  treatment.
- Add usage tracking to every new Pipeline action before deciding whether to
  remove it.
- Do not delete established tools solely because their historical usage is low;
  first verify that their background automation has a replacement.
