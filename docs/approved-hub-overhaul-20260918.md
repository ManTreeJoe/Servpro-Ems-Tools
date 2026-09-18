# Approved Linguar Hub overhaul

Status: product decisions approved September 18, 2026; implementation and verification pending.
Target: Linguar Hub Windows/internal application in this repository. L OPS is a read-only design/workflow reference. Test on Nathan's device before release. Preserve unrelated work already in the worktree.

## 1. Core job workflow

- Default New Loss to the current EMS Residential Trello template; retain explicit template selection.
- Diagnose CompanyCam project creation and automatic linking to the created job/card. Lock the reproduced failure down with a regression test before fixing it.
- Paint job information from stored DB records immediately. Refresh from Trello in the background without rebuilding the workspace or losing drafts.
- Preserve Hub edits when the same field changed in Trello; retain and flag the conflicting field. Merge nonconflicting updates quietly.
- Keep comments on the right. All / EMS / Contents / Recon toggles support multiple visible divisions. Preserve source labels and use one explicit posting destination.
- Run checklist action opens an Add to Schedule dialog for the job.

## 2. Digital schedule and run

- Store structured visits, multiple per job, each with date, arrival window, crew and work notes.
- Waiting/TBS/on-hold items remain undated until scheduled. Retain meaningful waiting sections.
- Compact rows; use L OPS scheduling as a reference after inspecting it.
- Print the schedule in the existing normal run-document layout and sections. Optional waiting-list section. Do not remove existing print capability during migration.

## 3. Billing and AR

- Diagnose the current inability to edit; verify actual read/write paths rather than treating the page's presence as functionality.
- Preview and reconcile a one-time Excel import, preserve the workbook backup, then maintain billing/AR in Hub's database. No ongoing Excel dependency.
- Support multiple invoices and partial payments per job/division; no whole-job billed/paid assumption from a single division.
- Adopt relevant L OPS billing layout/workflow after inspection.

### QuickBooks Online

- Official Intuit API/OAuth connection, server-side credentials, durable provider identities, retry-safe synchronization. No spreadsheet relay or browser automation.
- Prepare drafts in Hub, explicitly submit to QuickBooks, synchronize balances and payments back.
- Submit permission is explicitly granted to selected users. Preparing a draft does not confer submission permission.
- Posting and sending are separate actions. Submission must not implicitly email a payer.
- Billing Completed means SENT TO PAYER, not invoice creation or posting, and not payment.
- Support email, carrier portal and other delivery methods. External sends record sent date and method; optional receipt/reference. Hub sends record successful delivery/submission acknowledgement without claiming recipient receipt.
- Develop and validate in the QuickBooks sandbox before production accounting writes. Credentials, connected company mapping and hosting must be verified before integration rollout.

### Estimator ownership and billing-dispute carryover — planned only

Requested September 18, 2026. Record this requirement only; do not implement or change live assignments yet.

- When a job/card is in an estimator's lane, or an estimator takes responsibility for working on the job, link that person to the card as an estimator.
- Store the estimator relationship in Hub's database and show it on the job/card, using the same DB-first display and background-refresh approach as other job facts.
- Support multiple estimators and retain the relevant division association so EMS and Contents ownership can be distinguished.
- When a billing dispute is created for that job/division, automatically populate its linked estimator(s) from those stored relationships, without requiring the user to find and re-enter them.
- Before implementation, define the lane-to-user mapping, what evidence establishes "working on the job," and how reassignment/history should behave. Also confirm whether a visible estimator tag should be mirrored to Trello membership; automatic notifications are not implied by this request.

## 4. Analytics and Operations

- Inventory every metric/action, source record, fallback and missing-data state.
- Assess runtime behavior and data coverage separately; do not label either area 100% ready on the strength of a rendered page.
- Preserve weekly review rules and evidence references. Read current analytics status as a starting inventory, not fresh proof of readiness.
- Adopt appropriate L OPS layouts while keeping real Hub records and drill-downs.

## Delivery order and acceptance

1. Inventory/reproduction, then core New Loss/linking/DB-first job repairs.
2. Job workspace/comments and structured scheduling with print parity.
3. Database-backed billing/AR migration and editable workflow; official QuickBooks sandbox integration.
4. Analytics/Operations source coverage and UI completion, followed by connected end-to-end testing.

For each stage record what changed, what passed, what remains unverified, and any configuration needed. Local test build first; a release is a separate step. This document is approval of scope, not a claim that any feature above is complete.

## First implementation pass — September 18

Implemented in Hub (no L OPS edits or release):

