# L OPS platform / EMS Tools coordination

Status: October 5, 2026. This file is the canonical cross-chat handoff.

## October 5 — historical Run backfill proposed (not deployed)

Nathan requested several months of Run history. Source library located at the
configured EMS Daily Run OneDrive directory; proposed initial window July 1 through
October 4, 2026. Do not use active schedule bulk import for historical documents.
It would turn historical waiting rows into current work and cannot faithfully
represent repeated daily observations of the same job.

Shared-backend coordination proposal: separate office-scoped historical Run documents
and their dated source rows from active visits. Preserve all source sections,
raw text, source digest, original row identity, cancellation markings and reviewed
job links. Scheduled work is not evidence of completion. Repeated pending/TBS/hold
rows belong to each historical day, not today's waiting queue. Exact file retries
must deduplicate; changed versions must be retained for review, not overwrite history.
Calendar/Legacy history should be read-only initially, with unresolved links visible.
L OPS should consume this history separately from active schedule visits. Schema
and API agreement is required before implementation; no migration or history writes
have been made for this request.

## October 5 — live schedule drop fix

Branch: `handoff/paperclip-source-20261003`. Live calendar and Legacy drops now
save the move directly through the existing revision-checked schedule API instead
of opening the preview editor. Ordinary clicks still edit. Saving has status
feedback; failures refresh the saved placement and display an error. No schema,
Trello, Word, or L OPS changes required. Sample-only preview retains its edit-on-drop
flow. Browser regression tests cover direct drop, click editing, failed move, and
Legacy movement; calendar renderer and sample-preview tests also pass.

## October 5 — bulk import correction implemented in DEV

Nathan rejected mandatory per-line linking and approved importing the whole Run,
auto-linking strong job/Trello matches, retaining unmatched rows on the calendar,
and correcting links afterward. Planned shared contract change: permit a null
schedule visit job_id for an imported/unlinked entry, retain an explicit display
title and source identity, and provide an authorized revision-checked save/link
operation plus an atomic bulk import. Office membership remains mandatory even
without a job link. Link changes must validate both the old and new job's office.
Existing visits must not be silently overwritten or duplicated. No fake jobs,
Trello card creation or original-document writes. L OPS remains untouched; its
future consumer must support nullable job links and display needs-link states.
Branch: handoff/paperclip-source-20261003. Deployment and tests follow below once
verified; this section publishes the schema decision before implementation.

Implementation update: `20261005154121_schedule_bulk_import.sql` applied to
OneLoss/Linguar Hub. Added nullable job links, entry_title/source_key, v2
`save_schedule_entry` and atomic `import_schedule_entries`. Existing v1 save
remains available for linked visits. Direct writes stay denied; RLS allows only
office-authorized unlinked entries or authorized linked jobs. Link changes and
edits use revisions and append-only receipts. Source identity is immutable.

The .docx dialog now has one **Import all** action. Unique normalized full-name
and street-address evidence auto-matches existing jobs; ambiguous/conflicting
evidence stays unlinked. Existing saved `job_links` Trello pins follow the job—
this does not create/repin external cards or fuzzy-match directly against Trello.
Unmatched entries persist and show Needs link in calendar and Legacy. The visit
editor can search/change/remove its job link and edit an unlinked entry title.
Retries of the same source reuse rows, preserving subsequent edits. An already
active matched job is not overwritten; its new source line is retained unlinked
for reconciliation. Dates absent from Upcoming remain TBS with a review note;
unsupported sections are retained in On Hold with the original section in notes.
Crossed-out lines are counted/skipped. Tables remain explicit manual-review text.
Raw text is retained in notes; crew is not guessed from ambiguous abbreviations.

Validation: 51 Python tests passed; calendar/Legacy and live browser suites passed.
Isolated PostgreSQL tests cover unlinked saves, retries, duplicate handling,
link/unlink, stale edits, forbidden cross-office links and atomic batch rollback.
Signed-in read-only checks found 510 authorized jobs and confirmed saved Trello
links could be read. Live schedule load succeeded after migration; no real Run
entries were inserted by tests. Database changes and documentation are shared;
L OPS consumer adaptation remains future work. This is DEV, not an app release.

## October 5 — Schedule document import

