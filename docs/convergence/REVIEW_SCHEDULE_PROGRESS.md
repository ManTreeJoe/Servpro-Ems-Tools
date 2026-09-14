# Windows workflow increments

Workflow increments included in Windows release 1.8.20. No production migration
or L OPS source change. See ../RELEASE_1.8.20.md for release boundaries.

## Implemented

- Job workspace groups existing sections into tabs without cloning controls.
  Integration actions, comment search, draft contents, and checklist handlers remain.
- Schedule presents readable entries and a field editor, retaining raw Run editing.
  The formatter preserves interior blank columns; dated entries use dated parsing.
  Word remains the source, with existing backups and conflict checks.
- Schedule offers multi-select from the canonical Snapshot technician roster,
  retains manually entered crew, and offers earliest/latest arrival time inputs.
  These are roster names, not account-linked mobile assignments.
- Weekly reviews use company, record, exact period, division, and responsibility
  in their identity. Each captures detached record evidence and available reviewer
  identity. Prior revisions and old general reviews remain preserved.
- Weekly Review is the default Analytics view. Local-only storage is labelled.
- Review rows show audit outcome, reviewer and date for the selected period and
  responsibility. CSV exports include audit identity, period and preserved source
  column; an unreviewed department does not inherit another department's stamp.
- Corrections are loaded from saved unresolved reviews across all periods, not
  restricted to today's Logs membership. Resolution requires a note and checks
  the saved revision; original evidence, prior revision, and snapshots remain.
- Weekly review/queue/correction views read THE LOGS - EMS: TO BE PRESERVED
  and CONTENTS CARDS. Exact card IDs open the workspace; no name matching.
  Each review and snapshot retains observed board/list/card membership.
  Read-only live check: 76 EMS cards and 44 Contents cards on September 11.
  These are card counts, not deduplicated Loss counts or historic membership.

## Not complete

- Shared database persistence, server authorization, multi-PC concurrency and live
  propagation for reviews and visits. Do not claim local review records are shared.
- Canonical scheduled visit IDs, member-based crew selection, safe job linkage,
  structured arrival windows, and generation of the legacy printout from visits.
- Department timing targets and shared review storage remain unfinished.
- Historical column membership cannot be reconstructed from today's stage alone.
  New review evidence only preserves state from the time the user reviews it.
- Real-data desktop walkthrough and office acceptance before release.

## Checks

Browser fixtures exercise workspace tabs and schedule editing without accessing
live customer systems. Python tests cover document save behavior and review
identity/evidence. These checks do not certify live integrations or migration.
