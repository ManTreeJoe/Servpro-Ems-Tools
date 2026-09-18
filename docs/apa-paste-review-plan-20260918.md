# APA paste review — internal test build

## Approved workflow

1. Paste the full APA Monitor table on the selected APA date.
2. Parse job ID, claim, division and Initial/Final requirement independently.
3. Search Trello per row; show card and description for human verification.
4. Add a new pending entry, confirm an existing entry without changing its status, or skip.
5. Save queue progress locally and retain exact card links by entry, not customer name alone.

All initials route to Initial Uploads. Contents initials also use sub AARON. Contents finals route to PABLO. Both carry Contents in the entry. Other finals use normal lane suggestions. Same-name Water and Contents require an explicit separate-entry confirmation. No Trello mutations.

## September recovery

UI refinement: action buttons themselves confirm the review; no additional confirmation checkboxes. When same-customer entries exist, the new-entry button explicitly reads "Add separate entry". Exact duplicate rejection, stale-document checks, and failed-save protection remain. A single existing entry is preselected; multiple entries require selection.

On September 18, 2026, archived all 13 Word files found directly in the configured IE September APA folder. Zero unreadable files or backup failures. Originals remain untouched. Local archive: `%APPDATA%/Linguar Hub/apa_digital_archive`.

New APA writes archive the previous file and proposed replacement, verify hashes, then replace the live file atomically. Archive failure prevents overwrite. Monthly copies include readable paragraph/table JSON. Queue data lives in `%APPDATA%/Linguar Hub/apa_paste_review`.

## Test and rollout boundary

Test locally before release: initial/final routing, distinct Water/Contents, existing confirmation, skip, resume, offline retry, stale document rejection, repinning, backup failures, desktop/narrow layouts.

This is not a shared-database migration or an off-device backup. Existing Word documents remain the live APA source. Queue progress and links are per PC. Confirmation preserves existing placement/status; it does not silently correct old entries. Multi-PC conflict protection and shared durable identities remain the next digital-first phase. No production release included.