Added **Import document** beside the live Schedule search. A native file picker
reads a .docx Run into a review dialog, with an explicit MM/DD/YY Run date.
Each recognized line can be linked to a real job and opened in the existing visit
editor. Save draft uses the same revision/idempotency/RLS path as manual visits.
This is reviewed line-by-line import, not unattended bulk matching.

Work/Monitor use the reviewed Run date. Upcoming requires its date to be entered;
TBS, Pending and Hold remain undated. Original line text and filename are retained
in notes. Crew and activities require review; only an explicit Monitor section
proposes Monitor. Crossed-out rows and unsupported sections such as Marketing are
flagged/skipped, not silently converted. Tables are displayed for manual review;
tracked changes/text boxes warn that original-document review is needed.

No Word edits, Trello posts, job-fact changes or database migrations. Existing
active visits cannot be overwritten through import. Stable source-row UUIDs plus
the database's one-active-visit constraint prevent blind duplicate creation.
Changed documents need fresh review. The source is read from one bounded byte
snapshot; compressed and expanded document sizes are limited. UI-design guidance
kept the existing dialog/editor workflow. Parser/picker tests verify unchanged
source bytes, repeatable IDs, waiting groups and cancellation. Browser tests cover
file review, skip state, linking, editor handoff, saving and Saved feedback.
Supported input in this first version: Word .docx, not legacy .doc or PDF.

## October 5 — approved OneLoss-owned schedule drafts

This section supersedes the readiness/coordination blockers below. Nathan approved
OneLoss as owner and explicitly allowed L OPS to be rewired later because nobody
uses it yet. L OPS and its database are untouched. Branch:
`handoff/paperclip-source-20261003`.

Implementation: `schedule_store.py`, dedicated `schedule_load/search/save` desktop
methods, and `schedule_live.js` wire the existing calendar/Legacy editor to real
job UUIDs. DEV uses `calendar_preview.html?live=1`; without that flag the original
sample UI remains available for isolated tests. Installed Main is unchanged.

Database contract: additive migration `20261005150008_oneloss_schedule_drafts.sql`
creates `schedule_visits`, append-only `schedule_changes`, and
`save_schedule_draft(p_command jsonb)`. Signed-in office membership plus the job's
department are checked server-side. Direct client writes are denied. Exactly one
active visit per job; revision conflicts reject stale edits. Identical retries use
the same operation UUID. Optional `before_id` applies ordering atomically with the
save; clients cannot supply numeric positions. Job facts are never updated here.

L OPS integration later: use this contract or an agreed adapter, preserve canonical
OneLoss job/visit IDs, resolve account/office mappings, and use user authorization.
Do not mirror these drafts into test-only daily-run rows. Keep Supabase Storage
and CompanyCam for files; this change does not move files or change media APIs.

Scope: persistent active drafts, all waiting groups, per-activity crews, calendar
and Legacy drag/reorder, real-job search, read-only job facts. Confirmation,
Trello/board movement, comment posting, printable Run output, history UI and
cancellation/rescheduling controls remain follow-up work. No Word writes. The
calendar starts empty until real visits are explicitly added; there is no automatic
Run import or synthetic data inserted into the live database.

Validation: isolated PostgreSQL tests cover saves, revisions, retries, duplicate
prevention, invalid payloads, history, cross-office reads/writes and direct-write
denials. Python tests cover payload validation and bound-account transport.
Browser tests cover existing layouts/dragging and live-mode save failure/retry.
Deployment: applied successfully to OneLoss/Linguar Hub (`oqwwapqnzzhefqxobadl`)
on October 5. Verified both tables have RLS enabled and authenticated users have
SELECT but no direct INSERT/UPDATE/DELETE grants. The signed-in desktop loaded
the empty live schedule and searched authorized jobs successfully. No real visits
were created by tests. DEV launched the live route with three day columns and
loaded theme assets. Source publication is not an installed-app release.

