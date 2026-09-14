# Linguar Hub 1.8.20

Windows office update, September 14, 2026. This release changes Linguar Hub;
the separate L OPS application is not modified.

## Included

- Job workspace tabs retain existing tools, with the comment composer available
  at the bottom regardless of the selected tab.
- Whole-board zoom supports 50–140%, keyboard controls, and saved preferences.
- Schedule entries have arrival-window and crew selection controls while keeping
  the existing Run document, backups, and conflict checks.
- APA and Schedule can open the saved Word document in print preview. Microsoft
  Word is required; printing is initiated by the user, not automatically.
- Weekly Review records preserve exact source-card membership, review period,
  responsibility, reviewer, and evidence. Corrections remain available across
  periods with revision checks and resolution notes.
- Operations receives its embedded desktop bridge and returns to its home view
  when selected from the main sidebar.
- Backup scheduling recovers when a scheduled run overlaps an existing worker;
  SQLite sidecar files are not presented as backup snapshots.
- APA ignores late responses from older date selections and shows load failures
  without replacing the currently displayed document.

## Boundaries

- Weekly-review records remain local to each PC, not shared team audit records.
- This release does not migrate the database, apply new RLS policies, or perform
  bulk Trello comments, card movements, or payment confirmations.
- Crew selections are roster names, not mobile account assignments.
- Word/printer setup and each PC's network-drive access still need local setup.
- Code signing/Defender approval remains an IT deployment concern; a build and
  automated tests do not establish antivirus acceptance on every machine.

Customer-specific review reports and unapplied migration files are excluded.
