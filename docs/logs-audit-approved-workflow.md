# Logs audit — approved workflow (2026-09-17)

Target: Linguar Hub Windows Analytics, not L OPS. No production publication
is authorized by implementation or testing.

- Audit every current To Be Preserved card against full available history.
- Carry previous findings forward; highlight changed evidence and require fresh
  confirmation for a new weekly period. Longer periods remain selectable.
- Every completed audit posts a dated, attributed Trello comment, including
  cards left in place or moved to Questions.
- Audited plus explicitly billed qualifies for the billed-month lane. Missing
  documents/initial notes remain recorded findings, not independent move blockers.
- Clearly not billed: leave in place. Uncertain/conflicting billing: Questions.
- Invoice creation is not billed evidence. Payment is separate from billing.
- Every division represented on a combined card must be billed. Use the final
  represented division's billed month. Separate cards move independently.
- Never infer billed month from a comment timestamp. Require explicit billed dates.
- Support individual confirmation and selectable batch confirmation after preview.
- Missing month lanes require separate approval to create, never automatic creation.
- AR matching: saved exact link first, then claim/job number plus division. Name-only
  candidates require confirmation; property units must not be merged by name.
- Conflicting Logs/AR evidence: show both and propose Questions for user approval.
- No AR match does not block clear billing evidence on the Logs card.

## Implementation checkpoint

Implemented: form/source suggestions, dated comment-only hold publications,
billed/Questions moves, department confirmations, exact-card evidence rechecks,
weekly carry-forward, batch previews/selection, explicit month-lane creation.

AR candidate search now reads the existing IE AR board, ranks exact links and
claim/job-number plus division/unit evidence, and requires explicit link confirmation.
Confirmed links load full history and compare explicit dated billing statements.
Conflicts require Questions or a recorded user resolution. Linked AR evidence is
rechecked before publication and moving; no live changes were made in tests.

Initial-note timing is calculated on the server from explicit inspection-completion
and note-sent timestamps: <=60 minutes is on time. Missing, negative, date-only,
or incompatible timezone evidence is unverified. Arrival/comment timestamps are
not substituted. WC status remains manual. Estimator/activity suggestions retain
sources and never default Contents ownership to Pablo.

Weekly Excel copy: the queue exports saved reviews for the selected period,
including saved history for cards already moved. Choose the original Weekly Audit
template and a new .xlsx destination. Existing files are never overwritten.
The original columns and day-count formulas remain; Audit detail contains full
notes, evidence sources, and publication status. Drafts are explicitly identified.
Export does not publish comments, move cards, or update the SharePoint original.

Still pending: shared-office audit storage and production user acceptance.
Current drafts/recovery records are stored on this PC. Free-form ambiguous dates,
ownership, and historical billing differences still require review; keyword matching
does not prove that a job is billed or paid. OC requires a separate verified mapping.