Security advisor reported no schedule findings. Separate existing findings remain:
[admin security-definer RPC review](https://supabase.com/docs/guides/database/database-linter?lint=0029_authenticated_security_definer_function_executable)
and [leaked-password protection disabled](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection).
Those were not changed as part of scheduling.

### Same-day addition: near-real-time multiuser calendar

Nathan requested immediate cross-user updates. Additive migration
`20261005151551_oneloss_schedule_realtime.sql` enables `schedule_visits` in the
existing `supabase_realtime` publication. Applied successfully. Two independent
authenticated subscriptions reached PostgreSQL-subscription-ready status against
the live service without modifying records. The browser uses the documented
Phoenix v1 protocol with the user's short-lived JWT, table RLS and office filter;
no service credentials. Credentials refresh every minute, heartbeats detect dead
connections, and reconnects trigger a full read to recover missed events.

Events trigger a debounced authorized reload, not direct trust in event payloads.
There is a 15-second backup refresh and visibility/online catch-up. Healthy
connections should update shortly after a committed save; this is not an SLA or
simultaneous field-by-field co-editing. Unsaved editor content is preserved and
stale saves remain rejected. Incoming updates wait during dragging. A Live /
Reconnecting / Offline indicator shows connection state. Browser tests simulate
remote edits while an editor is open and verify local text is retained. A real
two-person save/observe test remains for Nathan and Sam in DEV.

## October 5 — live schedule readiness check (read-only)

Update: Nathan approved OneLoss/Linguar Hub as the canonical schedule backend.
`schedule_records.py` now defines a validation-only draft save envelope, covered
by 32 passing tests in `tests/test_schedule_records.py`. It performs no database
or external writes, is not wired to the sample UI, and is not a security boundary.
No migration has been created or applied. Server-side enforcement and the
adapter/UI connection remain pending cross-app contract review and implementation.
Reordering requires a separate atomic server operation; client position values
are deliberately not accepted by the visit save payload.
Implementation starts with a draft persistence contract; no automatic L OPS
writes, database merging, Word writes, board movement or comment posting.
Existing OneLoss job UUIDs and department access are authoritative. L OPS must
consume the agreed contract with verified identity mappings rather than write
its test-only daily-run rows as production data.

Draft v1 contract for cross-app review: persistent visit UUID + job UUID,
department, lifecycle (active/completed/canceled), queue (scheduled/tbs/pending/hold),
Run group, optional date/arrival label, activities with independent people,
equipment/access/notes, ordering, revision and actor-attributed change history.
Exactly one active visit per job; canceled/completed records remain history.
Save uses expected revision and a retry identity; requests never write job facts.
Authorization, allowed groups and payload limits must be enforced server-side.
Confirm day and posting require separate idempotent operations, not side effects
of a draft save. Deployment remains pending migration tests and cross-app review.

Nathan requested connecting the agreed calendar/Legacy layout to real persistent
schedule data. No layout redesign, Word write-back or Reconstruction expansion.

Verified against public information_schema metadata: OneLoss/Linguar Hub has no
public tables whose names contain schedule, visit or run. The L OPS database has
`workspace_job_visits` and `workspace_daily_run_rows`. The latter enforces
`CHECK (is_test)` and must not be repurposed for real scheduling by bypassing it.
Existing visits require an HH:MM time and use one crew string; they do not directly
represent the agreed optional arrival, undated waiting queues, and per-activity
assignments. The current L OPS main source at
`1fd31841bc2bf05320776536218482fd207058af` contains the older visit migration and
actions, but its migration tree lacks the live daily-run table and the additional
visit source-log/workstream fields. Source/deployment parity needs reconciliation.

Decision required before writing live data: which backend owns the canonical
schedule, and how the existing OneLoss job/account/workspace identities map to it.
No schema or data was changed during this inspection. Do not solve missing fields
by inventing arrival times, flattening independent crews, storing production work
as test rows, or connecting the new calendar to Word persistence.

Recommended decision to Nathan: start with the current OneLoss database as the
schedule owner for existing OneLoss jobs/users, publish the versioned contract,
and coordinate L OPS consumption/mapping before cross-app writes. This is a
proposal, not permission to create a competing schema or an accepted migration.
If L OPS instead owns persistence, require its current source/migration handoff
and explicit identity/auth mapping before implementation. Await Nathan's backend
direction and the previously required cross-app contract agreement.

## Code handoff — October 3

The team source snapshot is on `handoff/paperclip-source-20261003`, including the
previously unpublished desktop, storage, Trello sync and migration source plus
tests. Use that branch for Paperclip; see the publication update in
[paperclip-handoff.md](paperclip-handoff.md). This publishes existing WIP, not a
new shared-schema decision or live deployment. L OPS should inspect identity and
contract compatibility before using any SQL or enabling writes. Targeted Python:
60 passed; CompanyCam and Run activity Node checks passed. Storage SQL test blocked
by missing local PGlite dependency. No production release.

## Start here — Paperclip / new-agent onboarding

Read [paperclip-handoff.md](paperclip-handoff.md) for the mission, latest verified
DEV status, product decisions, ownership, next-task queue, and unpublished local
work inventory. Latest feature checkpoint: `3413dd0`, branch `main-lops-style-pivot`.
The calendar and Legacy drag UI exist as sample-only DEV functionality; digital
persistence, Confirm/Post and production print/PDF are still unfinished. Earlier
dated status notes below are historical. No release or schema deployment is
authorized by this documentation handoff.

## Active handoff — October 2, 2026

Owner: OneLoss/shared-backend chat. Branch: `main-lops-style-pivot` in
`ManTreeJoe/Servpro-Ems-Tools`. Base revision: `a495016` (release 1.8.26).
This handoff is documentation only; it does not publish an app release.

### Responsibility and communication

- This chat owns OneLoss desktop and shared-backend integration.
- The other-computer chat owns L OPS web/mobile in `ManTreeJoe/l-ops-crm`.
- Read this file from the latest remote branch before shared work. Record each
  handoff here with branch/revision, changes, database decisions, validation,
  required changes in the other app, and next owner/action.
- Shared schema/API changes must be proposed in GitHub and agreed by both sides
  BEFORE implementation. Acknowledgement is not approval. Deployment remains
  a separate action, not implied by pushing a proposal.
- Use linked PRs/comments for discussion and consolidate accepted decisions
  here. GitHub does not automatically deliver messages into either AI chat.

### Database and file decisions

- Supabase Storage and CompanyCam hold files for now; our own server comes later.
- Do not merge databases or assume existing job IDs/auth/workspaces match.
  Agree canonical IDs and explicit mappings; never join on display names alone.
- Before a schedule migration, agree source-of-truth project, existing tables
  to reuse, tenant/RLS rules, site-local dates/timezone, revision conflicts,
  idempotent confirm/post actions, audit history, and rollback compatibility.
- Store stable provider/object references, not expiring signed URLs. Keep
  credentials and customer documents out of GitHub.
- No database changes were made for this handoff.

### Schedule scope awaiting shared contract

- Main view: seven-day weekly calendar, weekends, week navigation, Today, and
  scheduling directly onto future days.
- Legacy view: familiar Run layout with editing/reordering and direct print/PDF.
  Same saved records as calendar and job log. NO Word dependency. Existing
  documents may be imported as copies only; never edited as the source of truth.
- One upcoming visit per job, multiple activities and per-activity assignments.
- Draft -> Confirm day updates board placements -> separate explicit Post to
  comments/job info. Board moves do not rewrite visits; board-to-draft pull is
  explicit.
- TBS retains entry date; Pending retains start date and remains visible on
  subsequent days only while unresolved.
- Canceled visits retain placement and history, flag rescheduling, and remain
  linked to their replacements.
- Monitor can be a main lane/activity or an extra without moving the WIP card.
- Reconstruction scheduling is ON HOLD. Preserve current behavior.

### Actual implementation status (not a completion claim)

The current `run_doc_editor_web.py` still loads/saves Word-backed days and prints
the original document. The requested digital weekly calendar is not implemented.
Do not wire the new web/mobile schedule to that Word-backed persistence.

Existing local work outside this documentation commit includes Card Details
movement history, exact notification aliases, division detection, profile source
refresh, and a document-storage pilot. These are NOT included in this handoff
commit and must not be assumed available in this remote revision. The previously
reported document pilot is gated; its live migration/enablement state must be
reverified before another client uses it. No new shared schedule schema exists
from this handoff.

### What L OPS must update / reply with

1. Acknowledge ownership and provide current branch/revision and migration head.
2. Link the actual job, visit, job-log, workspace/auth, and file-reference models.
3. Propose canonical identity mapping and shared source-of-truth project first.
4. Review the schedule requirements above and identify compatibility gaps.
5. After agreement, implement web/mobile against the versioned shared contract
   and common fixtures; do not independently create competing schedule tables.

OneLoss will reconcile that response before implementing a shared migration.
UI-only work and isolated tests need not change live data while review is pending.

Validation: documentation-only diff/whitespace review. No runtime tests or
deployment are claimed. The older linked L OPS guide below was not present in
the local checkout during this handoff; L OPS should confirm current guide paths.

### Follow-up: weekly-calendar presentation slice

Owner: OneLoss. Branch: `main-lops-style-pivot`, following `a2195a2`.
Status: isolated UI implemented/tested; NOT connected to the live Schedule.

- Added `run_doc_editor_web_assets/weekly_calendar.js` and `.css`: seven-day
  calendar, week/Today navigation, selected day, add/edit callbacks, search,
  TBS/Pending lists, loading/error/retry states, and a basic Legacy day view.
- Both views render the same host-provided collection. No Word, network,
  persistence or schema calls. The module never mutates host records.
- The input shape is a presentation adapter, NOT an approved shared schema.
  The host must supply authorized records, resolve pending state for the
  selected range, fence stale loads, and implement edits/persistence.
- Remaining: live data adapter, editor, ordering, original Run-style print/PDF,
  draft/confirm/post flow and shared schedule/job-log persistence. This basic
  Legacy view is not yet the complete original-document layout.
- `tests/weekly_calendar.cjs` passes using headless Edge: seven days/weekends,
  callbacks, same-record updates across views, queues, search, loading/retry,
  date boundaries, text escaping, narrow layout and teardown. Desktop/narrow
  screenshots inspected; retains OneLoss theme tokens and compact controls.
- L OPS: review shared contract questions above; do not build tables from this
  renderer's input shape. No action required in mobile/web for this isolated UI.
- No shared schema changes, app cutover, Reconstruction changes or release.

## Prior reference notes — September 14, 2026

### Latest design selection — B without an hourly grid

Nathan selected the three-day schedule with a persistent right-hand waiting
panel. Most visits have no set time: a date is sufficient to be scheduled.
Show an arrival-window label only when provided; do not show "Time not set".
TBS means no scheduled day, not a missing arrival time. Day lists retain Monitor
and Work To Be Performed; the right panel contains all seven Run waiting groups
and scrolls independently. On narrow windows it stacks below the dated work.
The layout comparison chooser is removed from the sample DEV page.

Compact toolbar follow-up: range (3 Days/Week/Month), queue selection and selected
date moved into a Filters disclosure. Selected range is a pill; queue pills can
be cleared. Date arrows, Today, search and Legacy remain visible. Escape and
outside-click dismiss the dropdown. Both browser suites pass, including filter
selection, clearing and keyboard dismissal. This remains sample-only DEV UI.

Visit editor follow-up: job/address/contact/phone/carrier/claim, explicit Run
group, optional arrival, activity multi-select pills with independent crew
assignments, equipment/access/work notes. Sample edits retain unknown record
fields and per-activity people; waiting items need no scheduled date. Browser
test verifies save/reopen retains details and distinct crews. No backend schema
or shared customer write behavior is implied; live job facts must use the agreed
canonical job model rather than independently copied visit fields at integration.

DEV presentation follow-up: displayed full dates and editor entry use MM/DD/YY;
stored values remain ISO. Activity pills/strips use blue Monitor, green Initial,
orange Demo, purple Contents, teal Equipment, with amber Pending, gray Hold and
red Canceled status strips. Labels remain visible independently of color. These
are local presentation choices, not schema changes. Browser suites passed and
the actual DEV shell confirmed three columns and loaded theme after restart.

Validated both calendar browser suites. No shared schema or live-data changes.
DEV now chooses an available port in 53100–53199: pywebview randomly selected
4045, which Edge rejected with ERR_UNSAFE_PORT. A socket regression test checks
the safe range and that occupied ports are skipped. Installed Main is unchanged.

### DEV testing handoff — calendar range and Run groups

OneLoss owner, branch `main-lops-style-pivot`: DEV-only Schedule route now opens
`calendar_preview.html` inside the normal shell. Main route is unchanged. This
remains sample/in-memory UI, not shared persistence or a deployment.

- Default 3 Days, plus Week and Month; month overflow opens the selected day.
- Day columns separate Monitor and Work To Be Performed and scroll independently.
- Page scroll exposes the three TBS groups, three Pending groups, and On Hold,
  each with its own scrollable list and entry dates. These are undated queues,
  not duplicate booked visits. They remain visible beneath calendar views.
- Populated synthetic examples and paper-style Legacy preview are available.
  Legacy is not yet an exact reproduction of the original Run or print-ready.
- Verified `tests/weekly_calendar.cjs` and `tests/calendar_preview.cjs`, including
  month navigation/drilldown, grouped queues and actual page/column scroll.
- `tools/dev_schedule_check.py` opens the real DEV Schedule and reports loaded
  theme tokens. The old standalone preview server rooted assets incorrectly;
  the main DEV shell serves shared CSS from the correct root.
- L OPS: no schema/API changes to adopt. Shared identity/source-of-truth review
  above is still required. Reconstruction remains deferred.

Read the [full L OPS agent guide](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/README.md) before transferring features. It covers web CRM, Expo phone/iPad app, architecture, shared data, roles, run/visit crew assignments, media, documents, forms/signing, build commands, tests and remaining work.

- [Product decisions](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/product.md)
- [Architecture](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/architecture.md)
- [Builds and validation](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/builds.md)
- [Data and permissions](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/data-and-access.md)
- [Current status](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/status.md)
- [Transfer protocol](https://github.com/ManTreeJoe/l-ops-crm/blob/main/docs/agent-guide/cross-repo.md)
- [Local intake mapping](intake-parity.md)

## EMS Tools remains a business-workflow reference
`new_loss_intake.py` has mature carrier intake parsing and template/folder/CompanyCam workflows. The new web intake now has corresponding contact, loss, claim/policy, adjuster and property/notes fields. Its parser fills explicit recognized labels for review; external provisioning and fallback parsing are not fully ported.

The user wants useful features to move in both directions. Shared domain contracts and fixtures should stay compatible, while Python desktop and TypeScript web/native rendering remain platform-specific. Tech assignments belong to dated runs/visits; permanent job contacts and Lead Tech staff designation are separate.

## No automatic DB merger
The legacy DB and new platform DB are not yet one database. Do read-only comparisons, agree stable IDs and source-of-truth/conflict rules, and build a reversible migration before shared writes. Avoid destructive changes to the working legacy app.

## Publication caveat
### 2026-10-03 — Legacy Run drag-and-drop

Branch `main-lops-style-pivot`: Legacy sample Run rows now share calendar pointer feedback and support drops within/across Run sections, including empty groups. Destination queue/group/date populate the review editor; Upcoming proposes the following day for review. Apply retains identity/details and inserts at the chosen position; Cancel leaves the original row untouched. Browser tests verify Legacy Monitor-to-Work placement, cancellation and duplicate prevention alongside existing calendar regressions. Render inspected; UI-design guidance preserved the paper-style layout. No live writes, schema changes or L OPS database updates.

### 2026-10-02 — Visible calendar drag feedback

Branch `main-lops-style-pivot`: DEV sample cards now use pointer-following ghosts, insertion placeholders, destination highlights and a short landing/return animation, referencing the existing job-board interaction. Escape cancels; reduced-motion skips the animation. Apply/Cancel review still owns the actual sample move. Added browser checks for visible ghost/placeholder and Escape cleanup; full preview and calendar regression tests pass. No schema or live-write changes; no L OPS update required. UI-design guidance kept existing controls and click-to-edit access.

### 2026-10-02 — All calendar cards and job search

Branch: `main-lops-style-pivot`. Extended DEV calendar dragging to scheduled cards as well as waiting cards. Drops review the existing visit on the target day, preserving its identity and details. Added a compact top job-name/address search with existing-visit and not-yet-scheduled sample results. Selecting an existing visit edits it instead of inserting a duplicate. Browser tests cover scheduled moves, new sample additions, repeated selection, empty results, and existing calendar regressions. Render inspected at desktop size.

UI-design guidance kept the existing compact controls and click-to-edit fallback. This remains in-memory sample functionality only; no shared schema or live writes changed. L OPS has no required database changes from this handoff.

### 2026-10-02 — Waiting work drag-to-schedule DEV handoff

Branch: `main-lops-style-pivot`. The sample calendar now accepts waiting-work drops onto three-day/week columns and month cells. A drop opens the visit editor with Scheduled and the target date selected; Apply replaces the same sample record, while Cancel leaves Waiting unchanged. Job details and activity assignments are retained. Click-to-edit remains available without dragging. Browser tests cover cancel/apply and duplicate prevention; the existing calendar suite also passes.

No database/schema, Trello, Word, or live scheduling writes were added. L OPS does not need a schema update for this UI-only change. Shared persistence remains subject to a coordinated contract before implementation.

This is a documentation snapshot. Some new-platform code is still local/uncommitted; the mobile repo has no remote yet. Verify the actual source revision and migration state before assuming a described feature is available from GitHub or deployed. No production release is implied by these notes.