- New Loss prefers the live EMS Residential template in both entry dialogs. Assignment parsing preserves the chosen template.
- New Loss publishes the created CompanyCam project as a Trello URL attachment, reuses an existing exact attachment on retry, and reports an incomplete link separately from successful card creation. Existing description links remain supported.
- Successfully opened exact-card workspaces have a local SQLite read projection, scoped to service, signed-in user, franchise, card and division. Reopening reads this before the network. Job edits invalidate it; a read begun before an edit cannot repopulate the old projection. This is not a primary database migration.
- Comments remain on the right across job tabs, with an independently scrolling history and persistent composer. Narrow windows stack the pane. EMS/Contents/Recon filters use linked card IDs; posting has its own explicit division selector. The follow-up changes the view to exactly one division at a time (no All). Missing/conflicted links are not searched by customer name.
- Unchanged workspace refreshes preserve the existing DOM. Comment refreshes preserve drafts/search and do not discard newly posted messages when an older request finishes. Fixed CSS that kept search-filtered comments visible.

Verification: 127 focused Python tests passed, plus five browser scripts: job_conversation, job_comment_dock, job_workspace_tabs, trello_import_entry, jobs_move_prompt. Python compilation, JS syntax checks and git diff whitespace checks passed. Two existing datetime.utcnow deprecation warnings remain. Browser tests render the production job modal with mocked APIs, including exact posting destination, offline refresh and stale-response cases; they do not certify live Trello writes.

Still pending in this stage: live New Loss end-to-end verification, a durable retry queue for partial provisioning, uncached first-open latency, background updates to changed non-comment sections without rebuilding, and field-level shared-edit conflict handling. Schedule/print parity, editable DB-backed Billing/AR, official QuickBooks sandbox integration and Analytics/Operations coverage remain subsequent work. No production accounting or customer-record writes were made by these tests.

## Follow-up: shared intake and saved-data reads

- Embedded Operations opens the same Jobs New Loss dialog inside the Hub. It does not launch a separate tool window. Standalone Operations retains its compatibility launcher.
- New Loss suggests the card title from customer/carrier without overwriting a customized title. Both names and intake facts are recorded together on the linked Hub job.
- Signed-in CompanyCam calls use the authenticated gateway before any old PC key. Writes require a connected personal account and do not fall back to the PC key after a gateway error. The gateway itself was not deployed or changed in this pass.
- CompanyCam and XA actions consult stored job destinations first. Folder actions consult the DB pin before the displayed hint; exact-card actions do not substitute a name-based pin. Missing provider links still have a Trello compatibility fallback.
- Job Info opens stored values without waiting for Trello. Editors send only changed fields; untouched values are not mirrored over newer Trello data. Existing Trello-to-job sync remains responsible for importing external changes.
- Cold job workspace reads use the selected card's saved identity, not a fuzzy customer match. Saved folder paths are present in that first response. Warm opens retain the scoped SQLite projection.
- Fixed a menu focus/hover rule that left the CompanyCam submenu covering the comment controls after selection.

Read-only live verification: Nathan - Cool beens has an exact saved job, a saved folder, and CompanyCam project 114863521. No duplicate project was created. Automated browser checks use mocked APIs; a live creation/write still needs acceptance testing.

Follow-up verification: 155 focused Python tests passed. Browser scripts passed for job_conversation, job_comment_dock, job_workspace_tabs, trello_import_entry, jobs_move_prompt, operations_new_loss, operations_embedded and intake_embedded. The last test loads the actual Jobs HTML and iframe bridge, opens the shared intake via the shell's readiness handler, and confirms the intake-only surface does not load an unrelated board.

App-wide requirement: every previously stored fact and action destination must read from Hub's DB/projection first, with provider refresh outside the initial render. This pass verifies the job workspace, Job Info and destination actions; it does not certify every legacy APA, Schedule, Analytics, Billing or Snapshot data path. Those remain part of the staged overhaul, not an implied complete database migration.

## Follow-up: keep open cards populated and dialogs stable

- Reproduced the disappearing-card bug: the fast response replaced the board preview with a less complete modal, and the later full response replaced it again. Background hydration now prepares bound sections off-screen and patches only changed sections of the existing card. Known facts survive incomplete projections. The composer, active workspace tab, scroll positions, focused fields and edited sections remain in place.
- Cold opens include already-stored comments and checklists alongside exact-card facts. Warm opens continue reading the scoped local SQLite projection. Newly discovered verified division links become available without replacing the composer; comment mutation versions still reject stale refreshes.
- Ordinary card opens no longer invoke the folder audit or document-directory walk. They display the saved audit; **Run audit** performs the explicit deep refresh, also updating the open workspace in place. No saved audit is reported as unknown, not as a clean result.
- A failed Trello read retains last-known comments, checklists, attachments and facts in the saved projection. The card reports that the Trello refresh is unavailable rather than claiming it is up to date.
- Reproduced release-outside dismissal in job cards and Job Info. Removed backdrop-dismiss handlers from the shared form modal and related Jobs, APA, Audit, Snapshot, Disputes and Job Notes forms. Explicit Close/Cancel and existing draft guards remain. Context menus and photo viewers retain their separate dismissal behavior.

