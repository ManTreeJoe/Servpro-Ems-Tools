# APA audit and digital-first plan

Date: September 18, 2026. Target: Linguar Hub Windows/internal app.

## Verdict

Move APA to digital-first, retaining the existing APA document format as an export/print product. Do not treat the current Word-backed implementation as safe concurrent office editing. Fix the safety gaps below before broadening rollout. No application changes, live document edits, Trello writes, or releases were performed in this audit.

This is a source-and-test audit, not a complete live desktop or installed-machine certification. It includes all APA-specific Python tests and targeted JavaScript handlers, not end-to-end Microsoft Word, Teams, email delivery or multi-PC acceptance testing.

## Evidence

- All 87 existing APA Python tests pass, including the recent lane fixes.
- Date-loading and drop/save JavaScript checks pass.
- Four additional isolated safety probes fail. The probes use synthetic data and temporary documents, never the live share.
- Probe file: `../tmp/apa_audit_probes.py` relative to the app repository. These are deliberately failing audit checks, not implemented fixes.
- Reviewed: apa_web.py, apa_logic.py, apa_web_assets/app.js, index.html, app.css, office_print.py, relevant persistence identity calls and APA tests.
- UI reference: https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md

## Confirmed failures: fix first

| Priority | Finding | Evidence | Required change |
| --- | --- | --- | --- |
| P1 | A stale second editor silently overwrites the first editor's changes. | Probe `test_stale_second_editor_cannot_overwrite_first`; `apa_web.py:1922` accepts whole-board content without a revision. | Revision-checked saves, conflict response, and per-item operations. Serialize saves in one client; detect stale writers across PCs. |
| P1 | Add-to-APA can report success while dropping an item assigned to an unknown lane. | Probe `test_unknown_lane_add_must_not_report_success_and_drop_item`; `apa_web.py:1195`. The new guard in save_doc does not cover this separate path. | One validation/save path for add, paste, edit, drag, auto-add, carry and refresh. Validate destination before writing. |
| P1 | Removing a lane changes how old documents are interpreted: its header and jobs become rows in the preceding recognized lane. | Probe `test_removed_lane_does_not_reclassify_history`; `apa_logic.py:413` recognizes only currently configured headers. | Archive lanes rather than delete them; preserve historical lane IDs/names and explicit migration rules. Block removal of populated lanes until a destination is chosen. |
| P1 | An unreadable Word document appears to be an empty, existing board. | Probe `test_unreadable_doc_is_not_reported_as_empty_success`; `apa_logic.py:423` catches the document-open failure and returns empty sections. | Distinguish missing, unreadable and valid-empty records. Fail closed, retain the last good view, block destructive replacement, provide retry/recovery. |

These are reproduced failure modes, not proof that a particular user's missing card is recoverable or lost. Recovery requires checking the actual saved document and backups before further overwrites.

## Additional code-verified gaps and risks

1. **Inconsistent working date.** Bulk paste (`apa_web.py:1371`) writes today; its UI reloads the selected date (`app.js:1148`). Estimator and all-estimator Teams summaries read today (`apa_web.py:546`, `579`). Trello Add intentionally jumps to today, but uses UTC `toISOString()` while Python uses local `date.today()` (`app.js:1430`), which diverges in the Pacific afternoon/evening. All actions need an explicit working date and local-date handling. A deliberate “Add to today” option should be labeled as such.
2. **No atomic document save.** `apa_logic.py:523` writes directly to the destination. An interrupted network write is a risk, not a crash scenario reproduced in this audit. Interim improvement: staged write, verification, recoverable replacement and last-good backup. Network-share behavior must be tested.
3. **Optimistic state outside drag/drop remains unsafe.** Edit and delete mutate local items; the edit dialog closes before awaiting the save (`app.js:811`). The recent drag rollback does not protect all other callers. Keep edits visible on failure, make retry explicit, and prevent export/share from claiming unsaved data is committed.
4. **Overlapping saves/navigation.** `saveDoc` replaces the current document with whichever response returns, unlike the sequence-guarded date loader. Slow saves can overwrite newer screen state or switch the displayed day. Add a save queue, captured document ID/date, and revision checks. Needs a dedicated asynchronous regression test.
5. **Identity is name-based.** Pins use a normalized customer key; parsing separates status/sub from display text. Same customer, multiple claims or divisions can collide. Notes are keyed by client plus section (`apa_web.py:1516`), so moves/renames can make notes appear absent. Store immutable item, job, division and external card IDs. Keep display names separate.
6. **Routing is only partially configurable.** Same-name saved lanes now route automatically, with deliberate existing aliases retaining priority. Substring rules and shared lanes still need an explicit mapping UI and a preview of the winning rule. Adding a lane is not a safe trigger to silently rearrange the entire board.
7. **Carry-forward depends on the nearest document within 14 days.** It stops at the first existing file. Status suffixes/highlight determine eligibility. With unreadable data this can carry nothing. Show a carry preview, source date, inclusion/exclusion reasons and duplicate prevention. Preserve prior days as snapshots.
8. **Print is Word-dependent.** `office_print.py:5` opens the saved DOCX in a separate Word instance; it does not build a PDF. `app.js:908` warns unsaved edits are excluded. Keep this interim workflow, then export from a committed revision with a print preview and PDF option.
9. **EOD is a compose link, not delivery tracking.** It builds a potentially long Outlook URL (`apa_web.py:1560`); Teams also uses compose/open workflows. Say “Open draft,” not “Sent.” Test long boards and URL limits, and provide copy/export fallbacks. No delivery failure was reproduced here.
10. **Workspace configuration and filtering require explicit scoping review.** APA uses one root path and generic settings keys; a franchise filter is not a permission boundary. Confirm storage, lane setup and operations are scoped correctly for IE/OC before shared multi-office deployment. This audit does not certify backend access control.