Verification: 155 focused Python regression tests passed, then the additional offline-projection regression and its suite passed (43 tests). Ten browser scripts passed: popup_click_retention, job_workspace_incremental, job_conversation, job_comment_dock, job_workspace_tabs, trello_import_entry, jobs_move_prompt, intake_embedded, operations_new_loss and operations_embedded. The popup test exercises five production popup implementations; the incremental test drives the actual card-open path, delayed partial/full responses, changed action bindings, linked divisions and checklist/draft retention. These browser APIs are mocked and are not proof of live provider writes. Python compilation, JavaScript syntax checks and diff whitespace checks passed; two pre-existing datetime deprecation warnings remain.

This completes the background non-comment section refresh item from the first pass. Shared-edit conflict resolution, truly uncached shared-database latency and the broader staged overhaul remain separate work. No release or production customer-record edits were made by this verification.

### Loading-state polish before release

The delayed-response browser regression reproduced three remaining hiccups: resetting the selected checklist responsibility, collapsing expanded Job Log evidence, and hiding saved documents behind a partial-loading placeholder. Refresh now copies reader-owned selection and expansion state before comparing/replacing a section. Saved files remain visible during partial hydration; a missing document index offers an explicit audit instead of claiming a scan is running. The new job_workspace_loading_state regression went red on all three symptoms and passes after the fix. Estimator ownership/dispute carryover above remains plan-only.

Focused verification for this polish: 79 Python tests and six production-UI browser scripts passed (loading state, incremental hydration, workspace tabs, conversation, comment dock and popup retention). JS syntax and diff whitespace checks passed. Two existing datetime deprecation warnings remain. This is loading-fix verification, not an assertion that all pending overhaul work is release-ready; no push was performed.

## Release audit — 1.8.21

The user authorized a quick audit and distribution through the normal Main update flow. Baseline: released v1.8.20. The newer origin/main documentation commit f1382ba is retained. This release does not implement the remaining overhaul or estimator ownership plan.

### Standards

Two findings, both corrected before packaging:

- A hidden required audit division could block preview without a visible remedy. The spreadsheet scope field remains removed; a Division for filing choice appears only when source evidence cannot resolve it, with preview directing the reviewer there.
- Merely opening a saved audit triggered an unsaved-change warning. Close/Queue now compare current values to the saved form snapshot.

### Spec

The parallel spec review found one recovery blocker, corrected before packaging: after posting a verified audit comment, changed evidence could block the move and strand the review. A fresh reviewed save can supersede the old operation only after verifying the exact posted comment and unchanged source lane. History is retained; a new preview and explicit confirmation are required. Uncertain/unposted operations cannot use this recovery path.

Additional release testing found and corrected an APA identity collision between Initial and Final rows for the same job. New-entry stable identity preserves requirement and source job ID, keeping links separate without rewriting existing documents. The full suite also exposed two Snapshot/Quick Import forwarding methods that rejected exact-card arguments; both now forward the shared action contract.

Summary: Standards 2 findings resolved (worst: hidden required choice blocked preview); Spec 1 finding resolved (worst: posted-comment recovery deadlock). No unresolved blocker identified in these reviews; this is not certification of every live integration or pending overhaul feature.

### Final verification and package

- Full Python suite: 3,549 passed; two existing datetime deprecation warnings.
- All 22 browser regression scripts passed, using production renderers with mocked APIs.
- Dependency consistency, sanitized shipped config audit and staged whitespace checks passed.
- Fresh PyInstaller bundle and Inno Setup installer built for 1.8.21. Bundled module inventory, version and changed JS assets verified.
- Packaged Windows app started under an isolated test profile; its home page returned HTTP 200 and version 1.8.21. No startup error/traceback found. Test process stopped afterward; user dev instance was not stopped.
- Installer: Linguar-Hub-Setup-1.8.21.exe; 38,435,493 bytes; SHA256 492c42963cc729206fad42770c6bf1b75fadce57de4ab64c3a7340057f24c5d3. Unsigned: IT allowlisting may be required.
- No production provider writes were performed by the test suite; no database migrations are included. Shared server schema changes and one-off customer audit scripts are intentionally excluded.