## UI/code accessibility findings

- `apa_web_assets/index.html:34` - Trello search has placeholder-only identification; add a persistent accessible name.
- `apa_web_assets/index.html:47` - item filter needs an explicit label/accessible name.
- `apa_web_assets/index.html:147` - save/status message has no live-region semantics; announce success/failure without forcing focus.
- `apa_web_assets/app.js:2433` - Manage Sections overlay needs dialog semantics, focus containment/return and a keyboard alternative to drag reordering.
- `apa_web_assets/app.js:2489` - lane addition/removal needs duplicate-name checking and populated-lane safeguards, not only a generic Save Order button.
- `apa_web_assets/app.css:117` and `:242` - important metadata/badges are 10–11px; increase readable text sizes without shrinking cards.
- `apa_web_assets/app.js:858` - whole-board rerender on edit risks scroll/focus disruption; update the affected record and preserve viewport/focus.

This is not an ADA/WCAG compliance certification. Computed contrast, screen-reader behavior, 200% zoom, high-DPI Windows and full keyboard walkthrough remain to be checked in the running app. Shared theme overrides must be included in those checks.

## Recommended digital-first structure

The Windows app remains the in-house app. This is a data/workflow change, not a request to rebuild it as a separate web app.

`APA records -> daily board / list -> committed daily snapshot -> print / PDF / Word / EOD draft`

- Store lanes with stable IDs, names, sort order, workspace, owner/type and archive status.
- Store items with stable IDs, linked job/division/card IDs, lane ID, status, next action, assignment, notes and revision.
- Store date membership/snapshots separately so yesterday's APA is not rewritten by today's lane changes.
- Record who changed what and when, with undo/recovery for moves and deletes.
- Keep routing rules separate from labels. Record the source rule and permit explicit manual routing overrides.
- Treat Trello as a mapped external source/mirror. Refresh in the background without replacing unsaved edits. Retain pending changes and expose conflicts.
- Use the shared application backend for office-wide records; a local cache can support offline work. Do not put a shared SQLite file on a network folder or treat independent local stores as synchronized.
- The Word/PDF file becomes output only. Import legacy files through an explicit migration flow; don't continue silently reading edits back from exported copies.

The exact backend schema/hosting choice needs a separate review of the shared application data layer. No database deployment is proposed as a prerequisite for the immediate safety fixes.

## Screen organization

- Top row: working date, workspace, Find job, Add, save/sync state.
- Views: Board and List, backed by the same records. Retain current fixed-size cards and per-lane scrolling.
- One Filters control: owner, stage, status, franchise, hide empty; show active filters and Clear.
- Lane menu: rename, reorder, owner/routing, archive. No silent destructive lane removal.
- Item view: job information, next action, status, owner, notes/history. Edit and Move alternatives alongside drag/drop. No long instruction blocks.
- Output menu: Print preview, PDF, Word, EOD draft, Teams draft. Make date and inclusion scope visible before output.
- History/recovery: undo recent action, prior daily snapshots, conflicts and failed saves.

## Delivery sequence and acceptance gates

### 1. Stabilize current APA
Fix the four reproduced failures, unify validation, correct date semantics, protect every mutation, and add save serialization/revision checks. Gate: two concurrent editors cannot silently overwrite; unknown lanes cannot lose cards; corrupt files cannot appear empty; lane archive preserves history; failures are recoverable.

### 2. Introduce structured storage behind the existing UI
Import a copy of a representative week including highlights, notes, pins, custom lanes, same-customer claims and carry-forward. Reconcile item counts and exact identities. Keep original files intact. Gate: record-for-record comparison and user approval before changing the authoritative store. Avoid indefinite dual-write systems.

### 3. Make daily operations digital-first
Create/open the day without requiring Word. Use typed statuses, stable IDs, archived lanes, next actions, explicit carry-forward and background sync. Gate: offline/reconnect, stale view, permission scope and multi-PC tests.

### 4. Preserve output and polish
Generate the familiar document layout from a saved revision; add PDF and unified share previews. Match date, item counts, ordering, highlights and wrapping. Gate: print on an office PC, long-name/large-board tests, page-break checks, keyboard and high-DPI/zoom acceptance.

### 5. Pilot, then release
Test on Nathan's device, then a second office PC with concurrent edits. Only after acceptance: installer/release. Current source tests are not proof that the installed build or every office workflow is ready.

## Immediate recommendation

Approve Phase 1 first, then structured storage and exports. Do not spend the next pass primarily recoloring the page. The highest-value improvements are reliable saves, explicit dates, stable identity and recoverable history; those support a cleaner UI and trustworthy printouts.
